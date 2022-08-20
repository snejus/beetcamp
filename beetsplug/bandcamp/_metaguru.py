"""Module for parsing bandcamp metadata."""
import itertools as it
import json
import operator as op
import re
import sys
from collections import Counter
from datetime import date, datetime
from functools import partial
from typing import Any, Dict, Iterable, List, Optional, Set
from unicodedata import normalize

from beets import __version__ as beets_version
from beets import config as beets_config
from beets.autotag.hooks import AlbumInfo, TrackInfo
from ordered_set import OrderedSet as ordset
from pycountry import countries, subdivisions

from ._helpers import PATTERNS, Helpers, MediaInfo
from ._tracks import Track, Tracks

if sys.version_info.minor > 7:
    from functools import cached_property  # pylint: disable=ungrouped-imports
else:
    from cached_property import cached_property  # type: ignore # pylint: disable=import-error # noqa

NEW_BEETS = int(beets_version.split(".")[1]) > 4

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
VA = "Various Artists"


class Metaguru(Helpers):
    _singleton = False
    va_name = VA
    media = MediaInfo("", "", "", "")

    meta: JSONDict
    config: JSONDict
    media_formats: List[MediaInfo]
    _tracks: Tracks

    def __init__(self, meta: JSONDict, config: Optional[JSONDict] = None) -> None:
        self.meta = meta
        self.media_formats = Helpers.get_media_formats(
            (meta.get("inAlbum") or meta).get("albumRelease") or []
        )
        if self.media_formats:
            self.media = self.media_formats[0]
        self.config = config or {}
        self.va_name = beets_config["va_name"].as_str() or self.va_name
        self._tracks = Tracks.from_json(meta)

    @classmethod
    def from_html(cls, html: str, config: JSONDict = None) -> "Metaguru":
        try:
            meta = re.search(PATTERNS["meta"], html).group()  # type: ignore[union-attr]
        except AttributeError as exc:
            raise AttributeError("Could not find release metadata JSON") from exc
        else:
            return cls(json.loads(meta), config)

    @cached_property
    def excluded_fields(self) -> Set[str]:
        return set(self.config.get("excluded_fields") or [])

    @property
    def comments(self) -> str:
        """Return release, media descriptions and credits separated by
        the configured separator string.
        """
        parts = [self.meta.get("description")]
        media_desc = self.media.description
        if media_desc and not media_desc.startswith("Includes high-quality"):
            parts.append(media_desc)

        parts.append(self.meta.get("creditText"))
        sep = self.config["comments_separator"]
        return sep.join(filter(op.truth, parts)).replace("\r", "")

    @cached_property
    def all_media_comments(self) -> str:
        return "\n".join([*[m.description for m in self.media_formats], self.comments])

    @cached_property
    def official_album_name(self) -> str:
        """Check description for the album name header and return whatever follows it
        if found.
        """
        m = re.search(r"(Title: ?|Album(:|/Single) )([^\n]+)", self.all_media_comments)
        if m:
            return m.group(3).strip()
        return ""

    @cached_property
    def parsed_album_name(self) -> str:
        """
        Search for the album name in the following order and return the first match:
        1. Album name is found in *all* track names
        2. When 'EP' or 'LP' is in the release name, album name is what precedes it.
        3. If some words are enclosed in quotes in the release name, it is assumed
           to be the album name. Remove the quotes in such case.
        """
        album_in_tracks = {t.album for t in self._tracks if t.album}
        if len(album_in_tracks) == 1:
            return list(album_in_tracks)[0]

        album = self.album_name
        for pat in [
            r"(((&|#?\b(?!Double|VA|Various)(\w|[^\w| -])+) )+[EL]P)",
            r"((['\"])([^'\"]+)\2( VA\d+)*)( |$)",
        ]:
            m = re.search(pat, album)
            if m:
                album = m.group(1).strip()
                return re.sub(r"^['\"](.+)['\"]$", r"\1", album)
        return album

    @cached_property
    def album_name(self) -> str:
        return self.meta["name"]

    @cached_property
    def label(self) -> str:
        match = re.search(r"Label:([^/,\n]+)", self.all_media_comments)
        if match:
            return match.expand(r"\1").strip(" '\"")

        return self.get_label(self.meta)

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
    def original_albumartist(self) -> str:
        m = re.search(r"Artists?:([^\n]+)", self.all_media_comments)
        aartist = m.group(1).strip() if m else self.meta["byArtist"]["name"]
        return re.sub(r" +// +", ", ", aartist)

    @cached_property
    def bandcamp_albumartist(self) -> str:
        """Return the official release albumartist.
        It is correct in half of the cases. In others, we usually find the label name.
        """
        aartist = self.original_albumartist
        if self.label == aartist:
            split = self.clean_album(self.album_name, self.catalognum).split(" - ")
            if len(split) > 1:
                aartist = split[0]

        aartists = Helpers.split_artists([aartist])
        if len(aartists) == 1:
            return aartist

        remixers_str = " ".join(self._tracks.other_artists).lower()

        def not_remixer(x: str) -> bool:
            splits = {x, *x.split(" & ")}
            return not any(y.lower() in remixers_str for y in splits)

        valid = list(filter(not_remixer, aartists))
        if len(valid) == len(aartists) and len(self._tracks.artists) <= 4:
            return aartist
        return ", ".join(valid)

    @cached_property
    def image(self) -> str:
        image = self.meta.get("image", "")
        return image[0] if isinstance(image, list) else image

    @cached_property
    def release_date(self) -> Optional[date]:
        """Parse the datestring that takes the format like below and return date object.
        {"datePublished": "17 Jul 2020 00:00:00 GMT"}

        If the field is not found, return None.
        """
        rel = self.meta.get("datePublished") or self.meta.get("dateModified")
        if rel:
            return datetime.strptime(re.sub(r" \d{2}:.+", "", rel), "%d %b %Y").date()
        return rel

    @cached_property
    def albumstatus(self) -> str:
        reldate = self.release_date
        return "Official" if reldate and reldate <= date.today() else "Promotional"

    @property
    def disctitle(self) -> str:
        """Return medium's disc title if found."""
        return "" if self.media.name == DIGI_MEDIA else self.media.title

    @property
    def mediums(self) -> int:
        return self.get_vinyl_count(self.disctitle) if self.media.name == "Vinyl" else 1

    @cached_property
    def general_catalognum(self) -> str:
        """Find catalog number in the media-agnostic release metadata and cache it."""
        cats = [t.catalognum for t in self._tracks if t.catalognum]
        artists = ordset([self.original_albumartist])
        if not self._singleton or len(self._tracks.artists) > 1:
            artists.update(self._tracks.artists)
            artists.update(self._tracks.other_artists)

        catnum = self.parse_catalognum(
            album=self.meta["name"],
            description=self.comments,
            label=self.label if not self._singleton else "",
            tracks=tuple(self._tracks.raw_names),
            artists=tuple(artists),
        )
        if len(cats) == len(self._tracks) and len(set(cats)) == 1:
            return list(cats)[0]
        return catnum

    @property
    def catalognum(self) -> str:
        """Find catalog number in the media-specific release metadata or return
        the cached media-agnostic one.
        """
        return (
            self.parse_catalognum(
                disctitle=self.disctitle,
                description=self.media.description,
                label=self.label if not self._singleton else "",
                tracks=tuple(self._tracks.raw_names),
            )
            or self.general_catalognum
        )

    @cached_property
    def country(self) -> str:
        try:
            loc = self.meta["publisher"]["foundingLocation"]["name"].rpartition(", ")[
                -1
            ]
            name = normalize("NFKD", loc).encode("ascii", "ignore").decode()
            return (
                COUNTRY_OVERRIDES.get(name)
                or getattr(countries.get(name=name, default=object), "alpha_2", None)
                or subdivisions.lookup(name).country_code
            )
        except (ValueError, LookupError):
            return WORLDWIDE

    @cached_property
    def tracks(self) -> Tracks:
        self._tracks.adjust_artists(self.bandcamp_albumartist)
        return self._tracks

    @cached_property
    def unique_artists(self) -> List[str]:
        return self.split_artists(self._tracks.artists)

    @cached_property
    def albumartist(self) -> str:
        """Take into account the release contents and return the actual albumartist.
        * 'Various Artists' (or `va_name` configuration option) for a compilation release
        """
        if self.va:
            return self.va_name

        if len(self._tracks) == 1:
            return self.tracks.first.artist

        aartist = self.original_albumartist
        if self.unique_artists:
            aartist = ", ".join(sorted(self.unique_artists))

        return aartist

    @cached_property
    def vinyl_disctitles(self) -> str:
        return " ".join([m.title for m in self.media_formats if m.name == "Vinyl"])

    def _search_albumtype(self, word: str) -> bool:
        """Return whether the given word (ep or lp) matches the release albumtype.
        True when one of the following conditions is met:
        * if {word}[0-9] is found in the catalognum
        * if it's found in the original album name or any vinyl disctitle
        * if it's found in the same sentence as 'this' or '{album_name}', where
        sentences are read from release and media descriptions.
        """
        sentences = re.split(r"[.]\s+|\n", self.all_media_comments)
        word_pat = re.compile(rf"\b{word}\b", re.I)
        catnum_pat = re.compile(rf"{word}\d", re.I)
        name_pat = re.compile(rf"\b(this|{re.escape(self.clean_album_name)})\b", re.I)
        return bool(
            catnum_pat.search(self.catalognum)
            or word_pat.search(self.album_name + " " + self.vinyl_disctitles)
            or any(word_pat.search(s) and name_pat.search(s) for s in sentences)
        )

    @cached_property
    def is_single_album(self) -> bool:
        return (
            self._singleton
            or len({t.main_title for t in self.tracks}) == 1
            or len(self._tracks.raw_names) == 1
        )

    @cached_property
    def is_lp(self) -> bool:
        """Return whether the release is an LP."""
        return self._search_albumtype("lp")

    @cached_property
    def is_ep(self) -> bool:
        """Return whether the release is an EP."""
        return self._search_albumtype("ep")

    def check_albumtype_in_descriptions(self) -> str:
        """Count 'lp', 'album' and 'ep' words in the release and media descriptions
        and return the albumtype that represents the word matching the most times.
        """
        matches = re.findall(r"\b(album|ep|lp)\b", self.all_media_comments.lower())
        if matches:
            counts = Counter(x.replace("lp", "album") for x in matches)
            # if equal, we assume it's an EP since it's more likely that an EP is
            # referred to as an "album" rather than the other way around
            if counts["ep"] >= counts["album"]:
                return "ep"
        return "album"

    @cached_property
    def is_comp(self) -> bool:
        """Return whether the release is a compilation."""

        def first_one(artist: str) -> str:
            return PATTERNS["split_artists"].split(artist.replace(" & ", ", "))[0]

        truly_unique = set(map(first_one, self.tracks.artists))
        return (
            bool(re.search(r"compilation|best of|anniversary", self.album_name, re.I))
            or self._search_albumtype("compilation")
            or (len(truly_unique) > 3 and len(self.tracks) > 4)
        )

    @cached_property
    def albumtype(self) -> str:
        if self._singleton:
            return "single"
        if self.is_ep:
            return "ep"
        if self.is_lp:
            return "album"

        atype = self.check_albumtype_in_descriptions()
        if atype == "ep":
            return "ep"
        # otherwise, it's an album, but we firstly need to check if it's a compilation
        if self.is_comp:
            return "compilation"

        return "album"

    @cached_property
    def albumtypes(self) -> str:
        albumtypes = {self.albumtype}
        if self.is_comp:
            if self.albumtype == "ep":
                albumtypes.add("compilation")
            else:
                albumtypes.add("album")
        if self.is_lp:
            albumtypes.add("lp")
        if self.is_single_album:
            albumtypes.add("single")
        for word in ["remix", "rmx", "edits", "live", "soundtrack"]:
            if word in self.album_name.lower():
                albumtypes.add(word.replace("rmx", "remix").replace("edits", "remix"))
        rmxers = [
            t.remixer for t in self.tracks if t.remixer and t.remixer != "Original"
        ]
        if len(rmxers) == len(self.tracks):
            albumtypes.add("remix")

        return "; ".join(sorted(albumtypes))

    @cached_property
    def va(self) -> bool:
        return len(self.unique_artists) > 3

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
        genres = self.get_genre(kws, genre_cfg, self.label)
        if genre_cfg["capitalize"]:
            genres = map(str.capitalize, genres)
        if genre_cfg["maximum"]:
            genres = it.islice(genres, genre_cfg["maximum"])

        return ", ".join(sorted(genres)).strip() or None

    @cached_property
    def eplp_album_comments(self) -> str:
        """Parse comments looking for an indication of an album in the following format
        (Capital-case Album Name) (EP or LP)
        and return the matching album name if found.
        """
        m = re.search(r"((?!The|This)\b[A-Z][^ \n]+\b )+[EL]P", self.all_media_comments)
        return m.group() if m else ""

    @cached_property
    def clean_album_name(self) -> str:
        if self.official_album_name:
            return self.official_album_name

        album = self.parsed_album_name or self.album_name
        artists = [*self.tracks.raw_artists, *self.tracks.artists]
        artists.sort(key=len, reverse=True)
        album = self.clean_album(album, self.catalognum, *artists, label=self.label)

        if album.startswith("("):
            album = self.album_name
        return album or self.eplp_album_comments or self.catalognum or self.album_name

    @property
    def _common(self) -> JSONDict:
        return {
            "data_source": DATA_SOURCE,
            "media": self.media.name,
            "data_url": self.album_id,
            "artist_id": self.artist_id,
        }

    def get_fields(self, fields: Iterable[str], src: object = None) -> JSONDict:
        """Return a mapping between unexcluded fields and their values."""
        fields = list(set(fields) - self.excluded_fields)
        if len(fields) == 1:
            field = fields.pop()
            return {field: getattr(self, field)}
        return dict(zip(fields, iter(op.attrgetter(*fields)(src or self))))

    @property
    def _common_album(self) -> JSONDict:
        common_data: JSONDict = {"album": self.clean_album_name}
        fields = ["label", "catalognum", "albumtype", "country"]
        if NEW_BEETS:
            fields.extend(["genre", "style", "comments", "albumtypes"])
        common_data.update(self.get_fields(fields))
        reldate = self.release_date
        if reldate:
            common_data.update(self.get_fields(["year", "month", "day"], reldate))

        return common_data

    def _trackinfo(self, track: Track, **kwargs: Any) -> TrackInfo:
        data = track.info
        data.update(**self._common, **kwargs)
        # if track-level catalognum is not found or if it is the same as album's, then
        # remove it. Otherwise, keep it attached to the track
        if not data["catalognum"] or data["catalognum"] == self.catalognum:
            data.pop("catalognum", None)
        if not data["lyrics"]:
            data.pop("lyrics", None)
        if not NEW_BEETS:
            data.pop("catalognum", None)
            data.pop("lyrics", None)
        for field in set(data.keys()) & self.excluded_fields:
            data.pop(field)

        return TrackInfo(**data)

    @cached_property
    def singleton(self) -> TrackInfo:
        self._singleton = True
        self.media = self.media_formats[0]
        track = self._trackinfo(self.tracks.first)
        if NEW_BEETS:
            track.update(self._common_album)
            track.pop("album", None)
        track.track_id = track.data_url
        return track

    def _album(self, media: MediaInfo) -> AlbumInfo:
        """Return album for the appropriate release format."""
        self.media = media
        include_digi = self.config.get("include_digital_only_tracks")

        tracks = list(self.tracks)
        if not include_digi and self.media.name != DIGI_MEDIA:
            tracks = [t for t in self.tracks if not t.digi_only]

        get_trackinfo = partial(
            self._trackinfo,
            medium=1,
            disctitle=self.disctitle or None,
            medium_total=len(self.tracks),
        )
        album_info = AlbumInfo(
            **self._common,
            **self._common_album,
            artist=self.albumartist,
            album_id=self.album_id,
            mediums=self.mediums,
            albumstatus=self.albumstatus,
            tracks=list(map(get_trackinfo, tracks)),
        )
        for key, val in self.get_fields(["va"]).items():
            setattr(album_info, key, val)
        album_info.album_id = self.media.album_id
        if self.media.name == "Vinyl":
            album_info = self.add_track_alts(album_info, self.comments)
        return album_info

    @cached_property
    def albums(self) -> Iterable[AlbumInfo]:
        """Return album for the appropriate release format."""
        return list(map(self._album, self.media_formats))
