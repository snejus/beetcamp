"""Module for parsing bandcamp metadata."""
import json
import re
from datetime import date, datetime
from functools import reduce
from math import floor
from string import ascii_lowercase, digits
from typing import Any, Dict, List, Optional, Pattern, Set, Union
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
DEFAULT_COUNTRY = "XW"
DEFAULT_MEDIA = "Digital Media"
MEDIA_MAP = {
    "VinylFormat": "Vinyl",
    "CDFormat": "CD",
    "CassetteFormat": "Cassette",
    "DigitalFormat": DEFAULT_MEDIA,
}
VALID_URL_CHARS = {*ascii_lowercase, *digits}

_catalognum = r"([^\d\W]+[_\W]?\d{2,}(?:\W\d|CD)?)"
_exclusive = r"\s?[\[(](bandcamp )?(digi(tal)? )?(bonus|only|exclusive)[\])]"
PATTERNS: Dict[str, Pattern] = {
    "meta": re.compile(r".*datePublished.*", flags=re.MULTILINE),
    "quick_catalognum": re.compile(rf"\[{_catalognum}\]"),
    "catalognum": re.compile(rf"^{_catalognum}|{_catalognum}$"),
    "catalognum_excl": re.compile(r"(?i:vol(ume)?|artists)|202[01]|(^|\s)C\d\d|\d+/\d+"),
    "country": re.compile(r'location\ssecondaryText">(?:[\w\s.]*, )?([\w\s,]+){1,4}'),
    "digital": re.compile(rf"^DIGI (\d+\.\s?)?|(?i:{_exclusive})"),
    "label": re.compile(r'og:site_name".*content="([^"]*)"'),
    "lyrics": re.compile(r'"lyrics":({[^}]*})'),
    "release_date": re.compile(r"release[ds] ([\d]{2} [A-Z][a-z]+ [\d]{4})"),
    "track_name": re.compile(
        r"""
((?P<track_alt>(^[ABCDEFGH]{1,3}\d|^\d)\d?)\s?[.-][^\w]*)?
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
    def check_digital_only(name: str) -> Dict[str, Union[bool, str]]:
        no_digi_only_name = re.sub(PATTERNS["digital"], "", name)
        if no_digi_only_name != name:
            return dict(digital_only=True, name=no_digi_only_name)
        return dict(digital_only=False)

    @staticmethod
    def parse_track_name(name: str) -> JSONDict:
        match = re.search(PATTERNS["track_name"], name)
        try:
            return match.groupdict()  # type: ignore
        except AttributeError:
            return {"title": name, "artist": None, "track_alt": None}

    @staticmethod
    def parse_catalognum(album: str, disctitle: str) -> str:
        for pattern, string in [
            (PATTERNS["quick_catalognum"], album),
            (PATTERNS["catalognum"], disctitle),
            (PATTERNS["catalognum"], album),
        ]:
            match = re.search(pattern, re.sub(PATTERNS["catalognum_excl"], "", string))
            if match:
                return [group for group in match.groups() if group].pop()

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
        excl = "Various Artists|limited edition"

        # handle special chars
        extras = "|".join(map(re.escape, args))
        excl = rf"({excl}|{extras})" if extras else rf"({excl})"

        pat = re.compile(
            rf" EP|({excl}\s[|/]+\s?)|[\[(]{excl}[])]|(\s-\s){excl}|{excl}(\s?-\s)",
            flags=re.IGNORECASE,
        )
        return re.sub(pat, "", name).strip()


class Metaguru(Helpers):
    html: str
    preferred_media: str
    meta: JSONDict

    _all_medias = {DEFAULT_MEDIA}  # type: Set[str]
    _media = None  # type: Dict[str, str]
    _singleton = False  # type: bool

    def __init__(self, html: str, media: str = DEFAULT_MEDIA) -> None:
        self.html = html
        self.preferred_media = media

        self.meta = {}
        match = re.search(PATTERNS["meta"], html)
        if match:
            self.meta = json.loads(match.group())

    def _search(self, pattern: Pattern[str]) -> str:
        match = re.search(pattern, self.html)
        return match.groups()[0] if match else ""

    @cached_property
    def album_name(self) -> str:
        return self.meta["name"]

    @property
    def clean_album_name(self) -> str:
        args = {self.label, self.catalognum}.difference({""})
        if not self._singleton:
            args.add(self.albumartist)
        return self.clean_up_album_name(self.album_name, *args)

    @cached_property
    def album_id(self) -> str:
        return self.meta["@id"]

    @cached_property
    def artist_id(self) -> str:
        try:
            return self.meta["byArtist"]["@id"]
        except KeyError:
            return self.meta["publisher"]["@id"]

    @property
    def image(self) -> str:
        # TODO: Need to test
        image = self.meta.get("image", "")
        return image[0] if isinstance(image, list) else image

    @cached_property
    def label(self) -> str:
        return self._search(PATTERNS["label"])

    @property
    def lyrics(self) -> Optional[str]:
        # TODO: Need to test
        matches = re.findall(PATTERNS["lyrics"], self.html)
        if not matches:
            return None
        return "\n".join(json.loads(m).get("text") for m in matches)

    @cached_property
    def release_date(self) -> date:
        datestr = self.parse_release_date(self.html)
        return datetime.strptime(datestr, DATE_FORMAT).date()

    @cached_property
    def disctitle(self) -> str:
        if self._media and self.media != "Digital Media":
            return self._media.get("name", "")
        return ""

    @cached_property
    def catalognum(self) -> str:
        # TODO: Can also search the description for more info, e.g. catalog: catalognum
        return self.parse_catalognum(self.album_name, self.disctitle)

    @property
    def country(self) -> str:
        country = self._search(PATTERNS["country"])
        ascii_name = normalize("NFKD", country).encode("ascii", "ignore").decode()
        try:
            return (
                COUNTRY_OVERRIDES.get(country)
                or getattr(
                    countries.get(name=ascii_name, default=object), "alpha_2", None
                )
                or subdivisions.lookup(ascii_name).country_code
            )
        except LookupError:
            return DEFAULT_COUNTRY

    @cached_property
    def media(self) -> str:
        if self._media:
            return MEDIA_MAP[self._media["musicReleaseFormat"]]
        return DEFAULT_MEDIA

    @property
    def mediums(self) -> int:
        if self.media != "Vinyl":
            return 1
        return self.get_vinyl_count(self.disctitle)

    @property
    def description(self) -> str:
        descr = self.meta.get("description", "")
        if not descr and self._media:
            descr = self._media.get("description", "")
            if descr.startswith("Includes high-quality dow"):
                descr = ""
        return descr

    @cached_property
    def tracks(self) -> List[JSONDict]:
        """Tracks JSON structure as of mid April, 2021.
        "itemListElement": [{
          "@type": "ListItem"
          "position": 1,
          "item": {
            "@id": "https://sinensis-ute.bandcamp.com/track/live-at-parken",
            "name": "Live At PARKEN",
            "@type": ["MusicRecording"],
            "copyrightNotice": "All Rights Reserved",
            "duration": "P01H00M00S",
            "additionalProperty": [
              { "value": 613900326,
                "name": "track_id",
                "@type": "PropertyValue" },
              { ... and same structure found for the following fields
                "name": "duration_secs",
                "name": "file_mp3-128",
                "name": "license_name",
                "name": "streaming",
                "name": "tracknum" }
            ]
          }
        }]
        """
        tracks = []
        if not self._singleton:
            raw_tracks = self.meta["track"].get("itemListElement", [])
        else:
            raw_tracks = [{"item": self.meta}]
        for raw_track in raw_tracks:
            track = raw_track["item"]
            track["position"] = raw_track.get("position") or 1
            track.update(self.check_digital_only(track["name"]))
            track.update(self.parse_track_name(track["name"]))
            tracks.append(track)
        return tracks

    @cached_property
    def track_artists(self) -> Set[str]:
        ignore = r" f(ea)?t\. .*"
        artists = set(re.sub(ignore, "", t.get("artist") or "") for t in self.tracks)
        artists.discard("")
        return artists

    @property
    def is_lp(self) -> bool:
        return "LP" in self.album_name or "LP" in self.disctitle

    @cached_property
    def is_ep(self) -> bool:
        return ("EP" in self.album_name or "EP" in self.disctitle) or (
            self._all_medias != {DEFAULT_MEDIA} and len(self.tracks) < 5
        )

    @cached_property
    def is_va(self) -> bool:
        return "various artists" in self.album_name.lower() or (
            len(self.track_artists) > 1 and len(self.tracks) > 4
        )

    @cached_property
    def bandcamp_albumartist(self) -> str:
        """Return original album artist - most often the label name."""
        return self.meta["byArtist"]["name"]

    @cached_property
    def albumartist(self) -> str:
        """Handle various artists and albums that have a single artist."""
        if self.is_va:
            return "Various Artists"
        if len(self.track_artists) == 1:
            return next(iter(self.track_artists))
        return self.bandcamp_albumartist

    @property
    def albumtype(self) -> str:
        if self._singleton:
            return "single"
        if self.is_lp:
            return "album"
        if self.is_va:
            return "compilation"
        return "ep"

    @property
    def _common(self) -> JSONDict:
        return dict(
            data_source=DATA_SOURCE,
            media=self.media or DEFAULT_MEDIA,
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
            albumstatus=OFFICIAL if self.release_date < date.today() else PROMO,
            country=self.country,
        )

    def _trackinfo(self, track: JSONDict, medium_total: int, **kwargs) -> TrackInfo:
        index = kwargs.pop("index", None) or track.get("position")
        return TrackInfo(
            **self._common,
            title=track.get("title"),
            track_id=kwargs.pop("track_id", None) or track.get("@id"),
            artist=track.get("artist") or self.bandcamp_albumartist,
            index=index,
            length=self.get_duration(track),
            track_alt=track.get("track_alt"),
            disctitle=self.disctitle or None,
            medium=1,
            medium_index=index,
            medium_total=medium_total,
            **kwargs,
        )

    @property
    def singleton(self) -> TrackInfo:
        self._singleton = True
        track = self.meta
        track.update(self.parse_track_name(self.album_name))
        kwargs = dict(track_id=self.album_id, index=1)
        if NEW_BEETS:
            kwargs.update(**self._common_album, albumartist=self.bandcamp_albumartist)

        return self._trackinfo(track, 1, **kwargs)

    def albuminfo(self, include_all: bool) -> AlbumInfo:
        if self.media == "Digital Media" or include_all:
            filtered_tracks = self.tracks
        else:
            filtered_tracks = [t for t in self.tracks if not t["digital_only"]]

        medium_total = len(filtered_tracks)
        _tracks = [self._trackinfo(track, medium_total) for track in filtered_tracks]
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
        # map available formats to appropriate names
        medias: JSONDict = {}
        try:
            for _format in self.meta["albumRelease"]:
                try:
                    media = _format["musicReleaseFormat"]
                except KeyError:
                    continue
                human_name = MEDIA_MAP[media]
                medias[human_name] = _format
        except (KeyError, AttributeError):
            return None

        self._all_medias = set(medias)
        # if preference is given and the format is available, return it
        for preference in self.preferred_media.split(","):
            if preference in medias:
                self._media = medias[preference]
                break
        else:  # otherwise, use the default option
            self._media = medias[DEFAULT_MEDIA]

        return self.albuminfo(include_all)
