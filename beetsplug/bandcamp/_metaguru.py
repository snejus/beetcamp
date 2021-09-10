"""Module for parsing bandcamp metadata."""
import json
import re
from datetime import date, datetime
from functools import reduce
from math import floor
from operator import truth
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
    "D.C.": "US",
    "South Korea": "KR",  # pycountry: Korea, Republic of
}
DATA_SOURCE = "bandcamp"
WORLDWIDE = "XW"
DEFAULT_MEDIA = "Digital Media"
MEDIA_MAP = {
    "VinylFormat": "Vinyl",
    "CDFormat": "CD",
    "CassetteFormat": "Cassette",
    "DigitalFormat": DEFAULT_MEDIA,
}
VA = "Various Artists"

_catalognum = r"(\b[A-Za-z]([^-.\s\d]|[.-][^0-9])+(([-.]?|[A-Z]\s)\d+|\s\d{2,})[A-Z]?(?:[.-]?\d|CD)?\b)"  # noqa
_exclusive = r"[*\[( -]*(bandcamp|digi(tal)?) (digital )?(only|bonus|exclusive)[*\])]?"
_catalognum_header = r"(?:Catalogue(?: (?:Number|N[or]))?|Cat N[or])\.?:"
PATTERNS: Dict[str, Pattern] = {
    "meta": re.compile(r".*dateModified.*", flags=re.MULTILINE),
    "desc_catalognum": re.compile(rf"(?:{_catalognum_header} ?)([A-Z]+[. -]?[0-9]+)"),
    "quick_catalognum": re.compile(rf"[\[(]{_catalognum}[])]"),
    "catalognum": re.compile(rf"(^{_catalognum}|{_catalognum}$)"),
    "catalognum_excl": re.compile(
        r"(?i:vol(ume)?|artists|\bva\d+|vinyl|triple|ep 12)|202[01]|(^|\s)C\d\d|\d+/\d+"
    ),
    "digital": re.compile(rf"^DIGI (\d+\.\s?)?|(?i:{_exclusive})"),
    "lyrics": re.compile(r'"lyrics":({[^}]*})'),
    "clean_incl": re.compile(r"(?i:(\(?incl[^)]+\)?|\([^)]+remix[^)]+\)))"),
    "remix_or_ft": re.compile(r"\s(?i:(\[|\().*(mix|edit)|f(ea)?t\.).*"),
    "track_alt": re.compile(r"([ABCDEFGH]{1,3}[0-9])(\.|.?- )"),
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
        return int(count) if count.isdigit() else conv[count.casefold()]

    @staticmethod
    def clean_digital_only_track(name: str) -> Tuple[str, bool]:
        """Return cleaned title and whether this track is digital-only."""
        clean_name = re.sub(PATTERNS["digital"], "", name)
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

        # in most cases that's the delimiter between the artist and the title
        parts = re.split(r"\s-\s|\s?-\s|\s-\s?", name.strip(",.- "))

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
        for pattern, source in [
            (PATTERNS["desc_catalognum"], description),
            (PATTERNS["quick_catalognum"], album),
            (rf"({label}\s?[0-9]+)", album) if label else (None, None),
            (PATTERNS["catalognum"], album),
            (PATTERNS["catalognum"], disctitle),
        ]:
            if not pattern:
                continue

            match = re.search(pattern, re.sub(PATTERNS["catalognum_excl"], "", source))
            if match:
                return match.groups()[0]
        return ""

    @staticmethod
    def get_duration(source: JSONDict) -> int:
        return [
            floor(x.get("value", 0))
            for x in source.get("additionalProperty", [])
            if x.get("name") == "duration_secs"
        ][0]

    @staticmethod
    def clean_name(name: str, *args: str, remove_extra: bool = False) -> str:
        """Return the clean album name.
        If it ends up cleaning the name entirely, then return the first `args` member
        if given (catalognum or label). If not given, return the original name.

        If `remove_extra`, remove info from within the parentheses (usually remix info).
        """
        # catalognum, album, albumartist
        for arg in args:
            name = name.replace(arg, "")

        # redundant spaces, duoble quotes, parentheses
        for pat, repl in [
            (r"\s\s+", " "),
            (r"\(\s+|(- )?\(+", "("),
            (r"\s+\)|\)+", ")"),
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

        rubbish = r"(?i:\b({})(\b|[\])]|$))".format(excl)
        empty_parens = r"\(\)|\[\]"
        default = next(iter([*args, name]))

        def clean(patstr: str, text: str) -> str:
            return re.sub(patstr, "", text)

        return clean(empty_parens, clean(rubbish, name)).strip("/-|([. ") or default

    @staticmethod
    def _get_media_index(meta: JSONDict) -> JSONDict:
        """Get release media from the metadata, excluding bundles.
        Return a dictionary with a human mapping (Digital|CD|Vinyl|Cassette) -> media.
        """
        media: JSONDict = {}
        for _format in meta["albumRelease"]:
            try:
                if "bundle" in _format["name"].casefold():
                    raise KeyError

                medium = _format["musicReleaseFormat"]
            except KeyError:
                continue
            human_name = MEDIA_MAP[medium]
            media[human_name] = _format
        return media


class Metaguru(Helpers):
    html: str
    meta: JSONDict
    include_all_tracks: bool

    _media: Dict[str, str]
    _singleton = False

    def __init__(
        self, html: str, media_prefs: str = DEFAULT_MEDIA, include_all_tracks: bool = True
    ) -> None:
        self.html = html
        self.meta = {}
        self.include_all_tracks = include_all_tracks

        match = re.search(PATTERNS["meta"], html)
        if match:
            self.meta = json.loads(match.group())

        self._media = self.meta.get("albumRelease", [{}])[0]
        try:
            media_index = self._get_media_index(self.meta)
        except (KeyError, AttributeError):
            pass
        else:
            # if preference is given and the format is available, use it
            for preference in media_prefs.split(","):
                if preference in media_index:
                    self._media = media_index[preference]
                    break

    @cached_property
    def description(self) -> str:
        """Return album and media description unless they start with a generic message.
        If credits exist, append them too.
        """
        _credits = self.meta.get("creditText", "")
        parts = [
            self.meta.get("description", ""),
            "" if self.media_name == DEFAULT_MEDIA else self._media.get("description"),
            "Credits: " + _credits if _credits else "",
        ]
        return reduce(lambda x, y: f"{x}\n - {y}", filter(truth, parts), "").replace(
            "\r", ""
        )

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
        match = re.search(r"Artist:([^\n]+)", self.description)
        if match:
            return str(match.groups()[0].strip())

        albumartist = self.meta["byArtist"]["name"].replace("various", VA)
        album = self.album_name
        if self.label == albumartist:
            albumartist = (
                self.parse_track_name(album, self.catalognum).get("artist") or albumartist
            )

        return re.sub(r"(?i:, ft.*remix.*)", "", albumartist)

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
        """Parse the datestring that takes the format like below and return date object.
        {"datePublished": "17 Jul 2020 00:00:00 GMT"}
        """
        date_part = re.sub(r"\s[0-9]{2}:.+", "", self.meta["datePublished"])
        return datetime.strptime(date_part, "%d %b %Y").date()

    @cached_property
    def media_name(self) -> str:
        """Return the human-readable version of the media format."""
        return MEDIA_MAP.get(self._media.get("musicReleaseFormat", ""), DEFAULT_MEDIA)

    @cached_property
    def disctitle(self) -> str:
        """Return medium's disc title if found."""
        return "" if self.media_name == DEFAULT_MEDIA else self._media.get("name", "")

    @cached_property
    def mediums(self) -> int:
        return self.get_vinyl_count(self.disctitle) if self.media_name == "Vinyl" else 1

    @cached_property
    def catalognum(self) -> str:
        return self.parse_catalognum(
            self.album_name, self.disctitle, self.description, self.label
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
            name = self.clean_name(name, *filter(truth, [self.catalognum, self.label]))
            track = dict(
                digital_only=digital_only,
                index=index,
                medium_index=index,
                track_id=raw_item.get("@id"),
                length=self.get_duration(raw_item),
                **self.parse_track_name(name, catalognum),
            )
            track["artist"] = self.get_track_artist(
                track["artist"], raw_item, albumartist  # type: ignore
            )

            tracks.append(track)

        return tracks

    @cached_property
    def track_artists(self) -> Set[str]:
        artists = {(t.get("artist") or "") for t in self.tracks}
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

    def _trackinfo(self, track: JSONDict, **kwargs: Any) -> TrackInfo:
        track.pop("digital_only")
        track.pop("main_title")
        return TrackInfo(
            **self._common,
            **track,
            disctitle=self.disctitle or None,
            medium=1,
            **kwargs,
        )

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
        if self.media_name == DEFAULT_MEDIA or self.include_all_tracks:
            filtered_tracks = self.tracks
        else:
            filtered_tracks = [t for t in self.tracks if not t["digital_only"]]

        total = len(filtered_tracks)
        _tracks = [self._trackinfo(t.copy(), medium_total=total) for t in filtered_tracks]
        return AlbumInfo(
            **self._common,
            **self._common_album,
            artist=self.albumartist,
            album_id=self.album_id,
            va=self.albumtype == "compilation",
            mediums=self.mediums,
            tracks=_tracks,
        )
