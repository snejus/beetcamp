"""Module for parsing bandcamp metadata."""
import itertools as it
import json
import operator as op
import re
from datetime import date, datetime
from functools import partial
from math import floor
from typing import Any, Dict, Iterable, List, Optional, Pattern, Set, Tuple
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

_catalognum = r"(\b[A-Za-z]([^-.\s\d]|[.-][^0-9])+(([-.]?|[A-Z]\s)\d+|\s\d{2,})[A-Z]?(?:[.-]?\d|CD)?\b)"  # noqa
_catalognum_header = r"(?:Catalog(?:ue)?(?: (?:Number|N[or]))?|Cat N[or])\.?:"
PATTERNS: Dict[str, Pattern] = {
    "meta": re.compile(r".*dateModified.*", flags=re.MULTILINE),
    "desc_catalognum": re.compile(rf"(?:{_catalognum_header} ?)([A-Z]+[. -]?[0-9]+)"),
    "quick_catalognum": re.compile(rf"[\[(]{_catalognum}[])]"),
    "catalognum": re.compile(rf"(^{_catalognum}|{_catalognum}$)"),
    "catalognum_excl": re.compile(
        r"(?i:vol(ume)?|artists|\bva\d+|vinyl|triple|ep 12)|202[01]|(^|\s)C\d\d|\d+/\d+"
    ),
    "digital": re.compile(
        r"""
        # either
        (^                  # start of the title
          DIGI(TAL)?[.]?[ ] # note all capitals (otherwise we may match actual titles)
          (\d+[.][ ]?)?     # which may be followed by an index
        ) | (?i:            # or, with ignorecase in place, ...
          [ *\[\(-]+                    # there is some special delimiter
          (bandcamp|digi(tal)?)         # followed by either of these two
          (
            [)\]]$                      # either closed immediately
            |.*(only|bonus|exclusive).* # or ending with some big VIP word
          )
        )
        """,
        re.VERBOSE,
    ),
    "clean_incl": re.compile(r"(?i:(\(?incl[^)]+\)?|\([^)]+remix[^)]+\)))"),
    "remix_or_ft": re.compile(r"\s(?i:(\[|\().*(mix|edit)|f(ea)?t\.).*"),
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
    def clean_digital_only_track(name: str) -> Tuple[str, bool]:
        """Return cleaned title and whether this track is digital-only."""
        clean_name = PATTERNS["digital"].sub("", name)
        if clean_name != name:
            return clean_name, True
        return clean_name, False

    @staticmethod
    def parse_track_name(name: str, catalognum: str = "") -> Dict[str, Optional[str]]:
        track: Dict[str, Optional[str]] = {
            a: None for a in ["track_alt", "artist", "title", "main_title"]
        }

        # remove catalognum if given
        if catalognum:
            name = name.replace(catalognum, "").strip(", ")

        # remove leading numerical index if found
        name = re.sub(r"^[01]?[0-9][. ]\s?(?=[A-Z])", "", name).strip(", ")

        # match track alt and remove it from the name
        match = PATTERNS["track_alt"].match(name)
        if match:
            track_alt = match.expand(r"\1")
            track["track_alt"] = track_alt
            name = name.replace(track_alt, "")

        # do not strip a period from the end since it could end with an abbrev
        name = name.lstrip(".")
        # in most cases that's the delimiter between the artist and the title
        parts = re.split(r"\s?-\s|\s-\s?", name.strip(",- "))

        # title is always given
        track["title"] = parts.pop(-1)
        track["main_title"] = PATTERNS["remix_or_ft"].sub("", track["title"])

        # whatever is left must be the artist
        if len(parts):
            track["artist"] = ", ".join(parts).strip(",. ")
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
    def parse_catalognum(album: str, disctitle: str, description: str, label: str) -> str:
        """Try finding the catalogue number in the following sequence:
        1. Check description for a formal catalogue number
        2. Check album name for [CATALOGNUM] or (CATALOGNUM)
        3. Check whether label name is followed by numbers
        4. Check album name and disctitle using more flexible rules.
        """
        label_excl: Tuple[Optional[Pattern], Optional[str]] = (None, None)
        if label:
            escaped = re.escape(label)
            label_excl = (re.compile(rf"({escaped}\s?[0-9]+)"), album)

        for pattern, source in [
            (PATTERNS["desc_catalognum"], description),
            (PATTERNS["quick_catalognum"], album),
            label_excl,
            (PATTERNS["catalognum"], album),
            (PATTERNS["catalognum"], disctitle),
        ]:
            if not pattern:
                continue

            match = pattern.search(PATTERNS["catalognum_excl"].sub("", source))
            if match:
                return match.groups()[0]
        return ""

    @staticmethod
    def get_duration(source: JSONDict) -> int:
        prop = [
            x.get("value") or 0
            for x in source.get("additionalProperty", [])
            if x.get("name") == "duration_secs"
        ]
        if len(prop) == 1:
            return floor(prop[0])
        return 0

    @staticmethod
    def clean_name(name: str, *args: str, remove_extra: bool = False) -> str:
        """Return the clean album name.
        If it ends up cleaning the name entirely, then return the first `args` member
        if given (catalognum or label). If not given, return the original name.

        If `remove_extra`, remove info from within the parentheses (usually remix info).
        """
        # catalognum, album, albumartist
        for arg in args:
            arg = re.escape(arg)
            name = re.sub(rf"{arg}((?=[^'])|$)", "", name)

        # redundant spaces, duoble quotes, parentheses
        for pat, repl in [
            (r"\s\s+", " "),
            (r"\(\s+|(- )?\(+", "("),
            # Remove duplicate closing parens if they follow a space
            # or enclose mix/edit info and are at the end
            (r" \)+|(?<=(?i:.mix|edit))\)+$", ")"),
            (r'"', ""),
        ]:
            name = re.sub(pat, repl, name)

        # redundant information about 'remixes from xyz'
        if remove_extra:
            name = PATTERNS["clean_incl"].sub("", name)

        # always removed
        exclude = [
            "limited edition",
            "various artists",
            "various artist",
            "free download",
            "free dl",
            "free)",
            "vinyl",
            "e.p.",
            "ep",
            "lp",
            "va",
        ]
        # handle special chars
        excl = "|".join(map(re.escape, exclude))

        rubbish = r"(?i:\b({})(\b|$))".format(excl)
        empty_parens = r"\(\)|\[\]"
        default = next(iter([*args, name]))

        def clean(patstr: str, text: str) -> str:
            return re.sub(patstr, "", text)

        return clean(empty_parens, clean(rubbish, name)).strip("/-|([ ") or default

    @staticmethod
    def get_genre(keywords: Iterable[str], mode: str) -> Iterable[str]:
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

        def valid_for_mode(kw: str) -> bool:
            if mode == "classical":
                return kw in GENRES

            words = map(str.strip, kw.split(" "))
            if mode == "progressive":
                return kw in GENRES or all(map(valid_mb_genre, words))

            return valid_mb_genre(kw) or valid_mb_genre(list(words)[-1])

        for kw in keywords:
            if kw not in genres and valid_for_mode(kw):
                genres.append(kw)

        def valid_genre(genre: str) -> bool:
            def within_another(another: str) -> bool:
                return genre != another and genre in another

            return not any(filter(within_another, genres))  # type: ignore

        return filter(valid_genre, genres)

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
        if self.media_name != DIGI_MEDIA:
            parts.append(self._media.get("description"))

        parts.append(self.meta.get("creditText"))
        sep = self.config["comments_separator"]
        return sep.join(filter(op.truth, parts)).replace("\r", "")

    @cached_property
    def album_name(self) -> str:
        match = re.search(r"Title:([^\n]+)", self.comments)
        if match:
            return match.groups()[0].strip()
        return self.meta["name"]

    @cached_property
    def label(self) -> str:
        match = re.search(r"Label:([^/,\n]+)", self.comments)
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
        match = re.search(r"Artist:([^\n]+)", self.comments)
        if match:
            return str(match.groups()[0].strip())

        albumartist = self.meta["byArtist"]["name"].replace("various", VA)
        album = self.album_name
        if self.label == albumartist:
            albumartist = (
                self.parse_track_name(album, self.catalognum).get("artist") or albumartist
            )

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
        date = self.meta.get("datePublished")
        if date:
            return datetime.strptime(re.sub(r" [0-9]{2}:.+", "", date), "%d %b %Y").date()
        return date

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
            self.album_name, self.disctitle, self.comments, self.label
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
        if self._singleton:
            raw_tracks = [{"item": self.meta}]
        else:
            raw_tracks = self.meta["track"].get("itemListElement", [])

        albumartist = self.bandcamp_albumartist
        catalognum = self.catalognum
        tracks = []
        for raw_track in raw_tracks:
            raw_item = raw_track["item"]
            index = raw_track.get("position") or 1
            name, digital_only = self.clean_digital_only_track(raw_item["name"])
            name = self.clean_name(name, *filter(op.truth, [self.catalognum, self.label]))
            track = dict(
                digital_only=digital_only,
                index=index,
                medium_index=index,
                track_id=raw_item.get("@id"),
                length=self.get_duration(raw_item) or None,
                **self.parse_track_name(name, catalognum),
            )
            track["artist"] = self.get_track_artist(
                track["artist"], raw_item, albumartist  # type: ignore
            )
            lyrics = raw_item.get("recordingOf", {}).get("lyrics", {}).get("text")
            if lyrics:
                track["lyrics"] = lyrics.replace("\r", "")
            else:
                track["lyrics"] = None

            tracks.append(track)

        return tracks

    @cached_property
    def track_artists(self) -> Set[str]:
        artists = {(t.get("artist") or "") for t in self.tracks}
        artists.discard("")
        return artists

    @cached_property
    def is_single(self) -> bool:
        return self._singleton or len(set(t.get("main_title") for t in self.tracks)) == 1

    @cached_property
    def is_lp(self) -> bool:
        return "LP" in self.album_name or "LP" in self.disctitle

    @cached_property
    def is_ep(self) -> bool:
        return "EP" in self.album_name or "EP" in self.disctitle

    @cached_property
    def is_va(self) -> bool:
        return (
            VA.casefold() in self.album_name.casefold()
            or len(self.track_artists) == len(self.tracks)
            or (
                len(self.track_artists) > 1
                and not {*self.bandcamp_albumartist.split(", ")}.issubset(
                    self.track_artists
                )
                and len(self.tracks) >= 4
            )
        )

    @cached_property
    def albumartist(self) -> str:
        """Handle various artists and albums that have a single artist."""
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
        genres = self.get_genre(kws, genre_cfg["mode"])
        if genre_cfg["capitalize"]:
            genres = map(str.capitalize, genres)
        if genre_cfg["maximum"]:
            genres = it.islice(genres, genre_cfg["maximum"])

        return ", ".join(genres) or None

    @cached_property
    def clean_album_name(self) -> str:
        args = [self.catalognum] if self.catalognum else []
        if not self.albumtype == "compilation":
            args.append(self.label)
        if not self._singleton:
            args.append(self.albumartist)
        return self.clean_name(self.album_name, *args, remove_extra=True)

    @property
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

    @property
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
        track.pop("digital_only")
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

    @property
    def singleton(self) -> TrackInfo:
        self._singleton = True
        kwargs: JSONDict = {}
        if NEW_BEETS:
            kwargs.update(**self._common_album, albumartist=self.bandcamp_albumartist)

        track = self.tracks[0].copy()
        track.update(self.parse_track_name(self.album_name))
        if not track.get("artist"):
            track["artist"] = self.bandcamp_albumartist
        if NEW_BEETS and "-" not in kwargs.get("album", ""):
            kwargs["album"] = "{} - {}".format(track["artist"], track["title"])

        return self._trackinfo(track, medium_total=1, **kwargs)

    @property
    def album(self) -> AlbumInfo:
        """Return album for the appropriate release format."""
        tracks: Iterable[JSONDict] = self.tracks
        include_digi = self.config.get("include_digital_only_tracks")
        if not include_digi and self.media_name != DIGI_MEDIA:
            tracks = it.filterfalse(op.itemgetter("digital_only"), tracks)

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
