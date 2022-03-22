"""Module for parsing bandcamp metadata."""
import itertools as it
import json
import operator as op
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from functools import partial
from html import unescape
from typing import Any, Dict, Iterable, List, Optional, Set
from unicodedata import normalize

from beets import config as beets_config
from beets.autotag.hooks import AlbumInfo, TrackInfo
from pkg_resources import get_distribution, parse_version
from pycountry import countries, subdivisions

from ._helpers import MEDIA_MAP, PATTERNS, Helpers

if sys.version_info.minor > 7:
    from functools import cached_property
else:
    from cached_property import cached_property

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
VA = "Various Artists"


def urlify(pretty_string: str) -> str:
    """Transform a string into bandcamp url."""
    name = pretty_string.lower().replace("'", "").replace(".", "")
    return re.sub("--+", "-", re.sub(r"\W", "-", name, flags=re.ASCII)).strip("-")


class Metaguru(Helpers):
    meta: JSONDict
    config: JSONDict
    _singleton = False
    va_name: str = VA

    def __init__(self, meta: JSONDict, config: Optional[JSONDict] = None) -> None:
        self.meta = meta
        self.config = config or {}
        self.va_name = beets_config["va_name"].as_str() or self.va_name

    @classmethod
    def from_html(cls, html: str, config: JSONDict = None) -> "Metaguru":
        try:
            meta = json.loads(re.search(PATTERNS["meta"], html).group())  # type: ignore
            meta["tracks"] = list(map(unescape, re.findall(r"^[0-9]+[.] .*", html, re.M)))
        except AttributeError as exc:
            raise AttributeError("Could not find release metadata JSON") from exc

        return cls(meta, config)

    @cached_property
    def excluded_fields(self) -> Set[str]:
        return set(self.config.get("excluded_fields") or [])

    @cached_property
    def comments(self) -> str:
        """Return release, media descriptions and credits separated by
        the configured separator string.
        """
        parts = [self.meta.get("description")]
        media_desc = self.media.get("description")
        if media_desc and not media_desc.startswith("Includes high-quality"):
            parts.append(media_desc)

        parts.append(self.meta.get("creditText"))
        sep = self.config["comments_separator"]
        return sep.join(filter(op.truth, parts)).replace("\r", "")

    @cached_property
    def all_media_comments(self) -> str:
        get_desc = op.methodcaller("get", "description", "")
        return "\n".join(
            [*map(get_desc, self.meta.get("albumRelease", {})), self.comments]
        )

    @cached_property
    def official_album_name(self) -> str:
        match = re.search(
            r"(Title: ?|Album(:|/Single) )([^\n:]+)(\n|$)", self.all_media_comments
        )
        return match.expand(r"\3").strip() if match else ""

    @cached_property
    def album_name(self) -> str:
        return self.official_album_name or self.meta["name"]

    @cached_property
    def label(self) -> str:
        match = re.search(r"Label:([^/,\n]+)", self.all_media_comments)
        if match:
            return match.expand(r"\1").strip(" '\"")

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
    def raw_albumartist(self) -> str:
        match = re.search(r"Artists?:([^\n]+)", self.all_media_comments)
        return match.expand(r"\1").strip() if match else ""

    @cached_property
    def official_albumartist(self) -> str:
        return self.meta["byArtist"]["name"]

    @cached_property
    def bandcamp_albumartist(self) -> str:
        """Return the official release albumartist.
        It is correct in half of the cases. In others, we usually find the label name.
        """
        aartist = self.raw_albumartist or self.official_albumartist
        if self.label == aartist:
            aartist = self.parse_track_name(self.album_name).get("artist") or aartist

        aartists = Helpers.split_artists([aartist])

        def not_remixer(x: str) -> bool:
            return not any(map(lambda y: y in self.remixers, {x, *x.split(" & ")}))

        valid = list(filter(not_remixer, aartists))
        if (
            len(aartists) == 1
            or len(valid) == len(aartists)
            and not len(self.raw_artists) > 4
        ):
            return aartist
        return ", ".join(valid)

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
    def media(self) -> JSONDict:
        media = self.meta.get("albumRelease", [{}])[0]
        try:
            media_index = self._get_media_reference(self.meta)
        except (KeyError, AttributeError):
            pass
        else:
            # if preference is given and the format is available, use it
            for preference in (self.config.get("preferred_media") or "").split(","):
                if preference in media_index:
                    media = media_index[preference]
                    break
        return media

    @cached_property
    def media_name(self) -> str:
        """Return the human-readable version of the media format."""
        return MEDIA_MAP.get(self.media.get("musicReleaseFormat", ""), DIGI_MEDIA)

    @cached_property
    def disctitle(self) -> str:
        """Return medium's disc title if found."""
        return "" if self.media_name == DIGI_MEDIA else self.media.get("name", "")

    @cached_property
    def mediums(self) -> int:
        return self.get_vinyl_count(self.disctitle) if self.media_name == "Vinyl" else 1

    @cached_property
    def catalognum(self) -> str:
        artists = [self.official_albumartist]
        if not self._singleton or len(self.raw_artists) > 1:
            artists.extend(self.raw_artists)
        return self.parse_catalognum(
            self.meta["name"],
            self.disctitle,
            self.all_media_comments,
            self.label,
            artists,
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
    def json_tracks(self) -> List[JSONDict]:
        try:
            return self.meta["track"]["itemListElement"]
        except KeyError:
            return [{"item": self.meta, "position": 1}]

    @cached_property
    def tracks(self) -> List[JSONDict]:
        """Parse relevant details from the tracks' JSON."""
        names = self.track_names
        delim = self.track_delimiter(names)
        names = self.clean_track_names(names, self.catalognum)
        tracks = []
        for item, position in map(op.itemgetter("item", "position"), self.json_tracks):
            initial_name = names[position - 1]
            name = self.clear_digi_only(initial_name)
            track: JSONDict = defaultdict(
                str,
                digi_only=name != initial_name,
                index=position,
                track_id=item.get("@id"),
                length=self.get_duration(item) or None,
                **self.parse_track_name(self.clean_name(name), delim),
            )
            lyrics = item.get("recordingOf", {}).get("lyrics", {}).get("text")
            if lyrics:
                track["lyrics"] = lyrics.replace("\r", "")
            tracks.append(track)

        return self.adjust_artists(tracks, self.bandcamp_albumartist)

    @cached_property
    def remixers(self) -> str:
        titles = " ".join(self.track_names)
        names = re.finditer(r"\( *([^)]+) (?i:(re)?mix|edit)\)", titles, re.I)
        ft = re.finditer(r"[( ](f(ea)?t[.]? [^()]+)[)]?", titles, re.I)
        return " ".join(set(map(lambda x: x.expand(r"\1"), it.chain(names, ft))))

    @cached_property
    def track_artists(self) -> List[str]:
        return list(filter(op.truth, map(lambda x: x.get("artist"), self.tracks)))

    @cached_property
    def unique_artists(self) -> List[str]:
        return self.split_artists(self.track_artists)

    @cached_property
    def track_names(self) -> List[str]:
        raw_tracks = self.meta.get("tracks")
        if raw_tracks:
            return list(map(lambda x: x.split(". ", maxsplit=1)[1], raw_tracks))
        return list(map(lambda x: x.get("item").get("name") or "", self.json_tracks))

    @cached_property
    def raw_artists(self) -> List[str]:
        def only_artist(name: str) -> str:
            return re.sub(r" - .*", "", PATTERNS["track_alt"].sub("", name))

        artists = list(map(only_artist, filter(lambda x: " - " in x, self.track_names)))
        return self.split_artists(artists)

    @cached_property
    def is_single(self) -> bool:
        return self._singleton or len(set(t["main_title"] for t in self.tracks)) == 1

    @cached_property
    def is_va(self) -> bool:
        track_count = len(self.tracks)

        def first_one(artist: str) -> str:
            return PATTERNS["split_artists"].split(artist.replace(" & ", ", "))[0]

        truly_unique = set(map(first_one, self.track_artists))
        return VA.casefold() in self.album_name.casefold() or (
            len(truly_unique) > min(4, track_count - 2) and track_count >= 4
        )

    @cached_property
    def albumartist(self) -> str:
        """Take into account the release contents and return the actual albumartist.
        * 'Various Artists' (or `va_name` configuration option) for a compilation release
        """
        if self.va:
            return self.va_name

        if self.unique_artists:
            return ", ".join(sorted(self.unique_artists))
        return self.official_albumartist

    @cached_property
    def albumtype(self) -> str:
        text = "\n".join([self.album_name, self.disctitle, self.comments])
        lp_count = text.count(" LP")
        ep_count = text.count(" EP")
        if lp_count >= ep_count and lp_count:
            return "album"
        if ep_count > lp_count:
            return "ep"

        if self.is_single:
            return "single"
        if self.is_va:
            return "compilation"
        return "album"

    @cached_property
    def va(self) -> bool:
        return len(self.unique_artists) > 4

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

        return ", ".join(sorted(genres)) or None

    @cached_property
    def parsed_album_name(self) -> str:
        match = re.search(r"[:-] ?([A-Z][\w ]+ ((?!an )[EL]P))", self.all_media_comments)
        return match.expand(r"\1") if match else ""

    @cached_property
    def clean_album_name(self) -> str:
        album = self.official_album_name
        if album:
            return album

        album = self.album_name
        # look for something in quotes
        match = re.search(r"(?:^| )(['\"])(.+?)\1(?: |$)", album)
        if match:
            album = match.expand(r"\2")
        album = self.clean_name(album, self.catalognum, remove_extra=True)
        if (
            album
            and not re.search(r"\W | [EL]P", album)  # no delimiters
            and album not in self.unique_artists  # and it isn't one of the artists
        ):
            return album

        if " EP" in album or " LP" in album:
            return self.clean_ep_lp_name(album, self.unique_artists)

        if not self._singleton:
            album = self.clean_name(
                album,
                self.bandcamp_albumartist,
                *self.unique_artists,
                self.raw_albumartist,
            )
        return album or self.parsed_album_name or self.catalognum or self.album_name

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
        fields = list(set(fields) - self.excluded_fields)
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
        ]
        if NEW_BEETS:
            fields.extend(["genre", "style", "comments"])
        common_data.update(self.get_fields(fields))
        reldate = self.release_date
        if reldate:
            common_data.update(self.get_fields(["year", "month", "day"], reldate))

        return common_data

    def _trackinfo(self, track: JSONDict, **kwargs: Any) -> TrackInfo:
        track.pop("digi_only", None)
        track.pop("main_title", None)
        ft = track.pop("ft", None)
        if ft:
            track["artist"] += f" {ft}"
        if not NEW_BEETS:
            track.pop("lyrics", None)
        track["track_alt"] = track["track_alt"] or None
        if not track["artist"]:
            track["artist"] = self.albumartist

        data = dict(**track, **self._common, **kwargs)
        if "index" in data:
            data.update(medium_index=data["index"])
        for field in set(data.keys()) & self.excluded_fields:
            data.pop(field)

        return TrackInfo(**data)

    @cached_property
    def singleton(self) -> TrackInfo:
        self._singleton = True
        track_dict = self.tracks[0]
        if not track_dict["artist"]:
            track_dict["artist"] = self.bandcamp_albumartist
        track = self._trackinfo({**track_dict, "index": None})
        if NEW_BEETS:
            track.update(self._common_album)
            track.pop("album", None)
            track.pop("albumstatus", None)
        track.track_id = track.data_url
        return track

    @cached_property
    def album(self) -> AlbumInfo:
        """Return album for the appropriate release format."""
        tracks: Iterable[JSONDict] = self.tracks
        include_digi = self.config.get("include_digital_only_tracks")
        if not include_digi and self.media_name != DIGI_MEDIA:
            tracks = it.filterfalse(op.itemgetter("digi_only"), tracks)

        tracks = list(map(op.methodcaller("copy"), tracks))
        get_trackinfo = partial(
            self._trackinfo,
            medium=1,
            disctitle=self.disctitle or None,
            medium_total=len(tracks),
        )
        album_info = AlbumInfo(
            **self._common,
            **self._common_album,
            artist=self.albumartist,
            album_id=self.album_id,
            mediums=self.mediums,
            tracks=list(map(get_trackinfo, tracks)),
        )
        for key, val in self.get_fields(["va"]).items():
            setattr(album_info, key, val)
        return album_info
