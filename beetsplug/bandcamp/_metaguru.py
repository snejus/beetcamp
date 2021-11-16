"""Module for parsing bandcamp metadata."""
import itertools as it
import json
import operator as op
import re
from collections import defaultdict
from datetime import date, datetime
from functools import partial
from math import floor
from typing import Any, Dict, Iterable, List, Optional, Pattern, Set
from unicodedata import normalize

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

_catalognum = r"""(\b
    (?![A-z][a-z]+\ [0-9]+|EP |C\d\d|(?i:vol(ume)?|record|session|disc|artist)|VA|[A-Z][0-9]\b)
    (
        [A-Z]+[ ]\d   # must include at least one number
      | [A-z$]+\d+([.]\d)?
      | (
          [A-z]+([-.][A-Z]+)?    # may include a space before the number(s)
          [-.]?
          (
            [ ]\d{2,3}   # must include at least one number
            | \d{1,3}[.]\d+ # may end with .<num>
            | \d{1,4}
          )
          (?:
            | (?=-?CD)  # may end with -CD which we ignore
            | [A-Z]     # may end with a single capital letter
          )?
      )
    )\b(?![0-9-/])
)
"""
rm_strings = [
    "limited edition",
    "various artists?|va",
    "free download|free dl|free\\)",
    "vinyl|ep|lp",
    "e[.]p[.]",
]
CATNUM_PAT = {
    "desc": re.compile(rf"(?:^|\n|[Cc]at[^:]+[.:]\ ?){_catalognum}", re.VERBOSE),
    "in_parens": re.compile(rf"[\[\(|]{_catalognum}[|\]\)]", re.VERBOSE),
    "with_header": re.compile(r"(?:Catal[^:]+: *)(\b[^\n]+\b)(?:[\]]*\n)"),
    "start_or_end": re.compile(rf"((^|\n){_catalognum}|{_catalognum}(\n|$))", re.VERBOSE),
}
PATTERNS: Dict[str, Pattern] = {
    "clean_title": re.compile(fr"(?i: ?\(?\b({'|'.join(rm_strings)})(\b\)?|$))"),
    "clean_incl": re.compile(r"(?i:(\(?incl|\((inc|tracks|.*remix( |es)))).*$"),
    "meta": re.compile(r".*dateModified.*", re.MULTILINE),
    "digital": [  # type: ignore
        re.compile(r"^(DIGI(TAL)? ?[\d.]+|Bonus\W{2,})\W*"),
        re.compile(
            r"(?i:[^\w\)]+(bandcamp[^-]+|digi(tal)?)(\W*(\W+|only|bonus|exclusive)\W*$))"
        ),
    ],
    "remix_or_ft": re.compile(r"\s(?i:[\[\(].*(mix|edit)|f(ea)?t\.).*"),
    "track_alt": re.compile(r"([ABCDEFGH]{1,3}[0-9])(\.|.?-\s|\s)"),
    "vinyl_name": re.compile(
        r'(?P<count>(?i:[1-5]|single|double|triple))(LP)? ?x? ?((7|10|12)" )?Vinyl'
    ),
}


def urlify(pretty_string: str) -> str:
    """Transform a string into bandcamp url."""
    name = pretty_string.lower().replace("'", "")
    return re.sub("--+", "-", re.sub(r"\W", "-", name, flags=re.ASCII)).strip("-")


