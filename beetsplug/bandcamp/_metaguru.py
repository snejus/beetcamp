"""Module for parsing bandcamp metadata."""
import itertools as it
import json
import operator as op
import re
from collections import defaultdict
from datetime import date, datetime
from functools import partial, reduce
from typing import Any, Dict, Iterable, List, Optional, Pattern, Set
from unicodedata import normalize

from beets.autotag.hooks import AlbumInfo, TrackInfo
from cached_property import cached_property
from ordered_set import OrderedSet
from pkg_resources import get_distribution, parse_version
from pycountry import countries, subdivisions
from rich import print

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
    (?![A-z][a-z]+\ [0-9]+|EP |C\d\d|(?i:vol(ume)?|record|session|disc|artist)|VA|CD[0-9]*|[A-Z][0-9]\b)
    (
        [A-Z]+[ ]\d
      | [A-Z]+[.][A-Z]+[ ]?\d+
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
    "vinyl|(double )?(ep|lp)",
    "e[.]p[.]",
]
CATNUM_PAT = {
    "desc": re.compile(rf"(?:^|\n|[Cc]at[^:]+[.:]\ ?){_catalognum}", re.VERBOSE),
    "in_parens": re.compile(rf"[\[\(|]{_catalognum}[|\]\)]", re.VERBOSE),
    "with_header": re.compile(r"(?:Catal[^:]+: *)(\b[^\n]+\b)(?:[\]]*\n)"),
    "start_or_end": re.compile(rf"((^|\n){_catalognum}|{_catalognum}(\n|$))", re.VERBOSE),
}
PATTERNS: Dict[str, Pattern] = {
    "clean_title": re.compile(fr"(?i: ?[\[\(]?\b({'|'.join(rm_strings)})(\b[\]\)]?|$))"),
    "clean_incl": re.compile(
        r"(?i:(\(incl[^)]+\)|\((inc|tracks|.*remix( |es)( [0-9]?)?\)?)))"
    ),
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
    def get_country(loc: str) -> str:
        try:
            name = normalize("NFKD", loc).encode("ascii", "ignore").decode()
            return (
                COUNTRY_OVERRIDES.get(name)
                or getattr(countries.get(name=name, default=object), "alpha_2", None)
                or subdivisions.lookup(name).country_code
            )
        except (ValueError, LookupError):
            return WORLDWIDE

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
    def parse_track_name(name: str, delim: str = "-", rm_index=False) -> Dict[str, str]:
        track = defaultdict(str)
        if rm_index:
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
        strip = (
            lambda x: x.groups()[0].strip()
            if x and len(x.groups()) and x.groups()[0]
            else ""
        )
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
    def clean_name(name: str, remove_extra: bool = False, **kwargs) -> str:
        """Return clean album name / track title.
        If `remove_extra`, remove info from within the parentheses (usually remix info).
        """
        # redundant information about 'remixes from xyz'
        if remove_extra:
            name = PATTERNS["clean_incl"].sub("", name)
        # catalognum, album, albumartist

        def get(key: str) -> str:
            return kwargs.get(key) or ""

        for arg in filter(op.truth, [get("catalognum"), get("label")]):
            name = re.sub(rf"(?i:[^\w\]\)]*{re.escape(arg)}\W*)", " ", name)

        name = name.strip()
        for artist in get("artists") or []:
            artist = re.escape(artist)
            name = re.sub(
                rf"(?i:^{artist}$|^{artist}[ &|:-]+|[ &|:-]+{artist}$)", "", name
            )

        for pat, repl in [
            (r"  +", " "),  # multiple spaces
            (r"\( +|(- )?\(+", "("),  # rubbish that precedes opening parenthesis
            (r" +\)|\)+", ")"),  # rubbish spaces that precede closing parenthesis
            ('"', ""),  # double quote anywhere
            ("//", ""),  # double slashes anywhere
        ]:
            name = re.sub(pat, repl, name)
        return PATTERNS["clean_title"].sub("", name).strip(" -|/'")

    @staticmethod
    def get_genre(
        keywords: Iterable[str],
        genre_config: JSONDict = None,
        always_include: List[str] = [],
        mode: str = "progressive",
    ) -> Iterable[str]:
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
        if genre_config:
            always_include = genre_config["always_include"]
            mode = genre_config["mode"]
        valid_mb_genre = partial(op.contains, GENRES)

        def is_included(kw: str) -> bool:
            return any(map(lambda x: re.search(x, kw), always_include))

        def valid_for_mode(kw: str) -> bool:
            if mode == "classical":
                return kw in GENRES

            words = map(str.strip, kw.split(" "))
            if mode == "progressive":
                return kw in GENRES or all(map(valid_mb_genre, words))

            return valid_mb_genre(kw) or valid_mb_genre(list(words)[-1])

        # expand badly delimited keywords
        split_kw = partial(re.split, r"[.] | #| - ")
        for kw in it.chain(*map(split_kw, map(str.lower, keywords))):
            # remove full stops and hashes and ensure the expected form of 'and'
            kw = (
                re.sub("[.#]", "", str(kw))
                .replace("&", "and")
                .replace("dnb", "drum and bass")
                .replace("drum n bass", "drum and bass")
            )
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
    def _get_media_reference(media_list: List[JSONDict]) -> JSONDict:
        """Get release media from the metadata, excluding bundles.
        Return a dictionary with a human mapping (Digital|CD|Vinyl|Cassette) -> media.
        """

        def is_bundle(fmt: JSONDict) -> bool:
            return "bundle" in (fmt.get("name") or "").casefold()

        media: Dict[str, JSONDict] = {}
        for _format in it.filterfalse(is_bundle, media_list):
            medium = _format.get("musicReleaseFormat")
            if not medium:
                continue
            media[MEDIA_MAP.get(medium) or DIGI_MEDIA] = _format
        return media


class BandcampMeta:
    media: JSONDict
    media_name: str

    _config: JSONDict
    _meta: JSONDict

    def __init__(self, html: str, config: JSONDict) -> None:
        self.media = self._meta = {}
        self._config = config
        match = re.search(PATTERNS["meta"], html)
        if match:
            self._meta = json.loads(match.group())

        media = self._meta.get("albumRelease") or self._meta.get("inAlbum", {}).get(
            "albumRelease"
        )
        media_index = Helpers._get_media_reference(media)
        for preference in (self._config.get("preferred_media") or "").split(","):
            if preference in media_index:
                self.media = media_index[preference]
                self.media_name = preference
                break
        else:
            self.media = media_index[DIGI_MEDIA]
            self.media_name = DIGI_MEDIA

    @cached_property
    def description(self):
        return self._meta.get("description") or ""

    @cached_property
    def media_description(self) -> str:
        return self.media.get("description") or ""

    @cached_property
    def disctitle(self) -> str:
        """Return medium's disc title if found."""
        return "" if self.media_name == DIGI_MEDIA else self.media.get("name", "")

    @cached_property
    def mediums(self) -> int:
        return (
            Helpers.get_vinyl_count(self.disctitle) if self.media_name == "Vinyl" else 1
        )

    @cached_property
    def credits(self) -> str:
        return self._meta.get("creditText") or ""

    @cached_property
    def all_media_descriptions(self) -> str:
        get_desc = op.methodcaller("get", "description", "")
        bad = "Includes high-quality"
        return self._config["comments_separator"].join(
            filter(
                lambda x: x and not x.startswith(bad),
                map(get_desc, self._meta.get("albumRelease", {})),
            )
        )

    @cached_property
    def album_name(self) -> str:
        match = re.search(r"Title: ?([^\n]+)", self.all_media_descriptions)
        if match:
            return match.expand(r"\1").strip()
        return self._meta["name"]

    @cached_property
    def label(self) -> str:
        match = re.search(r"Label:([^/,\n]+)", self.all_media_descriptions)
        if match:
            return match.groups()[0].strip()
        try:
            return self._meta["albumRelease"][0]["recordLabel"]["name"]
        except (KeyError, IndexError):
            return self._meta["publisher"]["name"]

    # @cached_property
    # def band_id(self) -> str:
    #     publish

    @cached_property
    def album_id(self) -> str:
        return self._meta["@id"]

    @cached_property
    def artist_id(self) -> str:
        try:
            return self._meta["byArtist"]["@id"]
        except KeyError:
            return self._meta["publisher"]["@id"]

    @cached_property
    def albumartist(self) -> str:
        """Return the official release albumartist.
        It is correct in half of the cases. In others, we usually find the label name.
        """
        match = re.search(r"Artist: ?([^\n]+)", self.all_media_descriptions)
        if match:
            return str(match.groups()[0].strip())

        return self._meta["byArtist"]["name"]

    @cached_property
    def image(self) -> str:
        # TODO: Need to test
        image = self._meta.get("image", "")
        return image[0] if isinstance(image, list) else image

    @cached_property
    def release_date(self) -> Optional[date]:
        """Parse the datestring that takes the format like below and return date object.
        {"datePublished": "17 Jul 2020 00:00:00 GMT"}

        If the field is not found, return None.
        """
        rel = self._meta.get("datePublished")
        if rel:
            return datetime.strptime(re.sub(r" [0-9]{2}:.+", "", rel), "%d %b %Y").date()
        return rel

    @cached_property
    def country(self) -> str:
        try:
            loc = self._meta["publisher"]["foundingLocation"]["name"]
            return Helpers.get_country(loc.rpartition(", ")[-1])
        except KeyError:
            return WORLDWIDE

    @cached_property
    def raw_tracks(self) -> List[JSONDict]:
        try:
            return self._meta["track"].get("itemListElement", [])
        except KeyError:
            return [{"item": self._meta}]

    @cached_property
    def style(self) -> Optional[str]:
        """Extract bandcamp genre tag from the metadata."""
        # expecting the following form: https://bandcamp.com/tag/folk
        style = None
        tag_url = self._meta.get("publisher", {}).get("genre") or ""
        if tag_url:
            style = tag_url.split("/")[-1]
            if self._config["genre"]["capitalize"]:
                style = style.capitalize()
        return style

    @cached_property
    def genre(self) -> Optional[str]:
        kws: Iterable[str] = map(str.lower, self._meta["keywords"])
        if self.style:
            exclude_style = partial(op.ne, self.style.lower())
            kws = filter(exclude_style, kws)

        genre_cfg = self._config.get("genre", {})
        genres = Helpers.get_genre(kws, genre_cfg)
        if genre_cfg["capitalize"]:
            genres = map(str.capitalize, genres)
        if genre_cfg["maximum"]:
            genres = it.islice(genres, genre_cfg["maximum"])

        return ", ".join(genres) or None


class Metaguru(Helpers):
    meta: BandcampMeta
    config: JSONDict

    _singleton = False
    excluded_fields: Set[str] = set()

    def __init__(self, html, config) -> None:
        self.config = config or {}
        self.meta = BandcampMeta(html, config)
        self.excluded_fields = set(self.config.get("exclude_extra_fields") or [])

    @cached_property
    def comments(self) -> str:
        """Return release, media descriptions and credits separated by
        the configured separator string.
        """
        parts = [self.meta.description]
        media_desc = self.meta.media_description
        if media_desc and not media_desc.startswith("Includes high-quality"):
            parts.append(media_desc)

        parts.append(self.meta.credits)
        sep = self.config["comments_separator"]
        return sep.join(filter(op.truth, parts)).replace("\r", "")

    @cached_property
    def albumstatus(self) -> str:
        reldate = self.meta.release_date
        return "Official" if reldate and reldate <= date.today() else "Promotional"

    @cached_property
    def catalognum(self) -> str:
        return self.parse_catalognum(
            self.meta.album_name,
            self.meta.disctitle,
            self.meta.all_media_descriptions,
            self.meta.label,
            artists=self.all_artists,
        )

    def track_delimiter(self, names: List[str]) -> str:
        """Return the track parts delimiter that is in effect in the current release.
        In some (weird) situations track parts are delimited by a pipe pipe character
        instead of the usual dash. This checks every track looking for our delimiters
        and returns the one that is found _in each of the track names_.
        """
        for delim in "-|":
            delim_pat: str = fr"[{delim}] | [{delim}]"
            delims = it.repeat(delim_pat)
            match_count = sum(map(bool, map(re.search, delims, names)))
            if len(names) - match_count <= 1:
                return delim
        return ""

    @cached_property
    def bandcamp_titles(self) -> Iterable[str]:
        return map(
            lambda i: (i.get("byArtist") or i).get("name") or "",
            map(lambda x: x.get("item") or {}, self.meta.raw_tracks),
        )

    @cached_property
    def tracks(self) -> List[JSONDict]:
        """Parse relevant details from the tracks' JSON."""
        raw_tracks = self.meta.raw_tracks
        names = list(self.bandcamp_titles)

        # find the track delimiter
        delim = self.track_delimiter(names)
        # remove leading numerical index if every track has it
        rm_index = False
        names = map(lambda x: self.clean_name(x, catalognum=self.catalognum), names)
        # names = list(map(lambda x: x.replace(" - Reworked", ""), names))
        if all(map(lambda x: x[0].isdigit(), names)):
            rm_index = True

        albumartist = self.meta.albumartist
        # pat = re.compile(r"[^\w\]\)]*\[(?!.*(?i:mix|edit))[^\]]+\]")
        # name = self.clear_digi_only(pat.sub("", item["name"]))
        # args = [name, catalognum]
        tracks = []
        for item, position in map(lambda x: (x["item"], x.get("position")), raw_tracks):
            name = self.clean_name(item["name"], catalognum=self.catalognum)
            name = self.clear_digi_only(name.replace(" - Reworked", ""))
            digi_only = name != item["name"]
            track: JSONDict = defaultdict(str)
            track.update(
                digi_only=digi_only,
                index=position or 1,
                medium_index=position or 1,
                track_id=item.get("@id"),
                length=self.get_duration(item),
                **self.parse_track_name(name, delim, rm_index=rm_index),
            )
            track["artist"] = self.get_track_artist(track["artist"], item, albumartist)
            lyrics = item.get("recordingOf", {}).get("lyrics", {}).get("text")
            if lyrics:
                track["lyrics"] = lyrics.replace("\r", "")
            tracks.append(track)

        return tracks

    @cached_property
    def track_artists(self) -> Set[str]:
        artists: Iterable[str] = map(
            lambda x: PATTERNS["remix_or_ft"].sub("", x.get("main_artist") or ""),
            self.tracks,
        )
        i: Iterable[str] = []
        unique_artists = set(reduce(lambda x, y: it.chain(x, y.split(", ")), artists, i))
        unique_artists.discard("")
        return unique_artists

    @cached_property
    def all_artists(self) -> Set[str]:
        def only_artist(name: str) -> str:
            return self.parse_track_name(name).get("artist") or ""

        artists = set(map(only_artist, self.bandcamp_titles)) - {""}
        return artists or {self.meta.albumartist}

    @cached_property
    def is_single_album(self) -> bool:
        return len(set(t.get("main_title") for t in self.tracks)) == 1

    @cached_property
    def is_lp(self) -> bool:
        maybe_here = [self.meta.album_name, self.meta.disctitle, self.comments]
        return any(map(lambda x: " LP" in x, maybe_here))

    @cached_property
    def is_ep(self) -> bool:
        maybe_here = [self.meta.album_name, self.meta.disctitle, self.comments]
        return any(map(lambda x: " EP" in x, maybe_here))

    @cached_property
    def is_va(self) -> bool:
        unique = self.all_artists
        track_count = len(self.tracks)
        print(unique)
        # unique = set(map(lambda x: re.sub(r" ?[,x].*", "", x).lower(), track_artists))
        # return VA.casefold() in self.meta.album_name.casefold() or (
        #     track_count >= 4
        #     and (
        #         len(unique) == track_count
        #         or (
        #             len(unique) > 1
        #             and not {*self.meta.albumartist.split(", ")}.issubset(unique)
        #         )
        #     )
        # )
        # print(vars(self))
        # print(vars(self.meta))
        return (
            bool(re.search(r"VA[0-9]+", self.catalognum))
            or bool(re.search(r"(?i:various|va)", self.meta.album_name))
            or bool(
                re.search(
                    r"(?i:various|va|v[.]a[.]|compilation)(\s|\d|$)",
                    self.meta.albumartist,
                )
            )
            or (
                len(unique) > 1
                and (
                    bool(re.search(r"(?i:vol[^0-9]*[0-9]+)", self.meta.album_name))
                    or bool(re.search(r"(?i:vol[^0-9]*[0-9]+)", self.meta.disctitle))
                )
            )
            # or len(unique) > track_count
            or (track_count > 4 and len(unique) > 4)
            # or (
            #     len(unique) > 3
            #     # this circumvents the case when a release lists all track artists
            #     # as the albumartist
            #     and not set(self.meta.albumartist.split(", ")) == unique
            #     and track_count > 4
            # )
        )

    @cached_property
    def albumartist(self) -> str:
        """Take into account the release contents and return the actual albumartist.
        * 'Various Artists' for a compilation release
        * If every track has the same author, treat it as the albumartist
        """
        albumartist = self.meta.albumartist
        if self.meta.label == albumartist:
            album = self.meta.album_name
            albumartist = self.parse_track_name(album, "-").get("artist") or albumartist

        if self.is_va:
            return VA

        tartists = self.track_artists
        if self.is_ep:
            joined = ", ".join(sorted(tartists))
            if joined:
                albumartist = joined
                print(joined)
        if len(tartists) == 1:
            first_tartist = tartists.copy().pop()
            if first_tartist != self.meta.label:
                return first_tartist
        return albumartist

    @cached_property
    def albumtype(self) -> str:
        if self._singleton:
            return "single"
        if self.is_ep:
            return "ep"
        return "album"

    @cached_property
    def albumtypes(self) -> str:
        albumtypes = [self.albumtype]
        if self.is_single_album:
            albumtypes.append("single")
        elif self.is_va:
            albumtypes.append("compilation")
        if self.is_lp:
            albumtypes.append("lp")
        if "remix" in self.meta.album_name.casefold():
            albumtypes.append("remix")
        return "; ".join(sorted(set(albumtypes)))

    @cached_property
    def parsed_album_name(self) -> str:
        match = re.search(r"[:-] ?([\w ]+) [EL]P", self.meta.all_media_descriptions)
        if match:
            return match.expand(r"\1")
        return self.catalognum

    @cached_property
    def clean_album_name(self) -> str:
        kwargs = {}
        if self.catalognum:
            kwargs["catalognum"] = self.catalognum
        if not self._singleton:
            artists = OrderedSet(
                [self.meta.albumartist, self.albumartist, *self.albumartist.split(", ")]
            )

            # leave label name in place for compilations
            if self.is_va:
                # it could have been added as an albumartist already
                artists.discard(self.meta.label)
            else:
                kwargs.update(label=self.meta.label)
            kwargs.update(artists=artists)

        clean = self.clean_name(self.meta.album_name, remove_extra=True, **kwargs)
        if not clean:
            clean = self.parsed_album_name
        if re.match(r"(?i:^vol[.]?[0-9])", clean) and self.catalognum:
            clean = f"{self.catalognum} {clean}"
        return re.sub(r"(?i:\W+vol(?:ume)?\W*0*([0-9]+))", ", Volume \\1", clean)

    @cached_property
    def _common(self) -> JSONDict:
        return dict(media=self.meta.media_name, artist_id=self.meta.artist_id)

    def get_fields(self, fields: Iterable[str], src: object = None) -> JSONDict:
        """Return a mapping between unexcluded fields and their values."""
        fields = set(fields) - self.excluded_fields
        if len(fields) == 1:
            field = fields.pop()
            return {field: getattr(self, field)}
        return dict(
            zip(
                fields,
                map(lambda x: x if x else "", iter(op.attrgetter(*fields)(src or self))),
            )
        )

    @cached_property
    def _common_album(self) -> JSONDict:
        common_data: JSONDict = dict(
            album=self.clean_album_name,
            data_source=DATA_SOURCE,
            data_url=self.meta.album_id,
        )
        fields = ["catalognum", "albumtype", "albumtypes", "comments", "albumstatus"]
        common_data.update(self.get_fields(fields))
        common_data.update(
            self.get_fields(["label", "style", "genre", "country"], self.meta)
        )
        reldate = self.meta.release_date
        if reldate:
            common_data.update(self.get_fields(["year", "month", "day"], reldate))

        return common_data

    def _trackinfo(self, track: JSONDict, **kwargs: Any) -> TrackInfo:
        track.pop("digi_only", None)
        track.pop("main_title", None)
        track_info = TrackInfo(
            **self._common,
            **track,
            disctitle=self.meta.disctitle or None,
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
            # track.update(**self._common_album, albumartist=self.albumartist)
            track.update(**self._common_album)
        track.pop("albumstatus")

        track.update(self.tracks[0].copy())
        track.update(self.parse_track_name(self.meta.album_name, "-"))
        if not track.get("artist"):
            track["artist"] = self.albumartist
        track["title"] = self.clean_name(track["title"])
        track["index"] = 0
        track.update(self._trackinfo(track))
        track.pop("disctitle", None)
        track.pop("medium", None)
        track.pop("medium_index", None)
        return TrackInfo(**track)

        # if NEW_BEETS:
        # artist, title = track["artist"], track["title"]
        # track["album"] = "{} - {}".format(artist, title)
        # return self._trackinfo(track, medium_total=1)
        # return self._trackinfo(track)

    @cached_property
    def album(self) -> AlbumInfo:
        """Return album for the appropriate release format."""
        tracks: Iterable[JSONDict] = self.tracks
        include_digi = self.config.get("include_digital_only_tracks")
        if not include_digi and self.meta.media_name != DIGI_MEDIA:
            tracks = it.filterfalse(op.itemgetter("digi_only"), tracks)

        tracks = list(map(op.methodcaller("copy"), tracks))

        get_trackinfo = partial(self._trackinfo, medium_total=len(tracks))
        return AlbumInfo(
            **self._common,
            **self._common_album,
            artist=self.albumartist,
            album_id=self.meta.album_id,
            mediums=self.meta.mediums,
            va=self.is_va,
            tracks=list(map(get_trackinfo, tracks)),
        )
