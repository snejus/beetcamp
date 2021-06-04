"""Module for parsing bandcamp metadata."""
import json
import re
from datetime import date, datetime
from functools import reduce
from math import floor
from operator import truth
from string import ascii_lowercase, digits
from typing import Any, Dict, List, Optional, Pattern, Set, Tuple
from unicodedata import normalize

from beets.autotag.hooks import AlbumInfo, TrackInfo
from cached_property import cached_property
from pkg_resources import get_distribution, parse_version
from pycountry import countries, subdivisions

NEW_BEETS = get_distribution("beets").parsed_version >= parse_version("1.5.0")

JSONDict = Dict[str, Any]

OFFICIAL = "Official"
PROMO = "Promotional"
COUNTRY_OVERRIDES = {
    "Russia": "RU",  # pycountry: Russian Federation
    "The Netherlands": "NL",  # pycountry: Netherlands
    "UK": "GB",  # pycountry: Great Britain
}
DATE_FORMAT = "%d %B %Y"
DATA_SOURCE = "bandcamp"
WORLDWIDE = "XW"
DEFAULT_MEDIA = "Digital Media"
MEDIA_MAP = {
    "VinylFormat": "Vinyl",
    "CDFormat": "CD",
    "CassetteFormat": "Cassette",
    "DigitalFormat": DEFAULT_MEDIA,
}
VALID_URL_CHARS = {*ascii_lowercase, *digits}

_catalognum = r"([A-Z][^-.\s\d]+[-.\s]?\d{2,4}(?:[.-]?\d|CD)?)"
_exclusive = r"[\[( -]*(bandcamp )?(digi(tal)? )?(bonus|only|exclusive)[\])]?"
_catalognum_header = r"(?:Catalogue(?: (?:Number|N[or]))?|Cat N[or])\.?:"
PATTERNS: Dict[str, Pattern] = {
    "meta": re.compile(r".*datePublished.*", flags=re.MULTILINE),
    "desc_catalognum": re.compile(rf"{_catalognum_header} ?({_catalognum})"),
    "quick_catalognum": re.compile(rf"\[{_catalognum}\]"),
    "catalognum": re.compile(rf"^{_catalognum}|{_catalognum}$"),
    "catalognum_excl": re.compile(r"(?i:vol(ume)?|artists)|202[01]|(^|\s)C\d\d|\d+/\d+"),
    "digital": re.compile(rf"^DIGI (\d+\.\s?)?|(?i:{_exclusive})"),
    "lyrics": re.compile(r'"lyrics":({[^}]*})'),
    "release_date": re.compile(r"release[ds] ([\d]{2} [A-Z][a-z]+ [\d]{4})"),
    "track_name": re.compile(
        r"""
((?P<track_alt>(^[ABCDEFGH]{1,3}[0-6]|^\d)\d?)\s?[.-]+(?=[^\d]))?
(\s?(?P<artist>[^-]*)(\s-\s))?
(?P<title>(\b([^\s]-|-[^\s]|[^-])+$))""",
        re.VERBOSE,
    ),
    "vinyl_name": re.compile(
        r'(?P<count>[1-5]|[Ss]ingle|[Dd]ouble|[Tt]riple)(LP)? ?x? ?((7|10|12)" )?Vinyl'
    ),
}


