"""Module for parsing bandcamp metadata."""

from __future__ import annotations

import itertools as it
import json
import operator as op
import re
from datetime import date, datetime, timezone
from functools import cached_property, partial
from typing import TYPE_CHECKING, Any
from unicodedata import normalize

from beets import config as beets_config
from beets.autotag.hooks import AlbumInfo, TrackInfo
from pycountry import countries, subdivisions

from .album_name import AlbumName
from .catalognum import Catalognum
from .helpers import Helpers, MediaInfo, cached_patternprop
from .names import Names
from .tracks import Tracks

if TYPE_CHECKING:
    from collections.abc import Iterable


JSONDict = dict[str, Any]

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
VA_ARTIST_COUNT = 4  # this number of artists is replaced with VA name


class Metaguru(Helpers):
    META_PAT = cached_patternprop(r'.*"@id".*')
    LABEL_IN_DESC = cached_patternprop(r"(?<=Label:) *\b[^/,\n]+")
    ARTIST_IN_DESC = cached_patternprop(r"Artists?: *(\b[^\n]+)")
    REMIX_IN_ARTIST = cached_patternprop(r"[(,+]+.+?re?mi?x", re.I)
    NOT_ALPHANUMERIC = cached_patternprop(r"\W")
    HTML_REMOVE_CHARS = ["\u200b", "\u200d", "\u200e", "\u200f", "\u00a0"]

    _singleton = False
    va_name = VA
    media = MediaInfo("", "", "", "")

    meta: JSONDict
    config: JSONDict
    media_formats: list[MediaInfo]
    _tracks: Tracks
    _album_name: AlbumName

    def __init__(self, meta: JSONDict, config: JSONDict | None = None) -> None:
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
            [*self._tracks.artists_and_titles, self.original_albumartist],
        )
        self._album_name = AlbumName(
            names.original_album, self.all_media_comments, names.album_in_titles
        )

    @classmethod
    def from_html(cls, html: str, config: JSONDict | None = None) -> Metaguru:
        for char in cls.HTML_REMOVE_CHARS:
            html = html.replace(char, "")
        try:
            meta = cls.META_PAT.search(html).group()  # type: ignore[union-attr]
        except AttributeError as exc:
            raise AttributeError("Could not find release metadata JSON") from exc

        return cls(json.loads(meta), config)

    @cached_property
    def excluded_fields(self) -> set[str]:
        return set(self.config.get("exclude_extra_fields") or [])

    @cached_property
    def description(self) -> str:
        return self.meta.get("description") or ""

    @cached_property
    def credits(self) -> str:
        return self.meta.get("creditText") or ""

    @property
    def comments(self) -> str | None:
        """Return concatenated release, media descriptions and credits."""
        parts = [self.description]

        normalize = partial(self.NOT_ALPHANUMERIC.sub, "")
        if normalize(self.media.description.lower()) != normalize(
            self.description.lower()
        ):
            parts.append(self.media.description)
        parts.append(self.credits)

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
        if m := self.LABEL_IN_DESC.search(self.all_media_comments):
            return m[0].strip(" '\"")

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
        if m := self.ARTIST_IN_DESC.search(self.all_media_comments):
            aartist = m[1].strip()
        else:
            aartist = self.meta["byArtist"]["name"]

        aartist = ", ".join(map(str.strip, aartist.split(" // ")))
        return self.REMIX_IN_ARTIST.split(aartist)[0].strip()

    @cached_property
    def original_album(self) -> str:
        return self._names.original_album

    @cached_property
    def preliminary_albumartist(self) -> str:
        """Determine and return preliminary album artist to set as default for tracks.

        This property calculates the lead artist based on the original album artist,
        label, and track track collaborators. Since this property gets required before
        track artists are available, it uses the pinciple of elimination to find the
        albumartist candidate.
        """
        aartist = self.original_albumartist
        if self.label != aartist:
            aartist = Helpers.clean_name(aartist)
        elif a := self._album_name.find_artist(self.catalognum):
            aartist = a

        if (
            len(aartists := Helpers.split_artists(aartist)) > 1
            and (main_artists := self._tracks.discard_collaborators(aartists))
            and main_artists != aartists
        ):
            return ", ".join(main_artists)

        return aartist

    @cached_property
    def image(self) -> str:
        image = self.meta.get("image") or ""
        if isinstance(image, list) and isinstance(image[0], str):
            return image[0]
        return image

    @cached_property
    def release_date(self) -> date | None:
        """Parse the datestring that takes the format like below and return date object.

        {"datePublished": "17 Jul 2020 00:00:00 GMT"}.

        If the field is not found, return None.
        """
        if dt := self.meta.get("datePublished") or self.meta.get("dateModified"):
            return (
                datetime.strptime(dt[:11], "%d %b %Y")
                .replace(tzinfo=timezone.utc)
                .date()
            )

        return None

    @cached_property
    def albumstatus(self) -> str:
        reldate = self.release_date
        today = datetime.now(tz=timezone.utc).date()
        return "Official" if reldate and reldate <= today else "Promotional"

    @property
    def disctitle(self) -> str | None:
        """Return medium's disc title if found."""
        return self.media.disctitle or None

    @staticmethod
    def get_mediums(track_infos: list[TrackInfo]) -> int:
        """Get the count of discs / mediums for this release format."""
        return max((t.medium or 0 for t in track_infos), default=0)

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
        """Return parsed tracks."""
        self._tracks.fix_track_artists(self.preliminary_albumartist)
        return self._tracks

    @cached_property
    def unique_artists(self) -> list[str]:
        """Return all unique artists in the release ignoring differences in case."""
        artists = self.split_artists(self._tracks.artists)
        return artists[:1] if len(set(map(str.lower, artists))) == 1 else artists

    @cached_property
    def track_count(self) -> int:
        return len(self._tracks)

    @cached_property
    def albumartist(self) -> str:
        """Take into account the release contents and return the actual albumartist.

        If we have one track, return the artist of that track.
        If we have more than VA_ARTIST_COUNT artists, return the VA name.

        Compare the original albumartist with artists found in the tracks:
        * if we have a single albumartist, and it's one of the track lead artists,
          return it ignoring the rest of track artists
        * if we have more than one albumartist, and they are all track lead artists,
          return them in the original format
        * otherwise, join track lead artists with a comma and return them.

        Note: ft artists are not included.
        """
        if self.track_count == 1:
            return self.remove_ft(self.tracks.first.artist)

        if self.va:
            return self.va_name

        aartist = self.preliminary_albumartist
        if aartist and (set(self.split_artists(aartist)) <= set(self.unique_artists)):
            return self.remove_ft(aartist) if "remix" in aartist else aartist
        if len(self.tracks.original_artists) == 1:
            return self.tracks.original_artists[0]

        def normalize(artists: Iterable[str]) -> tuple[str, ...]:
            return tuple(sorted(set(map(str.lower, artists))))

        aartists = normalize(self.split_artists(aartist, force=True))
        all_artists_sets = {
            normalize(self._tracks.lead_artists),
            normalize(self.unique_artists),
        }
        all_artists = {a for artists in all_artists_sets for a in artists}
        if (
            not self.tracks.lead_artists
            # if the release specifies a single albumartist, respect it as long as
            # that's one of the track artists
            or (len(aartists) == 1 and next(iter(aartists)) in all_artists)
            or (aartists in all_artists_sets)
        ):
            return aartist

        return ", ".join(sorted(self.tracks.lead_artists))

    @cached_property
    def album_name(self) -> str:
        artists = []
        if self.original_albumartist != self.label:
            artists.append(self.original_albumartist)

        return self._album_name.get(
            self.catalognum,
            [*artists, *self.tracks.original_artists],
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
        sentences = [s.strip() for s in text.lower().split(". ")]

        word_pat = re.compile(rf"(?<!-)\b{word}(\b|\.)", re.I)
        in_catnum = re.compile(rf"{word}\d", re.I)
        release_ref = re.compile(
            rf"\b((this|with|present|deliver|new)[\w\s,'-]*?|the|track|full|first) {word}\b",  # noqa: E501
            re.I,
        )
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
            " / " in self.album_name
            and len(self.tracks.artists) == AlbumName.SPLIT_RELEASE_ARTIST_COUNT
        )

    @cached_property
    def is_comp(self) -> bool:
        """Return whether the release is a compilation."""
        return (
            self._album_name.mentions_compilation
            or self._search_albumtype("compilation")
            or (
                len(self.tracks.lead_artists) >= VA_ARTIST_COUNT
                and self.track_count > VA_ARTIST_COUNT
            )
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
        return "compilation" if self.is_comp else "album"

    @cached_property
    def albumtypes(self) -> list[str]:
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

        if sum(bool(t.remix and t.remix.valid) for t in self._tracks) >= max(
            self.track_count - 1, 1
        ):
            albumtypes.add("remix")

        return sorted(albumtypes)

    @cached_property
    def va(self) -> bool:
        return len(self.tracks.lead_artists) >= VA_ARTIST_COUNT

    @cached_property
    def style(self) -> str | None:
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
    def genre(self) -> str | None:
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

    @cached_property
    def artists(self) -> list[str]:
        artists = self.split_artists(self.albumartist, force=True)
        if m := self.FT_PAT.search(self.albumartist):
            artists.append(m["ft_artist"])

        return artists

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
            "artists",
        ]
        common_data.update(self.get_fields(fields))
        if reldate := self.release_date:
            common_data.update(self.get_fields(["year", "month", "day"], reldate))

        return common_data

    def _trackinfo(self, data: dict[str, Any], **kwargs: Any) -> TrackInfo:
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
        track = self._trackinfo(self.tracks.first.info, medium=None)
        track.update(self._common_album)
        track.album = None
        track.track_id = track.data_url
        if not track.title:
            track.title = self.catalognum
        return self.check_list_fields(track)

    def get_media_album(self, media: MediaInfo) -> AlbumInfo:
        """Return album for the appropriate release format."""
        self.media = media

        tracks = self.tracks.for_media(
            self.media.name,
            self.comments or "",
            bool(self.config.get("include_digital_only_tracks")),
        )
        track_infos = [self._trackinfo(t, disctitle=self.disctitle) for t in tracks]
        album_info = AlbumInfo(
            **self._common,
            **self._common_album,
            artist=self.albumartist,
            album_id=self.album_id,
            mediums=self.get_mediums(track_infos),
            albumstatus=self.albumstatus,
            tracks=track_infos,
        )
        for key, val in self.get_fields(["va"]).items():
            setattr(album_info, key, val)
        album_info.album_id = self.media.album_id
        return self.check_list_fields(album_info)

    @cached_property
    def albums(self) -> list[AlbumInfo]:
        """Return album for the appropriate release format."""
        return list(map(self.get_media_album, self.media_formats))
