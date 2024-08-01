from __future__ import annotations

import re
from datetime import datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal
from unicodedata import normalize

from beets.autotag.hooks import AlbumInfo, TrackInfo
from pycountry import countries, subdivisions
from pydantic import BaseModel, Field, OnErrorOmit

from .helpers import Helpers
from .metaguru import COUNTRY_OVERRIDES, DIGI_MEDIA
from .track import Track

if TYPE_CHECKING:
    from beets import IncludeLazyConfig

JSONDict = dict[str, Any]

SINGLE_TRACK_MAX_LENGTH = 2000


def get_country(loc: str) -> str:
    try:
        name = normalize("NFKD", loc).encode("ascii", "ignore").decode()
        return (
            COUNTRY_OVERRIDES.get(name)
            or getattr(countries.get(name=name, default=object), "alpha_2", None)
            or subdivisions.lookup(name).country_code
        )
    except (ValueError, LookupError):
        return "XW"


class ParsedTrack(BaseModel):
    album: str | None = None
    artist: str | None = None
    catalognum: str | None = None
    title: str | None = None
    track: int | None = None
    track_alt: str | None = None
    live: bool = False

    @cached_property
    def data(self) -> JSONDict:
        return {k: v for k, v in self.dict().items() if k != "live"}


def parse_title(source: str, title: str, artist: str) -> ParsedTrack:
    delim = r"([-&|x]|w/|__)"
    _delim = rf" {delim} "

    index_pat = r"(?P<full_index>[\[# 0]+(?P<index>[\d.]+\b)\]?)"
    artist_pat = rf"(?P<artist>.+(?!{delim}))"
    album_pat = rf"#*(?P<album>.+(?!{delim}))"
    label_pat = r"(?P<full_label> \[(?P<label>[^\]]+)\])"

    data: JSONDict = {"artist": source, "title": title}
    if m := re.search(r" [^ ]*live[^ ]*", data["title"], re.I):
        title = data["title"] = data["title"].replace(m.group(0), "")
        data["live"] = True
    for pat in (
        # discast
        rf"^{album_pat}{_delim}{index_pat}{_delim}{artist_pat}{delim}.*$",
        rf"^{album_pat}{_delim}{index_pat}{_delim}{artist_pat}$",
        # DISSENTIENT.SPACE
        rf"^{index_pat}{_delim}{artist_pat}{delim}$",
        # Ismcast
        rf"^{album_pat}{index_pat}{_delim}{artist_pat}",
        # DUSKCAST, POSSESSION, DETECT
        rf"^{album_pat}{index_pat}{_delim}{artist_pat}({delim}.*$|{label_pat})",
        # Axxidcast
        rf"^{album_pat}{_delim}{artist_pat}{_delim}(Live )?{index_pat}$",
        # CRUDE MIX
        rf"^{album_pat} {index_pat}{_delim}{artist_pat}$",
        # SACHSENTRANCE PODCAST
        rf"^{artist_pat}{_delim}{album_pat} {index_pat}$",
        # PURE Guest
        rf"^{album_pat} Guest[.]{index_pat} {artist_pat}$",
    ):
        # print(pat)
        m = re.search(pat, title)
        if m:
            mdata = m.groupdict()
            data.update(mdata)
            full_index = data.pop("full_index", "")
            if full_index and title.startswith(full_index):
                title = title.split(full_index)[1].strip(" -|")
            full_label = data.pop("full_label", "")
            if full_label:
                title = title.replace(full_label, "")
            data["title"] = title
            break
    else:
        data = {"@id": "", "name": title, "byArtist": {"name": artist}}
        track = Track.make(data)
        return ParsedTrack(**{**track.info, "album": ""})

    index = data.pop("index", "")
    if "." not in index:
        index = index.lstrip("0")
    data["track"] = index

    title, artist = data["title"], data["artist"]
    if not title:
        data["title"] = f"{data['album']} {data['track']}"
    elif title.startswith(artist):
        data["title"] = re.sub(rf"{artist}{_delim}", "", title)

    data["artist"] = ", ".join(Helpers.split_artists([data["artist"]]))

    return ParsedTrack(**data)


class SCEntity(BaseModel):
    id: int  # 327465714
    kind: Literal["user", "track", "playlist"]  # "user"
    last_modified: datetime  # "2024-02-14T00:17:48Z"
    permalink_url: str  # "https://soundcloud.com/aexhy"
    uri: str  # "https://api.soundcloud.com/users/327465714"


class Visual(BaseModel):
    urn: str  # "soundcloud:visuals:206653239"
    entry_time: int  # 0
    visual_url: str  # "https://i1.sndcdn.com/visuals-000327465714-MWYRGR-original.jpg"


class Visuals(BaseModel):
    urn: str  # "soundcloud:users:327465714"
    enabled: bool  # true
    visuals: list[Visual]
    tracking: bool | None  # null