class Helpers:
    @staticmethod
    def get_vinyl_count(name: str) -> int:
        conv = {"single": 1, "double": 2, "triple": 3}
        match = re.search(PATTERNS["vinyl_name"], name)
        if not match:
            return 1
        count: str = match.groupdict()["count"]
        return int(count) if count.isdigit() else conv[count.lower()]

    @staticmethod
    def clear_digi_only(name: str) -> str:
        """Return the track title which is clear from digi-only artifacts."""
        clean_name = name
        for pat in PATTERNS["digital"]:  # type: ignore
            clean_name = pat.sub("", clean_name)
        return clean_name

    @staticmethod
    def parse_track_name(name: str, delim: str) -> Dict[str, str]:
        track = defaultdict(str)

        # remove leading numerical index if found
        name = re.sub(r"^[01]?[0-9][. ] ?(?=[A-Z])", "", name).strip(", ")

        # match track alt and remove it from the name
        match = PATTERNS["track_alt"].match(name)
        if match:
            track["track_alt"] = match.expand(r"\1")
            name = name.replace(track["track_alt"], "")

        # do not strip a period from the end since it could end with an abbrev
        name = name.lstrip(".")
        if delim:
            parts = re.split(fr" ?[{delim}] | [{delim}] ?", name.strip(",-| "))
            track["title"] = parts.pop(-1)  # title is always given
            if parts:  # whatever is left must be the artist
                track["artist"] = ", ".join(parts).strip(", ")
        else:
            track["title"] = name

        track["main_title"] = PATTERNS["remix_or_ft"].sub("", track["title"])
        return track

    @staticmethod
    def get_track_artist(parsed_artist, raw_track, albumartist):
        # type: (Optional[str], JSONDict, str) -> str
        """Return the first of the following options, if found:
        1. Parsed artist from the track title
        2. Artist specified by Bandcamp (official)
        3. Albumartist (worst case scenario)
        """
        official_artist = raw_track.get("byArtist", {}).get("name", "")
        return parsed_artist or official_artist or albumartist

    @staticmethod
    def parse_catalognum(album, disctitle, description, label, **kwargs):
        # type: (str, str, str, str, Any) -> str
        """Try getting the catalog number looking at various fields."""
        esc_label = re.escape(label)
        cases = [
            (CATNUM_PAT["in_parens"], album),
            (CATNUM_PAT["start_or_end"], album),
            (CATNUM_PAT["with_header"], description),
            (CATNUM_PAT["in_parens"], description),
            (CATNUM_PAT["desc"], description),
            (CATNUM_PAT["start_or_end"], disctitle),
            (re.compile(rf"\ {_catalognum}(?:\n|$)", re.VERBOSE), description),
        ]
        if label:
            # low prio: if label name is followed by digits, it may form a cat number
            esc = rf"{esc_label}\ ?[A-Z]?[0-9]+[A-Z]?"
            cases.append((re.compile(rf"(^{esc})|({esc}$)", re.IGNORECASE), album))

        search = lambda x: x[0].search(x[1])
        strip = lambda x: x.groups()[0].strip() if x and len(x.groups()) else ""
        matches: Iterable[str] = filter(op.truth, map(strip, map(search, cases)))

        artists = set(map(str.casefold, kwargs.get("artists") or []))
        if artists:
            matches = list(matches)
            matches = it.filterfalse(lambda x: x.casefold() in artists, matches)
        return next(it.chain(matches, [""]))

    @staticmethod
    def get_duration(source: JSONDict) -> int:
        def dur(item: JSONDict) -> bool:
            return item.get("name") == "duration_secs"

        try:
            return next(filter(dur, source.get("additionalProperty", []))).get("value", 0)
        except (StopIteration, KeyError):
            return 0

    @staticmethod
    def clean_name(name: str, *args: str, remove_extra: bool = False) -> str:
        """Return clean album name / track title.
        If `remove_extra`, remove info from within the parentheses (usually remix info).
        """
        # catalognum, album, albumartist
        for arg in filter(op.truth, args):
            name = re.sub(rf"(?i:[^\w\]\)]*{re.escape(arg)}\W*)", " ", name)
        for pat, repl in [
            (r"  +", " "),  # multiple spaces
            (r"\( +|(- )?\(+", "("),  # rubbish that precedes opening parenthesis
            (r" +\)|\)+", ")"),  # rubbish spaces that precede closing parenthesis
            ('"', ""),  # double quote anywhere in the string
        ]:
            name = re.sub(pat, repl, name)
        # redundant information about 'remixes from xyz'
        if remove_extra:
            name = PATTERNS["clean_incl"].sub("", name)
        return PATTERNS["clean_title"].sub("", name).strip(" -|/'")

    @staticmethod
    def get_genre(keywords: Iterable[str], config: JSONDict) -> Iterable[str]:
        """Verify each keyword against the list of MusicBrainz genres and return
        a comma-delimited list of valid ones, where validity depends on the mode:
          * classical: valid only if the entire keyword is found in the MB genres list
          * progressive: above + if each of the words is a valid MB genre since it is
            effectively a subgenre.
          * psychedelic: above + if the last word is a valid MB genre

        If a keyword is part of another keyword (genre within a sub-genre), exclude it.
        For example,
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
    html: str
    meta: JSONDict
    config: JSONDict

    _media: Dict[str, str]
    _singleton = False
    excluded_fields: Set[str] = set()

    def __init__(self, html, config=None) -> None:
        self.html = html
        self.config = config or {}
        self.meta = {}
        self.excluded_fields.update(set(self.config.get("exclude_extra_fields") or []))
        match = re.search(PATTERNS["meta"], html)
        if match:
            self.meta = json.loads(match.group())

        self._media = self.meta.get("albumRelease", [{}])[0]
        try:
            media_index = self._get_media_reference(self.meta)
        except (KeyError, AttributeError):
            pass
        else:
            # if preference is given and the format is available, use it
            for preference in (self.config.get("preferred_media") or "").split(","):
                if preference in media_index:
                    self._media = media_index[preference]
                    break

    @cached_property
    def comments(self) -> str:
        """Return release, media descriptions and credits separated by
        the configured separator string.
        """
        parts = [self.meta.get("description")]
        media_desc = self._media.get("description")
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
    def bandcamp_albumartist(self) -> str:
        """Return the official release albumartist.
        It is correct in half of the cases. In others, we usually find the label name.
        """
        match = re.search(r"Artist:([^\n]+)", self.all_media_comments)
        if match:
            return str(match.groups()[0].strip())

        albumartist = self.meta["byArtist"]["name"].replace("various", VA)
        album = self.album_name
        if self.label == albumartist:
            albumartist = self.parse_track_name(album, "-").get("artist") or albumartist

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
    def media_name(self) -> str:
        """Return the human-readable version of the media format."""
        return MEDIA_MAP.get(self._media.get("musicReleaseFormat", ""), DIGI_MEDIA)

    @cached_property
    def disctitle(self) -> str:
        """Return medium's disc title if found."""
        return "" if self.media_name == DIGI_MEDIA else self._media.get("name", "")

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
            artists=self.all_artists,
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

    def track_delimiter(self, raw_tracks: List[JSONDict]) -> str:
        """Return the track parts delimiter that is in effect in the current release.
        In some (weird) situations track parts are delimited by a pipe pipe character
        instead of the usual dash. This checks every track looking for our delimiters
        and returns the one that is found _in each of the track names_.
        """
        get = op.itemgetter
        names = list(map(get("name"), map(get("item"), raw_tracks)))
        for delim in "-|":
            delims = it.repeat(fr"[{delim}] | [{delim}]")
            match_count = sum(map(bool, map(re.search, delims, names)))
            if len(names) - match_count <= 1:
                return delim
        return ""

    @cached_property
    def tracks(self) -> List[JSONDict]:
        """Parse relevant details from the tracks' JSON."""
        try:
            raw_tracks = self.meta["track"].get("itemListElement", [])
        except KeyError:
            raw_tracks = [{"item": self.meta}]

        albumartist = self.bandcamp_albumartist
        catalognum = self.catalognum
        delim = self.track_delimiter(raw_tracks)
        tracks = []
        for item, position in map(op.itemgetter("item", "position"), raw_tracks):
            name = self.clear_digi_only(item["name"])
            track: JSONDict = defaultdict(str)
            track.update(
                digi_only=name != item["name"],
                index=position or 1,
                medium_index=position or 1,
                track_id=item.get("@id"),
                length=self.get_duration(item),
                **self.parse_track_name(self.clean_name(name, catalognum), delim),
            )
            track["artist"] = self.get_track_artist(track["artist"], item, albumartist)
            lyrics = item.get("recordingOf", {}).get("lyrics", {}).get("text")
            if lyrics:
                track["lyrics"] = lyrics.replace("\r", "")
            tracks.append(track)

        return tracks

    @cached_property
    def track_artists(self) -> Set[str]:
        artists = {(t.get("artist") or "") for t in self.tracks}
        artists.discard("")
        return artists

    @cached_property
    def bandcamp_titles(self) -> List[str]:
        try:
            tracks = self.meta["track"].get("itemListElement", [])
        except KeyError:
            tracks = [{"item": self.meta}]

        return list(
            map(
                lambda x: (x.get("byArtist", x) or x).get("name") or "",
                map(op.itemgetter("item"), tracks),
            )
        )

    @cached_property
    def all_artists(self) -> Set[str]:
        def only_artist(name: str) -> str:
            return re.sub(r" - .*", "", PATTERNS["track_alt"].sub("", name))

        artists = set()
        titles = self.bandcamp_titles
        for t in titles:
            if " - " in t:
                artists.add(only_artist(t))
            else:
                artists.add(t)

        match = re.search(r"Artist:([^\n]+)", self.all_media_comments)
        if match:
            albumartist = match.groups()[0].strip()
        else:
            albumartist = self.meta["byArtist"]["name"]
        artists.update(albumartist.split(", "))
        return artists

    @cached_property
    def is_single(self) -> bool:
        return self._singleton or len(set(t.get("main_title") for t in self.tracks)) == 1

    @cached_property
    def is_lp(self) -> bool:
        maybe_here = [self.album_name, self.disctitle, self.comments]
        return any(map(lambda x: " LP" in x, maybe_here))

    @cached_property
    def is_ep(self) -> bool:
        maybe_here = [self.album_name, self.disctitle, self.comments]
        return any(map(lambda x: " EP" in x, maybe_here))

    @cached_property
    def is_va(self) -> bool:
        track_artists = self.track_artists
        track_count = len(self.tracks)
        unique = set(map(lambda x: re.sub(r" ?[,x].*", "", x).lower(), track_artists))
        return (
            VA.casefold() in self.album_name.casefold()
            or len(unique) == track_count
            or (
                len(unique) > 1
                and not {*self.bandcamp_albumartist.split(", ")}.issubset(unique)
                and track_count >= 4
            )
            or (len(unique) > 1 and len(self.tracks) >= 4)
        )

    @cached_property
    def albumartist(self) -> str:
        """Take into account the release contents and return the actual albumartist.
        * 'Various Artists' for a compilation release
        * If every track has the same author, treat it as the albumartist
        """
        if self.albumtype == "compilation":
            return VA
        tartists = self.track_artists
        if len(tartists) == 1:
            first_tartist = tartists.copy().pop()
            if first_tartist != self.label:
                return first_tartist
        return self.bandcamp_albumartist

    @cached_property
    def albumtype(self) -> str:
        if self.is_lp:
            return "album"
        if self.is_ep:
            return "ep"
        if self.is_single:
            return "single"
        if self.is_va:
            return "compilation"
        return "album"

    @cached_property
    def va(self) -> bool:
        return self.albumtype == "compilation"

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

        return ", ".join(genres) or None

    @cached_property
    def clean_album_name(self) -> str:
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
        if not album:
            # try checking the description
            match = re.search(r"[:-] ?([\w ]+) [EL]P", self.all_media_comments)
            if match:
                album = match.expand(r"\1")
            else:
                album = self.catalognum
        return album

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
        fields = set(fields) - self.excluded_fields
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
            "style",
            "genre",
            "comments",
        ]
        common_data.update(self.get_fields(fields))
        reldate = self.release_date
        if reldate:
            common_data.update(self.get_fields(["year", "month", "day"], reldate))

        return common_data

    def _trackinfo(self, track: JSONDict, **kwargs: Any) -> TrackInfo:
        track.pop("digi_only")
        track.pop("main_title")
        track_info = TrackInfo(
            **self._common,
            **track,
            disctitle=self.disctitle or None,
            medium=1,
            **kwargs,
        )
        for field in set(track_info.keys()) & self.excluded_fields:
            track_info[field] = None

        return track_info

    @cached_property
    def singleton(self) -> TrackInfo:
        self._singleton = True
        track: JSONDict = {}
        if NEW_BEETS:
            track.update(**self._common_album, albumartist=self.albumartist)

        track.update(self.tracks[0].copy())
        track.update(self.parse_track_name(self.album_name, "-"))
        if not track.get("artist"):
            track["artist"] = self.albumartist
        track["title"] = self.clean_name(track["title"])
        if NEW_BEETS:
            artist, title = track["artist"], track["title"]
            track["album"] = "{} - {}".format(artist, title)
        return self._trackinfo(track, medium_total=1)

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
        album_info.update(self.get_fields(["va"]))
        return album_info
