"""Module for parsing bandcamp metadata."""
import itertools as it
import json
import operator as op
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from functools import partial
from html import unescape
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Pattern,
    Set,
    Tuple,
    Union,
)
from unicodedata import normalize

from beets import config as beets_config
from beets.autotag.hooks import AlbumInfo, TrackInfo
from cached_property import cached_property
from pkg_resources import get_distribution, parse_version
from pycountry import countries, subdivisions

from .genres_lookup import GENRES

NEW_BEETS = get_distribution("beets").parsed_version >= parse_version("1.5.0")

JSONDict = Dict[str, Any]

COUNTRY_OVERRIDES = {
    "Russia": "RU",  # pycountry: Russian Federation
    "The Netherlands": "NL",  # pycountry: Netherlands
    "UK": "GB",  # pycountry: Great Britain
    "D.C.": "US",
    "South Korea": "KR",  # pycountry: Korea, Republic of
}
DATA_SOURCE = "bandcamp"
WORLDWIDE = "XW"
DIGI_MEDIA = "Digital Media"
MEDIA_MAP = {
    "VinylFormat": "Vinyl",
    "CDFormat": "CD",
    "CassetteFormat": "Cassette",
    "DigitalFormat": DIGI_MEDIA,
}
VA = "Various Artists"

_catalognum = r"""(?<![/@])(\b
(?!\W|VA|EP[ ]|L[PC][ ]|.*[ ][0-9]KG|AT[ ]0|GC1)
(?!(?i:vol |mp3|christ|vinyl|disc|session|record|artist|the |maxi ))
(?![^.]+shirt)
(
      [A-Z .]+\d{3}         # HANDS D300
    | [A-z ][ ]0\d{2,3}     # Persephonic Sirens 012
    | [A-Z-]{2,}\d+         # RIV4
    | [A-Z]+[A-Z.$-]+\d{2,} # USE202, HEY-101, LI$025
    | [A-Z.]{2,}[ ]\d{1,3}  # OBS.CUR 9
    | \w+[A-z]0\d+          # 1ØPILLS018, fa036
    | [a-z]+(cd|lp)\d+      # ostgutlp45
    | [A-z]+\d+-\d+         # P90-003
)
( # optionally followed by
      [ ]?[A-Z]     # IBM001V
    | [.][0-9]+     # ISMVA002.1
    | -?[A-Z]+      # PLUS8024CD
)?
\b)"""

CATNUM_PAT = {
    "with_header": re.compile(fr"(?:Cat[^:]+:[ \W]*){_catalognum}", re.VERBOSE),
    "start_or_end": re.compile(fr"((^|\n){_catalognum}|{_catalognum}(\n|$))", re.VERBOSE),
    "anywhere": re.compile(_catalognum, re.VERBOSE),
}

rm_strings = [
    "limited edition",
    "various artists?|va|vinyl",
    r"free download|free dl|free\)",
]
PATTERNS: Dict[str, Pattern] = {
    "clean_title": re.compile(fr"(?i: ?[\[\(]?\b({'|'.join(rm_strings)})(\b[\]\)]?|$))"),
    "clean_incl": re.compile(
        r"((\(?incl|\((inc|tracks|.*remix( |es)))([^)]+\)|.*))", re.I
    ),
    "meta": re.compile(r".*dateModified.*", re.MULTILINE),
    "digital": [  # type: ignore
        re.compile(r"^(DIGI(TAL)? ?[\d.]+|Bonus\W{2,})\W*"),
        re.compile(
            r"[^\w\)]+(bandcamp[^-]+|digi(tal)?)(\W*(\W+|only|bonus|exclusive)\W*$)", re.I
        ),
    ],
    "remix_or_ft": re.compile(r" [\[\(].*(?i:mix|edit|f(ea)?t\.).*"),
    "track_alt": re.compile(r"([ABCDEFGH]{1,3}[0-6])\W+", re.I),
    "vinyl_name": re.compile(r"[1-5](?= ?(xLP|LP|x))|single|double|triple", re.I),
}