def urlify(pretty_string: str) -> str:
    """Make a string bandcamp-url-compatible."""
    return reduce(
        lambda p, n: p + n
        if n in VALID_URL_CHARS
        else p + "-"
        if not p.endswith("-")
        else p,
        pretty_string.lower().replace("'", ""),
        "",
    ).strip("-")


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
        clean_name = re.sub(PATTERNS["digital"], "", name)
        if clean_name != name:
            return clean_name, True
        return clean_name, False

    @staticmethod
    def parse_track_name(name: str) -> Dict[str, str]:
        name = re.sub(r" \(free[^)]*\)", "", name, flags=re.IGNORECASE)
        track = {"track_alt": None, "artist": None, "title": name}
        match = re.search(PATTERNS["track_name"], name)
        if match:
            track = match.groupdict()
        track["main_title"] = re.sub(r"\s?([[(]|f(ea)?t\.).*", "", track["title"])
        return track

    @staticmethod
    def parse_catalognum(album: str, disctitle: str, description: str) -> str:
        for pattern, source in [
            (PATTERNS["desc_catalognum"], description),
            (PATTERNS["quick_catalognum"], album),
            (PATTERNS["catalognum"], disctitle.upper()),
            (PATTERNS["catalognum"], album),
        ]:
            match = re.search(pattern, re.sub(PATTERNS["catalognum_excl"], "", source))
            if match:
                try:
                    return next(group for group in match.groups() if group)
                except StopIteration:
                    continue
        return ""

    @staticmethod
    def parse_release_date(string: str) -> str:
        match = re.search(PATTERNS["release_date"], string)
        return match.groups()[0] if match else ""

    @staticmethod
    def get_duration(source: JSONDict) -> int:
        for item in source.get("additionalProperty", []):
            if item.get("name") == "duration_secs":
                return floor(item.get("value", 0))
        return 0

    @staticmethod
    def clean_up_album_name(name: str, *args: str) -> str:
        """Return clean album name.
        If it ends up cleaning the name entirely, then return the first `args` member
        if any given (catalognum or label). If not given, return the original name.
        """
        # always removed
        exclude = ["E.P.", "various artists", "limited edition", "free download", "vinyl"]
        # add provided arguments
        exclude.extend(args)
        # handle special chars
        excl = "|".join(map(re.escape, exclude))

        _with_brackparens = r"[\[(]({})[])]"
        _opt_brackparens = r"[\[(]?({})[])]?"
        _lead_or_trail_dash = r"(\s-\s)({0})|({0})(\s?-\s)"
        _followed_by_pipe_or_slash = r"({})\s[|/]+\s?"
        _trails = r" ({})$"
        pattern = "|".join(
            [
                " " + _opt_brackparens.format("[EL]P"),
                _followed_by_pipe_or_slash.format(excl),
                _with_brackparens.format(excl),
                _lead_or_trail_dash.format(excl),
                _trails.format(excl),
            ]
        )
        pat = re.compile(pattern, flags=re.IGNORECASE)
        return re.sub(pat, "", name).strip() or (args[0] if args else name)

    @staticmethod
    def _get_media(meta: JSONDict) -> JSONDict:
        """Get release media from the metadata, excluding bundles.
        Return a dictionary with a human mapping (Digital|CD|Vinyl|Cassette) -> media.
        """
        media: JSONDict = {}
        for _format in meta["albumRelease"]:
            try:
                assert "bundle" not in _format["name"].lower()
                medium = _format["musicReleaseFormat"]
            except (KeyError, AssertionError):
                continue
            human_name = MEDIA_MAP[medium]
            media[human_name] = _format
        return media