class BasicUser(SCEntity):
    avatar_url: str  # "https://i1.sndcdn.com/avatars-VdiyiKIAvTrN0eFz-bPJOIg-large.jpg"
    badges: dict[str, bool]  # {"pro": false, "pro_unlimited": true, "verified": false}
    city: str | None  # "Berlin"
    country_code: str | None  # "DE"
    first_name: str  # ""
    followers_count: int  # 5982
    full_name: str  # ""
    last_name: str  # ""
    permalink: str  # "aexhy"
    username: str  # "Aexhy"
    verified: bool  # false
    station_urn: str  # "soundcloud:system-playlists:artist-stations:327465714"
    station_permalink: str  # "artist-stations:327465714"
    urn: str  # "soundcloud:users:327465714"

    @property
    def country(self) -> str | None:
        location = self.country_code or self.city

        if not location:
            return None

        if len(location) == 2:
            return location

        return get_country(location)


class User(BasicUser):
    comments_count: int  # 0
    created_at: datetime  # "2017-08-21T06:37:47Z"
    creator_subscriptions: list[
        JSONDict
    ]  # [{"product": {"id": "creator-pro-unlimited"}}]
    creator_subscription: JSONDict  # {"product": {"id": "creator-pro-unlimited"}}
    # "✧ ☆ H<3core-Poet ☆ ✧ \n\n🌎booking via paolo@moonagency.xyz\n\nSYNDIKAET\nASYLUM \nDEESTRICTED \nENIGMA \nEHRENKLUB\nPARA//E/ \nPUBLIC ENERGY\n240KMH\n\n\n\nHigh in the ethereal skies, a majestic crystal castle stands, its translucent walls reflecting a kaleidoscope of colors. Within its walls, a hidden realm of enchantment unfolds, where whimsical fairies dance on shimmering petals, weaving dreams with their delicate wings.\nThis fairy world sparkles with magic, where laughter and wonder embrace every corner, and imagination reigns supreme.\n\nAexhy has been a long time in the scene as a dj which motivated him to push further and start his career as a producer. In his Productions and in his sets you can clearly notice what Aexhy is made of. Playfully guiding you through all styles which inspire him, aexhy pushes boundaries and combines everything in a playful style to suprise you each minute. Constantly rising energy and letting it drop just to change to another style to capture your emotions and make you feel something.\n__________________________________✘✘✘_________________\nalso performing as:\n\"Space Cowboys\" with Trancemaster Krause\n\"SAEXHY\" with SACID"
    description: str | None
    followings_count: int  # 524
    groups_count: int  # 0
    likes_count: int | None  # 1472
    playlist_likes_count: int  # 91
    playlist_count: int  # 12
    reposts_count: int | None  # null
    track_count: int  # 83
    visuals: Visuals | None

    @property
    def visual_url(self) -> str | None:
        return self.visuals.visuals[0].visual_url if self.visuals else None


class SCMedia(SCEntity):
    DATA_SOURCE: Final[Literal["soundcloud"]] = "soundcloud"

    info_type: ClassVar[type[TrackInfo | AlbumInfo]]

    artwork_url: (
        str | None  # "https://i1.sndcdn.com/artworks-1JYcoqeTzmZQOzYk-5ZSI7g-large.jpg"
    )
    created_at: datetime  # "2022-09-09T22:09:09Z"
    description: str  # ""
    display_date: datetime  # "2022-09-09T22:09:09Z"
    duration: int  # 173610
    embeddable_by: str  # "all"
    label_name: str | None  # null
    license: str  # "all-rights-reserved"
    likes_count: int | None  # 115
    permalink: str  # "02-aexhy-x-dj-traytex-glasversteck-fallen-shrine-nxc"
    public: bool  # true
    purchase_title: str | None  # null
    purchase_url: str | None  # null
    release_date: str | None  # null
    reposts_count: int  # 4
    secret_token: str | None  # null
    sharing: str  # "public"
    tag_list: str  # ""
    title: str  # "02. Aexhy X Dj Traytex - Glasversteck (Fallen Shrine nxc)"
    user: BasicUser
    user_id: int  # 327465714

    @cached_property
    def label(self) -> str:
        return (self.label_name or self.user.username).strip(" /")

    @cached_property
    def artist(self) -> str:
        return self.user.username

    @property
    def data(self) -> JSONDict:
        return {
            "artist": self.artist,
            "artist_id": self.user.urn,
            "artwork_url": (self.artwork_url or "").replace("-large", "-t500x500"),
            "comments": self.description if self.description else None,
            "country": self.user.country,
            "data_source": self.DATA_SOURCE,
            "day": self.display_date.day,
            "data_url": self.permalink_url,
            "label": self.label,
            "media": DIGI_MEDIA,
            "month": self.display_date.month,
            "year": self.display_date.year,
        }

    @cached_property
    def info(self) -> AlbumInfo | TrackInfo:
        return self.info_type(**self.data)