def urlify(pretty_string: str) -> str:
    """Transform a string into bandcamp url."""
    name = pretty_string.lower().replace("'", "").replace(".", "")
    return re.sub("--+", "-", re.sub(r"\W", "-", name, flags=re.ASCII)).strip("-")


class Helpers:
    @staticmethod
    def get_vinyl_count(name: str) -> int:
        conv = {"single": 1, "double": 2, "triple": 3}
        for match in PATTERNS["vinyl_name"].finditer(name):
            count = match.group()
            return int(count) if count.isdigit() else conv[count.lower()]
        return 1

    @staticmethod
    def clear_digi_only(name: str) -> str:
        """Return the track title which is clear from digi-only artifacts."""
        clean_name = name
        for pat in PATTERNS["digital"]:  # type: ignore
            clean_name = pat.sub("", clean_name)
        return clean_name

    @staticmethod
    def parse_track_name(name: str, delim: str = "-") -> Dict[str, str]:
        track: Dict[str, str] = defaultdict(str)

        # match track alt and remove it from the name
        def get_trackalt(name: str) -> Tuple[str, str]:
            match = PATTERNS["track_alt"].match(name)
            track_alt = ""
            if match:
                track_alt = match.expand(r"\1").upper()
                # do not strip a period from the end since it may end with an abbrev
                name = name.replace(match.group(), "")
            return name, track_alt

        name, track_alt = get_trackalt(name)
        parts = name.split(f" {delim} ")
        if len(parts) == 1:
            parts = re.split(fr" [{delim}]|[{delim}] ", name)
        parts = list(map(lambda x: x.strip(" -"), parts))

        title = parts.pop(-1)
        artist = ", ".join(sorted(set(parts)))
        artist = re.sub(r" \(.*mix.*", "", artist).strip(",")
        artist = re.sub(r"[(](f(ea)?t.*)[)]", r"\1", artist)
        if not track_alt:
            title, track_alt = get_trackalt(title)
        track.update(title=title, artist=artist)
        if track_alt:
            track.update(track_alt=track_alt)
        track.update(main_title=PATTERNS["remix_or_ft"].sub("", title))
        return track

    @staticmethod
    def parse_catalognum(album, disctitle, description, label, **kwargs):
        # type: (str, str, str, str, Any) -> str
        """Try getting the catalog number looking at text from various fields."""
        cases = [
            (CATNUM_PAT["with_header"], description),
            (CATNUM_PAT["anywhere"], disctitle),
            (CATNUM_PAT["anywhere"], album),
            (CATNUM_PAT["start_or_end"], description),
            (CATNUM_PAT["anywhere"], description),
        ]
        if label:
            # if label name is followed by digits, it may form a cat number
            esc = re.escape(label)
            cases.insert(0, (re.compile(fr"(?i:({esc} ?[A-Z]?\d+[A-Z]?))"), album))

        def find(pat: Pattern, string: str) -> str:
            try:
                return pat.search(string).groups()[0].strip()  # type: ignore
            except (IndexError, AttributeError):
                return ""

        ignored = set(map(str.casefold, kwargs.get("artists") or []) or [None, ""])

        def not_ignored(option: str) -> bool:
            return bool(option) and option.casefold() not in ignored

        try:
            return next(filter(not_ignored, it.starmap(find, cases)))
        except StopIteration:
            return ""

    @staticmethod
    def get_duration(source: JSONDict) -> int:
        try:
            h, m, s = map(int, re.findall(r"[0-9]+", source["duration"]))
            return h * 3600 + m * 60 + s
        except KeyError:
            return 0

    @staticmethod
    def clean_name(name: str, *args: str, remove_extra: bool = False) -> str:
        """Return clean album name / track title.
        If `remove_extra`, remove info from within the parentheses (usually remix info).
        """
        replacements: List[Tuple[str, Union[str, Callable]]] = [
            (r"  +", " "),  # multiple spaces
            (r"\( +|(- )?\(+", "("),  # rubbish that precedes opening parenthesis
            (r" \)+|(?<=(?i:.mix|edit))\)+$", ")"),
            ('"', ""),  # double quote anywhere in the string
            # spaces around dash in remixer names within parens
            (r"(\([^)]+) - ([^(]+\))", r"\1-\2"),
            (r"[\[(][A-Z]+[0-9]+[\])]", ""),
            # uppercase EP and LP, and remove surrounding parens / brackets
            (r"(\S*(\b(?i:[EL]P)\b)\S*)", lambda x: x.expand(r"\2").upper()),
        ]
        for pat, repl in replacements:
            name = re.sub(pat, repl, name).strip()
        for arg in filter(op.truth, args):
            esc = re.escape(arg)
            name = re.sub(fr"[^'\])\w]*(?i:{esc})[^'(\[\w]*", " ", name).strip()
        if remove_extra:
            # redundant information about 'remixes from xyz'
            name = PATTERNS["clean_incl"].sub("", name)
        name = PATTERNS["clean_title"].sub("", name).strip(" -|/")
        return re.sub("^'([^']+)'$", r"\1", name)

    @staticmethod
    def clean_ep_lp_name(album: str, artists: List[str]) -> str:
        """Parse album name - which precedes 'LP' or 'EP' in the release title.
        Attempt to remove artist names from the parsed string:
        * If we're only left with 'EP', it means that the album name is made up of those
          artists - in that case we keep them.
        * Otherwise, we will end up cleaning a release title such as 'Artist Album EP',
          where the artist is not clearly separated from the album name.
        """
        match = re.search(r"[^-|]+[EL]P", album)
        if not match:
            return ""
        album_with_artists = match.group().strip()
        clean_album = Helpers.clean_name(album_with_artists, *artists)
        return album_with_artists if len(clean_album) == 2 else clean_album

    @staticmethod
    def clean_track_names(names: List[str], catalognum: str = "") -> List[str]:
        """Remove catalogue number and leading numerical index if they are found."""
        if catalognum:
            names = list(map(lambda x: Helpers.clean_name(x, catalognum), names))

        len_tot = len(names)
        if len_tot > 1 and sum(map(lambda x: int(x[0].isdigit()), names)) > len_tot / 2:
            pat = re.compile(r"^\d+\W+")
            names = list(map(lambda x: pat.sub("", x), names))
        return names

    @staticmethod
    def track_delimiter(names: List[str]) -> str:
        """Return the track parts delimiter that is in effect in the current release.
        In some (unusual) situations track parts are delimited by a pipe character
        instead of dash.

        This checks every track looking for the first character (see the regex for
        exclusions) that splits it. The character that split the most and
        at least half of the tracklist is the character we need.
        """

        def get_delim(string: str) -> str:
            match = re.search(r" ([^\w&()+ ]) ", string)
            return match.expand(r"\1") if match else "-"

        most_common = Counter(map(get_delim, names)).most_common(1)
        if not most_common:
            return ""
        delim, count = most_common.pop()
        return delim if (len(names) == 1 or count > len(names) / 2) else "-"

    @staticmethod
    def get_genre(keywords: Iterable[str], config: JSONDict) -> Iterable[str]:
        """Return a comma-delimited list of valid genres, using MB genres for reference.

        Verify each keyword's (potential genre) validity w.r.t. the configured `mode`:
          * classical: valid only if the _entire keyword_ matches a MB genre in the list
          * progressive: either above or if each of the words matches MB genre - since it
            is effectively a subgenre.
          * psychedelic: either one of the above or if the last word is a valid MB genre.
            This allows to be flexible regarding the variety of potential genres while
            keeping away from spammy ones.

        Once we have the list of keywords that make it through the mode filters,
        an additional filter is executed:
          * if a keyword is _part of another keyword_ (genre within a sub-genre),
            the more generic option gets excluded, for example,
            >>> get_genre(['house', 'garage house', 'glitch'], "classical")
            'garage house, glitch'
        """
        # use a list to keep the initial order
        genres: List[str] = []
        valid_mb_genre = partial(op.contains, GENRES)

        def is_included(kw: str) -> bool:
            return any(map(lambda x: re.search(x, kw), config["always_include"]))

        def valid_for_mode(kw: str) -> bool:
            if config["mode"] == "classical":
                return kw in GENRES

            words = map(str.strip, kw.split(" "))
            if config["mode"] == "progressive":
                return kw in GENRES or all(map(valid_mb_genre, words))

            return valid_mb_genre(kw) or valid_mb_genre(list(words)[-1])

        # expand badly delimited keywords
        split_kw = partial(re.split, r"[.] | #| - ")
        for kw in it.chain(*map(split_kw, keywords)):
            # remove full stops and hashes and ensure the expected form of 'and'
            kw = re.sub("[.#]", "", str(kw)).replace("&", "and")
            if kw not in genres and (is_included(kw) or valid_for_mode(kw)):
                genres.append(kw)

        unique_genres = set(genres)

        def duplicate(genre: str) -> bool:
            """Return True if genre is contained within another genre or if,
            having removed spaces from every other, there is a duplicate found.
            It is done this way so that 'dark folk' is kept while 'darkfolk' is removed,
            and not the other way around.
            """
            others = unique_genres - {genre}
            others = others.union(map(lambda x: x.replace(" ", ""), others))
            return any(map(lambda x: genre in x, others))

        return it.filterfalse(duplicate, genres)

    @staticmethod
    def _get_media_reference(meta: JSONDict) -> JSONDict:
        """Get release media from the metadata, excluding bundles.
        Return a dictionary with a human mapping (Digital|CD|Vinyl|Cassette) -> media.
        """

        def is_bundle(fmt: JSONDict) -> bool:
            return "bundle" in (fmt.get("name") or "").casefold()

        media: Dict[str, JSONDict] = {}
        for _format in it.filterfalse(is_bundle, meta["albumRelease"]):
            try:
                medium = _format["musicReleaseFormat"]
            except KeyError:
                continue
            human_name = MEDIA_MAP[medium]
            media[human_name] = _format
        return media