class Metaguru(Helpers):
    html: str
    preferred_media: str
    meta: JSONDict

    _media: Dict[str, str]
    _all_media = {DEFAULT_MEDIA}  # type: Set[str]
    _singleton = False  # type: bool
    _release_datestr = ""

    def __init__(self, html: str, media: str = DEFAULT_MEDIA) -> None:
        self._media = {}
        self.html = html
        self.preferred_media = media

        self.meta = {}
        match = re.search(PATTERNS["meta"], html)
        if match:
            self.meta = json.loads(match.group())

        match = re.search(PATTERNS["release_date"], html)
        if match:
            self._release_datestr = match.groups()[0]

    @cached_property
    def description(self) -> str:
        """Return album and media description if unless they start with a generic message.
        If credits exist, append them too.
        """
        exclude = r"Includes high-quality dow.*"
        _credits = self.meta.get("creditText", "")
        contents = [
            self.meta.get("description", ""),
            re.sub(exclude, "", self._media.get("description", "")),
            "Credits: " + _credits if _credits else "",
        ]
        s = "\n - "
        return reduce(lambda a, b: a + s + b if b else a, contents, "").replace("\r", "")

    @cached_property
    def album_name(self) -> str:
        match = re.search(r"Title:([^\n]+)", self.description)
        if match:
            return match.groups()[0].strip()
        return self.meta["name"]

    @cached_property
    def label(self) -> str:
        match = re.search(r"Label:([^/,\n]+)", self.description)
        if match:
            return match.groups()[0].strip()
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
        match = re.search(r"Artist:([^\n]+)", self.description)
        if match:
            return str(match.groups()[0].strip())
        return self.meta["byArtist"]["name"]

    @property
    def image(self) -> str:
        # TODO: Need to test
        image = self.meta.get("image", "")
        return image[0] if isinstance(image, list) else image

    @property
    def lyrics(self) -> Optional[str]:
        # TODO: Need to test
        matches = re.findall(PATTERNS["lyrics"], self.html)
        if not matches:
            return None
        return "\n".join(json.loads(m).get("text") for m in matches)

    @cached_property
    def release_date(self) -> date:
        return datetime.strptime(self._release_datestr, DATE_FORMAT).date()

    @cached_property
    def media(self) -> str:
        """Return the human-readable version of the media format."""
        return MEDIA_MAP.get(self._media.get("musicReleaseFormat", ""), DEFAULT_MEDIA)

    @cached_property
    def disctitle(self) -> str:
        """Return medium's disc title if found."""
        return "" if self.media == DEFAULT_MEDIA else self._media.get("name", "")

    @property
    def mediums(self) -> int:
        return self.get_vinyl_count(self.disctitle) if self.media == "Vinyl" else 1

    @cached_property
    def catalognum(self) -> str:
        return self.parse_catalognum(self.album_name, self.disctitle, self.description)

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
        except (KeyError, ValueError, LookupError):
            return WORLDWIDE

    @cached_property
    def tracks(self) -> List[JSONDict]:
        """Parse relevant details from the tracks' JSON."""
        if self._singleton:
            raw_tracks = [{"item": self.meta}]
        else:
            raw_tracks = self.meta["track"].get("itemListElement", [])

        tracks = []
        for raw_track in raw_tracks:
            raw_item = raw_track["item"]
            name, digital_only = self.clean_digital_only_track(raw_item["name"])
            track = dict(
                digital_only=digital_only,
                index=raw_track.get("position") or 1,
                track_id=raw_item.get("@id"),
                length=self.get_duration(raw_item),
                **self.parse_track_name(name),
            )
            track["medium_index"] = track["index"]
            track["artist"] = raw_item.get("byArtist", {}).get("name", track["artist"])
            if not track["artist"]:
                track["artist"] = self.bandcamp_albumartist
            tracks.append(track)

        return tracks

    @cached_property
    def track_artists(self) -> Set[str]:
        ignore = r" f(ea)?t\. .*"
        artists = set(re.sub(ignore, "", t.get("artist") or "") for t in self.tracks)
        artists.discard("")
        return artists

    @property
    def is_single(self) -> bool:
        return self._singleton or len(set(t.get("main_title") for t in self.tracks)) == 1

    @property
    def is_lp(self) -> bool:
        return "LP" in self.album_name or "LP" in self.disctitle

    @cached_property
    def is_ep(self) -> bool:
        return "EP" in self.album_name or "EP" in self.disctitle

    @cached_property
    def is_va(self) -> bool:
        return "various artists" in self.album_name.lower() or (
            len(self.track_artists) > 1
            and not {self.bandcamp_albumartist}.issubset(self.track_artists)
            and len(self.tracks) > 4
        )

    @cached_property
    def albumartist(self) -> str:
        """Handle various artists and albums that have a single artist."""
        if self.is_va:
            return "Various Artists"
        if self.label == self.bandcamp_albumartist:
            artists = self.track_artists
            if len(artists) == 1:
                return next(iter(artists))
        return self.bandcamp_albumartist

    @property
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

    @property
    def clean_album_name(self) -> str:
        args = set(filter(truth, [self.catalognum, self.label]))
        if not self._singleton:
            args.add(self.bandcamp_albumartist)
        return self.clean_up_album_name(self.album_name, *args)

    @property
    def _common(self) -> JSONDict:
        return dict(
            data_source=DATA_SOURCE,
            media=self.media,
            data_url=self.album_id,
            artist_id=self.artist_id,
        )

    @property
    def _common_album(self) -> JSONDict:
        return dict(
            year=self.release_date.year,
            month=self.release_date.month,
            day=self.release_date.day,
            label=self.label,
            catalognum=self.catalognum,
            albumtype=self.albumtype,
            album=self.clean_album_name,
            albumstatus=OFFICIAL if self.release_date <= date.today() else PROMO,
            country=self.country,
        )

    def _trackinfo(self, track: JSONDict, medium_total: int, **kwargs: Any) -> TrackInfo:
        track.pop("digital_only")
        track.pop("main_title")
        return TrackInfo(
            **self._common,
            **track,
            disctitle=self.disctitle or None,
            medium=1,
            medium_total=medium_total,
            **kwargs,
        )

    @property
    def singleton(self) -> TrackInfo:
        self._singleton = True
        track = self.tracks[0]
        track.update(self.parse_track_name(self.album_name))
        kwargs: JSONDict = {}
        if NEW_BEETS:
            kwargs.update(**self._common_album, albumartist=self.bandcamp_albumartist)

        return self._trackinfo(track.copy(), 1, **kwargs)

    def albuminfo(self, include_all: bool) -> AlbumInfo:
        if self.media == "Digital Media" or include_all:
            filtered_tracks = self.tracks
        else:
            filtered_tracks = [t for t in self.tracks if not t["digital_only"]]

        medium_total = len(filtered_tracks)
        _tracks = [self._trackinfo(t.copy(), medium_total) for t in filtered_tracks]
        return AlbumInfo(
            **self._common,
            **self._common_album,
            artist=self.albumartist,
            album_id=self.album_id,
            va=self.is_va,
            mediums=self.mediums,
            tracks=_tracks,
        )

    def album(self, include_all: bool) -> AlbumInfo:
        """Return album for the appropriate release format."""
        try:
            media = self._get_media(self.meta)
        except (KeyError, AttributeError):
            return None
        self._all_media = set(media)
        # if preference is given and the format is available, return it
        for preference in self.preferred_media.split(","):
            if preference in media:
                self._media = media[preference]
                break
        else:  # otherwise, use the default option
            self._media = media[DEFAULT_MEDIA]

        return self.albuminfo(include_all)