class PlaylistTrack(SCMedia):
    info_type = TrackInfo

    caption: str | None  # null
    commentable: bool  # true
    comment_count: int | None  # 4
    downloadable: bool  # false
    download_count: int | None  # 0
    full_duration: int  # 173610
    has_downloads_left: bool  # false
    media: JSONDict
    monetization_model: str  # "NOT_APPLICABLE"
    playback_count: int | None  # 5202
    policy: str  # "ALLOW"
    publisher_metadata: (
        JSONDict | None
    )  # {"id": int  # 1341013456, "urn": str  # "soundcloud:tracks:1341013456", "contains_music": bool  # true}
    state: str  # "finished"
    station_permalink: str  # "track-stations:1341013456"
    station_urn: str  # "soundcloud:system-playlists:track-stations:1341013456"
    streamable: bool  # true
    track_authorization: str  # "eyJ0eXAiOiJKV1QiLCJ..."
    # track_format: str | None  # "single-track"
    urn: str  # "soundcloud:tracks:1341013438"
    visuals: Visuals | None  # null
    waveform_url: str  # "https://wave.sndcdn.com/6FiJyRHgHJQ1_m.json"

    @cached_property
    def parsed_track(self) -> ParsedTrack:
        return parse_title(self.label, self.title, self.artist)

    @cached_property
    def length(self) -> int:
        return round(self.duration / 1000) - 1

    @property
    def data(self) -> JSONDict:
        return {
            **super().data,
            "title": self.title,
            **self.parsed_track.data,
            "isrc": (self.publisher_metadata or {}).get("isrc"),
            "length": self.length,
            "track_id": self.permalink_url,
        }


class ReleaseMixin(BaseModel):
    original_genre: str = Field(validation_alias="genre")  # ""
    config: JSONDict

    @cached_property
    def albumtypes(self) -> list[str]:
        return [self.albumtype]

    @cached_property
    def genre(self) -> str:
        keywords = [
            item.casefold().replace("\\", "")
            for item in re.split(r" ?[-,/&] ", self.original_genre)
        ]
        return ", ".join(Helpers.get_genre(keywords, self.config, ""))

    @property
    def data(self) -> JSONDict:
        return {
            **super().data,
            "albumstatus": "Official",
            "albumtype": self.albumtype,
            "albumtypes": self.albumtypes,
            "city": self.user.city,
            "genre": self.genre,
        }


class MainTrack(ReleaseMixin, PlaylistTrack):
    user: User

    @cached_property
    def albumtype(self) -> str:
        return "single" if self.length < SINGLE_TRACK_MAX_LENGTH else "broadcast"

    @cached_property
    def albumtypes(self) -> list[str]:
        albumtypes = super().albumtypes
        if self.albumtype == "broadcast":
            albumtypes.append("dj-mix")

        if self.parsed_track.live:
            albumtypes.append("live")

        return albumtypes

    @cached_property
    def albumartist(self) -> str:
        if not self.parsed_track.album:
            return ""

        return self.label or self.artist

    @property
    def data(self) -> JSONDict:
        return {
            **super().data,
            "album": self.parsed_track.album,
            "albumartist": self.albumartist,
            "visual_url": self.user.visual_url,
        }


class Playlist(ReleaseMixin, SCMedia):
    info_type = AlbumInfo

    is_album: bool  # true
    managed_by_feeds: bool  # false
    published_at: datetime | None  # "2022-09-09T22:10:03Z"
    set_type: Literal["album", "compilation"]  # "album"
    tracks: list[OnErrorOmit[PlaylistTrack]]
    track_count: int  # 5
    url: str  # "/aexhy/sets/fallen-shrine-s-bday-present-4"
    user: User

    @cached_property
    def album(self) -> str:
        return self.title

    @cached_property
    def album_id(self) -> str:
        return self.permalink_url

    @cached_property
    def albumtype(self) -> str:
        return "album" if len({t.artist for t in self.tracks}) == 1 else self.set_type

    @property
    def data(self) -> JSONDict:
        tracks = [t.info for t in self.tracks]
        for idx, track in enumerate(tracks, 1):
            track.index = track.medium_index = idx
            track.medium_total = self.track_count
            track.album = self.album
            track.album_id = self.album_id

        return {
            **super().data,
            "album": self.album,
            "album_id": self.album_id,
            "tracks": tracks,
            "medium_total": self.track_count,
        }


def get_soundcloud_track(data: JSONDict, config: IncludeLazyConfig) -> TrackInfo:
    return MainTrack(**data, config=config).info


def get_soundcloud_album(data: JSONDict, config: IncludeLazyConfig) -> AlbumInfo:
    return Playlist(**data, config=config).info
