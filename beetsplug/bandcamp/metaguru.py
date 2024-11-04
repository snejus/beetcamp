"""Module for parsing bandcamp metadata."""

import itertools as it
import json
import operator as op
import re
from datetime import date, datetime
from functools import cached_property, partial
from typing import Any, Dict, Iterable, List, Optional, Set
from unicodedata import normalize

from beets import config as beets_config
from beets.autotag.hooks import AlbumInfo, TrackInfo
from pycountry import countries, subdivisions

from .album_name import AlbumName
from .catalognum import Catalognum
from .helpers import PATTERNS, Helpers, MediaInfo
from .names import Names
from .track import Track
from .tracks import Tracks

JSONDict = Dict[str, Any]

COUNTRY_OVERRIDES = {
    "Russia": "RU",  # pycountry: Russian Federation
    "The Netherlands": "NL",  # pycountry: Netherlands
    "UK": "GB",  # pycountry: Great Britain
    "D.C.": "US",
    "South Korea": "KR",  # pycountry: Korea, Republic of
    "Turkey": "TR",  # pycountry: only handles Türkiye
}
DATA_SOURCE = "bandcamp"
WORLDWIDE = "XW"
DIGI_MEDIA = "Digital Media"
VA = "Various Artists"


class Metaguru(Helpers):
    HTML_REMOVE_CHARS = ["\u200b", "\u00a0"]
    _singleton = False
    va_name = VA
    media = MediaInfo("", "", "", "")

    meta: JSONDict
    config: JSONDict
    media_formats: List[MediaInfo]
    _tracks: Tracks
    _album_name: AlbumName

    def __init__(self, meta: JSONDict, config: Optional[JSONDict] = None) -> None:
        self.meta = meta
        self.media_formats = self.get_media_formats(
            (meta.get("inAlbum") or meta).get("albumRelease") or []
        )
        if self.media_formats:
            self.media = self.media_formats[0]
        self.config = config or {}
        self.va_name = beets_config["va_name"].as_str() or self.va_name
        names = Names(meta, self.original_albumartist)
        names.resolve()
        self._names = names
        self._tracks = Tracks.from_names(names)
        self._catalognum = Catalognum(
            f"{self.description}\n{self.credits}".replace("\r", ""),
            names.original_album,
            names.label,
            self._tracks.artists_and_titles,
        )
        self._album_name = AlbumName(
            names.original_album, self.all_media_comments, names.album_in_titles
        )

    @classmethod
    def from_html(cls, html: str, config: Optional[JSONDict] = None) -> "Metaguru":
        for char in cls.HTML_REMOVE_CHARS:
            html = html.replace(char, "")
        try:
            meta = re.search(PATTERNS["meta"], html).group()  # type: ignore[union-attr]
        except AttributeError as exc:
            raise AttributeError("Could not find release metadata JSON") from exc
        else:
            return cls(json.loads(meta), config)

    @cached_property
    def excluded_fields(self) -> Set[str]:
        return set(self.config.get("exclude_extra_fields") or [])

    @cached_property
    def description(self) -> str:
        return self.meta.get("description") or ""

    @cached_property
    def credits(self) -> str:
        return self.meta.get("creditText") or ""

    @property
    def comments(self) -> Optional[str]:
        """Return concatenated release, media descriptions and credits."""
        parts = [self.description, self.media.description, self.credits]
        sep = self.config["comments_separator"]
        return sep.join(filter(None, parts)).replace("\r", "") or None

    @cached_property
    def disctitles(self) -> str:
        return " ".join([m.disctitle for m in self.media_formats if m.disctitle])

    @cached_property
    def only_media_comments(self) -> str:
        return "\n".join([
            self.disctitles,
            *[m.description for m in self.media_formats],
        ])

    @cached_property
    def all_media_comments(self) -> str:
        return "\n".join([self.only_media_comments, self.comments or ""])

    @cached_property
    def label(self) -> str:
        m = re.search(r"Label:([^/,\n]+)", self.all_media_comments)
        if m:
            return m.expand(r"\1").strip(" '\"")

        return self._names.label

    @cached_property
    def album_id(self) -> str:
        return self.meta.get("@id") or ""

    @cached_property
    def artist_id(self) -> str:
        try:
            return self.meta["byArtist"]["@id"]  # type: ignore [no-any-return]
        except KeyError:
            return self.meta["publisher"]["@id"]  # type: ignore [no-any-return]

    @cached_property
    def original_albumartist(self) -> str:
        m = re.search(r"Artists?:([^\n]+)", self.all_media_comments)
        aartist = m.group(1).strip() if m else self.meta["byArtist"]["name"]
        aartist = ", ".join(map(str.strip, aartist.split(" // ")))
        return re.split(r"[(,][^(,]{1,30}remix", aartist, flags=re.I)[0].strip()

    @cached_property
    def original_album(self) -> str:
        return self._names.original_album

    @cached_property
    def bandcamp_albumartist(self) -> str:
        """Return the official release albumartist.
        It is correct in half of the cases. In others, we usually find the label name.
        """
        year_range = re.compile(r"20[12]\d - 20[12]\d")
        aartist = self.original_albumartist
        if self.label == aartist and not year_range.match(self.original_album):
            split = AlbumName.clean(self.original_album, [self.catalognum]).split(" - ")
            if len(split) > 1:
                aartist = split[0]

        aartists = Helpers.split_artists(aartist)
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
        image = self.meta.get("image") or ""
        if isinstance(image, list) and isinstance(image[0], str):
            return image[0]
        return image

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
        return self.media.disctitle

    @property
    def mediums(self) -> int:
        return self.media.medium_count

    @property
    def catalognum(self) -> str:
        """Return the first found catalogue number."""
        return (
            self._names.catalognum
            or self._catalognum.get(f"{self.media.disctitle}\n{self.media.description}")
            or ""
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
        self._tracks.post_process(self.bandcamp_albumartist)
        return self._tracks

    @cached_property
    def unique_artists(self) -> List[str]:
        return self.split_artists(self._tracks.artists)

    @cached_property
    def track_count(self) -> int:
        return len(self._tracks)

    @cached_property
    def albumartist(self) -> str:
        """Take into account the release contents and return the actual albumartist.
        * 'Various Artists' (or `va_name` configuration option) for a compilation release
        """
        if self.va:
            return self.va_name

        if self.track_count == 1:
            return self.tracks.first.artist

        aartist = self.original_albumartist
        if self.unique_artists:
            aartist = ", ".join(sorted(self.unique_artists))

        return aartist

    @cached_property
    def album_name(self) -> str:
        return self._album_name.get(
            self.catalognum,
            self.tracks.original_artists,
            self.tracks.artists,
            self.label,
        )

    def _search_albumtype(self, word: str) -> bool:
        """Return whether the given word (ep or lp) matches the release albumtype.

        True when one of the following conditions is met:
        * if {word}[0-9] is found in the catalognum
        * if [0-9]?{word} is found in the album name or any disctitle
        * if {word} is preceded by 'this ...' or 'the' in a sentence in the release or
          or any media description, like 'this EP'
        * if {word} and the album_name are found in the same sentence in the release or
          any media description.
        """
        text = " ".join(self.all_media_comments.splitlines())
        sentences = re.split(r"[.]\s+", text.lower())

        word_pat = re.compile(rf"(?<!-)\b{word}(\b|\.)", re.I)
        in_catnum = re.compile(rf"{word}\d", re.I)
        release_ref = re.compile(rf"\b(this[\w\s]*?|the) {word}\b", re.I)
        album_name = self.album_name.lower()

        media_word_pat = re.compile(rf"(vinyl |x|[0-5]){word}\b", re.I)
        return bool(
            media_word_pat.search(self.only_media_comments)
            or in_catnum.search(self.catalognum)
            or word_pat.search(f"{album_name} {self.disctitles}")
            or in_catnum.search(text)
            or any(
                release_ref.search(s) or (word_pat.search(s) and album_name in s)
                for s in sentences
            )
        )

    @cached_property
    def is_singleton(self) -> bool:
        return self._singleton or self.track_count == 1

    @cached_property
    def is_single_album(self) -> bool:
        return self.track_count > 1 and (
            len({t.title_without_remix for t in self.tracks}) == 1
        )

    @cached_property
    def is_lp(self) -> bool:
        """Return whether the release is an LP."""
        return self._search_albumtype("lp")

    @cached_property
    def is_ep(self) -> bool:
        """Return whether the release is an EP."""
        return self._search_albumtype(r"e\.?p") or (
            " / " in self.album_name and len(self.tracks.artists) == 2
        )

    @cached_property
    def is_comp(self) -> bool:
        """Return whether the release is a compilation."""

        def first_one(artist: str) -> str:
            return PATTERNS["split_artists"].split(artist.replace(" & ", ", "))[0]

        truly_unique = set(map(first_one, self.tracks.artists))
        return (
            self._album_name.mentions_compilation
            or self._search_albumtype("compilation")
            or (len(truly_unique) > 3 and self.track_count > 4)
        )

    @cached_property
    def albumtype(self) -> str:
        if self.is_singleton:
            return "single"
        if self.is_lp:
            return "album"
        if self.is_ep:
            return "ep"
        if self.is_single_album:
            return "single"
        if self.is_comp:
            return "compilation"

        return "album"

    @cached_property
    def albumtypes(self) -> List[str]:
        albumtypes = {self.albumtype}
        if self.is_comp:
            if self.albumtype == "ep":
                albumtypes.add("compilation")
            else:
                albumtypes.add("album")
        if not self.is_singleton and self.is_lp:
            albumtypes.add("lp")
        if self.is_single_album:
            albumtypes.add("single")

        if self.albumtype == "single" and self.track_count > 1:
            albumtypes.add("album")

        for word in ["remix", "rmx", "edits", "live", "soundtrack"]:
            if word in self.original_album.lower():
                albumtypes.add(word.replace("rmx", "remix").replace("edits", "remix"))

        if len(self.tracks.remixers) >= max(self.track_count - 1, 1):
            albumtypes.add("remix")

        return sorted(albumtypes)

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
        kws: Iterable[str] = map(str.lower, self.meta.get("keywords", []))
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

    @property
    def _common(self) -> JSONDict:
        return {
            "album": self.album_name,
            "artist_id": self.artist_id,
            "artists_credit": [],  # TODO: implement
            "artists_ids": [self.artist_id],
            "artists_sort": [],  # TODO: implement
            "data_source": DATA_SOURCE,
            "data_url": self.album_id,
            "media": self.media.name,
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
        common_data: JSONDict = dict.fromkeys(["barcode", "release_group_title"])
        fields = [
            "albumtype",
            "albumtypes",
            "catalognum",
            "comments",
            "country",
            "genre",
            "label",
            "style",
        ]
        common_data.update(self.get_fields(fields))
        reldate = self.release_date
        if reldate:
            common_data.update(self.get_fields(["year", "month", "day"], reldate))
        common_data["artists"] = self.albumartist.split(", ")

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
        for field in set(data.keys()) & self.excluded_fields:
            data.pop(field)

        return TrackInfo(**data)

    @cached_property
    def singleton(self) -> TrackInfo:
        self._singleton = True
        self.media = self.media_formats[0]
        track = self._trackinfo(self.tracks.first)
        track.update(self._common_album)
        track.album = None
        track.track_id = track.data_url
        return self.check_list_fields(track)

    def get_media_album(self, media: MediaInfo) -> AlbumInfo:
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
            medium_total=self.track_count,
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
            album_info = self.add_track_alts(album_info, self.comments or "")
        return self.check_list_fields(album_info)

    @cached_property
    def albums(self) -> List[AlbumInfo]:
        """Return album for the appropriate release format."""
        return list(map(self.get_media_album, self.media_formats))