class Metaguru(Helpers):
    meta: JSONDict
    config: JSONDict
    _singleton = False
    va_name: str = VA

    def __init__(self, meta: JSONDict, config: Optional[JSONDict] = None) -> None:
        self.meta = meta
        self.config = config or {}
        self.va_name = beets_config["va_name"].as_str() or self.va_name

    @classmethod
    def from_html(cls, html: str, config: JSONDict = None) -> "Metaguru":
        try:
            meta = json.loads(re.search(PATTERNS["meta"], html).group())  # type: ignore
            meta["tracks"] = list(map(unescape, re.findall(r"^[0-9]+[.] .*", html, re.M)))
        except AttributeError as exc:
            raise AttributeError("Could not find release metadata JSON") from exc

        return cls(meta, config)

    @cached_property
    def excluded_fields(self) -> Set[str]:
        return set(self.config.get("excluded_fields") or [])

    @cached_property
    def comments(self) -> str:
        """Return release, media descriptions and credits separated by
        the configured separator string.
        """
        parts = [self.meta.get("description")]
        media_desc = self.media.get("description")
        if media_desc and not media_desc.startswith("Includes high-quality"):
            parts.append(media_desc)

        parts.append(self.meta.get("creditText"))
        sep = self.config["comments_separator"]
        return sep.join(filter(op.truth, parts)).replace("\r", "")

    @cached_property
    def all_media_comments(self) -> str:
        get_desc = op.methodcaller("get", "description", "")
        return "\n".join(
            [
                # self.comments,
                *map(get_desc, self.meta.get("albumRelease", {})),
                self.comments,
            ]
        )

    @cached_property
    def album_name(self) -> str:
        match = re.search(r"Title:([^\n]+)", self.all_media_comments)
        if match:
            return match.groups()[0].strip()
        return self.meta["name"]

    @cached_property
    def label(self) -> str:
        match = re.search(r"Label:([^/,\n]+)", self.all_media_comments)
        if match:
            return match.groups()[0].strip()

        try:
            return self.meta["albumRelease"][0]["recordLabel"]["name"]
        except (KeyError, IndexError):
            return self.meta["publisher"]["name"]

    @cached_property
    def album_id(self) -> str:
        return self.meta["@id"]

    @cached_property
    def artist_id(self) -> str:
        try:
            return self.meta["byArtist"]["@id"]
        except KeyError:
            return self.meta["publisher"]["@id"]

    @cached_property
    def raw_albumartist(self) -> str:
        match = re.search(r"Artists?:([^\n]+)", self.all_media_comments)
        if match:
            return str(match.groups()[0].strip())
        return self.meta["byArtist"]["name"]

    @cached_property
    def bandcamp_albumartist(self) -> str:
        """Return the official release albumartist.
        It is correct in half of the cases. In others, we usually find the label name.
        """
        albumartist = self.raw_albumartist
        if self.label == albumartist:
            album = self.album_name
            albumartist = self.parse_track_name(album).get("artist") or albumartist

        return re.sub(r"(?i:, ft.*remix.*)", "", albumartist)

    @cached_property
    def image(self) -> str:
        # TODO: Need to test
        image = self.meta.get("image", "")
        return image[0] if isinstance(image, list) else image

    @cached_property
    def release_date(self) -> Optional[date]:
        """Parse the datestring that takes the format like below and return date object.
        {"datePublished": "17 Jul 2020 00:00:00 GMT"}

        If the field is not found, return None.
        """
        rel = self.meta.get("datePublished")
        if rel:
            return datetime.strptime(re.sub(r" [0-9]{2}:.+", "", rel), "%d %b %Y").date()
        return rel

    @cached_property
    def albumstatus(self) -> str:
        reldate = self.release_date
        return "Official" if reldate and reldate <= date.today() else "Promotional"

    @cached_property
    def media(self) -> JSONDict:
        media = self.meta.get("albumRelease", [{}])[0]
        try:
            media_index = self._get_media_reference(self.meta)
        except (KeyError, AttributeError):
            pass
        else:
            # if preference is given and the format is available, use it
            for preference in (self.config.get("preferred_media") or "").split(","):
                if preference in media_index:
                    media = media_index[preference]
                    break
        return media

    @cached_property
    def media_name(self) -> str:
        """Return the human-readable version of the media format."""
        return MEDIA_MAP.get(self.media.get("musicReleaseFormat", ""), DIGI_MEDIA)

    @cached_property
    def disctitle(self) -> str:
        """Return medium's disc title if found."""
        return "" if self.media_name == DIGI_MEDIA else self.media.get("name", "")

    @cached_property
    def mediums(self) -> int:
        return self.get_vinyl_count(self.disctitle) if self.media_name == "Vinyl" else 1

    @cached_property
    def catalognum(self) -> str:
        return self.parse_catalognum(
            self.album_name,
            self.disctitle,
            self.all_media_comments,
            self.label,
            artists=self.raw_artists,
        )

    @cached_property
    def country(self) -> str:
        try:
            loc = self.meta["publisher"]["foundingLocation"]["name"].rpartition(", ")[-1]
            name = normalize("NFKD", loc).encode("ascii", "ignore").decode()
            return (
                COUNTRY_OVERRIDES.get(name)
                or getattr(countries.get(name=name, default=object), "alpha_2", None)
                or subdivisions.lookup(name).country_code
            )
        except (ValueError, LookupError):
            return WORLDWIDE

    @cached_property
    def tracks(self) -> List[JSONDict]:
        """Parse relevant details from the tracks' JSON."""
        try:
            raw_tracks = self.meta["track"]["itemListElement"]
        except KeyError:
            raw_tracks = [{"item": self.meta, "position": 1}]
        if self._singleton:
            names = [raw_tracks[0].get("item").get("name") or ""]
        else:
            names = self.track_names
        delim = self.track_delimiter(names)
        names = self.clean_track_names(names, self.catalognum)
        tracks = []
        for item, position in map(op.itemgetter("item", "position"), raw_tracks):
            initial_name = names[position - 1]
            name = self.clear_digi_only(initial_name)
            track: JSONDict = defaultdict(
                str,
                digi_only=name != initial_name,
                index=position or 1,
                medium_index=position or 1,
                track_id=item.get("@id"),
                length=self.get_duration(item) or None,
                **self.parse_track_name(self.clean_name(name), delim),
            )
            track["artist"] = track["artist"] or self.bandcamp_albumartist
            lyrics = item.get("recordingOf", {}).get("lyrics", {}).get("text")
            if lyrics:
                track["lyrics"] = lyrics.replace("\r", "")
            tracks.append(track)

        return tracks

    @cached_property
    def track_artists(self) -> Set[str]:
        artists = {(t.get("artist") or "") for t in self.tracks} - {""}
        return artists

    @cached_property
    def unique_artists(self):
        pat = re.compile(r" (?:[x+]|vs|f(?:ea)?t\.?) |, ")
        split = map(lambda x: pat.split(x), self.track_artists)
        artists = set(it.chain(*split))
        for artist in list(artists):
            if " X " in artist and artist.upper() == artist:
                artists.discard(artist)
                artists.update(artist.split(" X "))
                continue

            subartists = artist.split(" & ")
            if len(subartists) > 1 and any(map(lambda x: x in artists, subartists)):
                artists.discard(artist)
                artists.update(subartists)
        return artists

    @cached_property
    def track_names(self) -> List[str]:
        raw_tracks = self.meta.get("tracks") or []
        return list(map(lambda x: x.split(". ", maxsplit=1)[1], raw_tracks))

    @cached_property
    def raw_artists(self) -> Set[str]:
        def only_artist(name: str) -> str:
            return re.sub(r" - .*", "", PATTERNS["track_alt"].sub("", name))

        artists = set(map(only_artist, self.track_names))
        artists.update(self.meta["byArtist"]["name"].split(", "))
        return artists

    @cached_property
    def is_single(self) -> bool:
        return self._singleton or len(set(t.get("main_title") for t in self.tracks)) == 1

    @cached_property
    def is_va(self) -> bool:
        track_artists = self.track_artists
        track_count = len(self.tracks)
        unique = set(map(lambda x: re.sub(r" ?[&,x].*", "", x).lower(), track_artists))
        return VA.casefold() in self.album_name.casefold() or (
            len(unique) > min(4, track_count - 2) and track_count >= 4
        )

    @cached_property
    def albumartist(self) -> str:
        """Take into account the release contents and return the actual albumartist.
        * 'Various Artists' (or `va_name` configuration option) for a compilation release
        * If every track has the same author, treat it as the albumartist
        """
        if self.va:
            return self.va_name

        return ", ".join(sorted(self.unique_artists))

    @cached_property
    def albumtype(self) -> str:
        text = "\n".join([self.album_name, self.disctitle, self.comments])
        lp_count = text.count(" LP")
        ep_count = text.count(" EP")
        if lp_count >= ep_count and lp_count:
            return "album"
        if ep_count > lp_count:
            return "ep"

        if self.is_single:
            return "single"
        if self.is_va:
            return "compilation"
        return "album"

    @cached_property
    def va(self) -> bool:
        return len(self.unique_artists) > 4

    @cached_property
    def style(self) -> Optional[str]:
        """Extract bandcamp genre tag from the metadata."""
        # expecting the following form: https://bandcamp.com/tag/folk
        tag_url = self.meta.get("publisher", {}).get("genre") or ""
        style = None
        if tag_url:
            style = tag_url.split("/")[-1]
            if self.config["genre"]["capitalize"]:
                style = style.capitalize()
        return style

    @cached_property
    def genre(self) -> Optional[str]:
        kws: Iterable[str] = map(str.lower, self.meta["keywords"])
        if self.style:
            exclude_style = partial(op.ne, self.style.lower())
            kws = filter(exclude_style, kws)

        genre_cfg = self.config["genre"]
        genres = self.get_genre(kws, genre_cfg)
        if genre_cfg["capitalize"]:
            genres = map(str.capitalize, genres)
        if genre_cfg["maximum"]:
            genres = it.islice(genres, genre_cfg["maximum"])

        return ", ".join(sorted(genres)) or None

    @cached_property
    def parsed_album_name(self) -> str:
        match = re.search(r"[:-] ?([\w ]+) [EL]P", self.all_media_comments)
        if match:
            return match.expand(r"\1")
        return self.catalognum

    @cached_property
    def clean_album_name(self) -> str:
        album = self.album_name
        if " EP" in album or " LP" in album:
            # EP and LP strings also get normalised during the cleanup,
            # which is important for the next step
            no_catlabel = self.clean_name(self.album_name, self.catalognum, self.label)
            return self.clean_ep_lp_name(no_catlabel, self.albumartist.split(", "))

        args = [self.catalognum]
        if not self._singleton:
            args.append(self.bandcamp_albumartist)
            args.append(self.albumartist)
            args.extend(self.albumartist.split(", "))
        # leave label name in place for compilations
        if self.albumtype == "compilation":
            # it could have been added as an albumartist already
            for _ in range(args.count(self.label)):
                args.remove(self.label)
        else:
            args.append(self.label)

        album = self.clean_name(self.album_name, *args, remove_extra=True)
        if album:
            return album
        return self.parsed_album_name

    @cached_property
    def _common(self) -> JSONDict:
        return dict(
            data_source=DATA_SOURCE,
            media=self.media_name,
            data_url=self.album_id,
            artist_id=self.artist_id,
        )

    def get_fields(self, fields: Iterable[str], src: object = None) -> JSONDict:
        """Return a mapping between unexcluded fields and their values."""
        fields = list(set(fields) - self.excluded_fields)
        if len(fields) == 1:
            field = fields.pop()
            return {field: getattr(self, field)}
        return dict(zip(fields, iter(op.attrgetter(*fields)(src or self))))

    @cached_property
    def _common_album(self) -> JSONDict:
        common_data: JSONDict = dict(album=self.clean_album_name)
        fields = [
            "label",
            "catalognum",
            "albumtype",
            "albumstatus",
            "country",
        ]
        if NEW_BEETS:
            fields.extend(["genre", "style", "comments"])
        common_data.update(self.get_fields(fields))
        reldate = self.release_date
        if reldate:
            common_data.update(self.get_fields(["year", "month", "day"], reldate))

        return common_data

    def _trackinfo(self, track: JSONDict, **kwargs: Any) -> TrackInfo:
        track.pop("digi_only", None)
        track.pop("main_title", None)
        if not NEW_BEETS:
            track.pop("lyrics", None)

        data = dict(
            **track,
            **self._common,
            disctitle=self.disctitle or None,
            medium=1,
            **kwargs,
        )
        for field in set(data.keys()) & self.excluded_fields:
            data.pop(field)

        return TrackInfo(**data)

    @cached_property
    def singleton(self) -> TrackInfo:
        self._singleton = True
        track: TrackInfo = self._trackinfo(self.tracks[0])
        if NEW_BEETS:
            track.update(self._common_album)
            track.pop("album", None)
        if not track.artist:
            track.artist = self.bandcamp_albumartist
        track.index = track.medium_index = track.medium_total = 1
        track.track_id = track.data_url
        return track

    @cached_property
    def album(self) -> AlbumInfo:
        """Return album for the appropriate release format."""
        tracks: Iterable[JSONDict] = self.tracks
        include_digi = self.config.get("include_digital_only_tracks")
        if not include_digi and self.media_name != DIGI_MEDIA:
            tracks = it.filterfalse(op.itemgetter("digi_only"), tracks)

        tracks = list(map(op.methodcaller("copy"), tracks))

        get_trackinfo = partial(self._trackinfo, medium_total=len(tracks))
        album_info = AlbumInfo(
            **self._common,
            **self._common_album,
            artist=self.albumartist,
            album_id=self.album_id,
            mediums=self.mediums,
            tracks=list(map(get_trackinfo, tracks)),
        )
        for key, val in self.get_fields(["va"]).items():
            setattr(album_info, key, val)
        return album_info
