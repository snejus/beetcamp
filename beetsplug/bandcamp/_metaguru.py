"""Module for parsing bandcamp metadata."""
import itertools as it
import json
import operator as op
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from functools import partial
from html import unescape
from typing import Any, Dict, Iterable, List, Optional, Set
from unicodedata import normalize

from beets import config as beets_config
from beets.autotag.hooks import AlbumInfo, TrackInfo
from pkg_resources import get_distribution, parse_version
from pycountry import countries, subdivisions

from ._helpers import PATTERNS, Helpers, MediaInfo

if sys.version_info.minor > 7:
    from functools import cached_property  # pylint: disable=ungrouped-imports
else:
    from cached_property import cached_property  # type: ignore

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
    _singleton = False
    va_name = VA
    media = MediaInfo("", "", "", "")

    meta: JSONDict
    config: JSONDict
    media_formats: List[MediaInfo]

    def __init__(self, meta: JSONDict, config: Optional[JSONDict] = None) -> None:
        self.meta = meta
        self.media_formats = Helpers.get_media_formats(
            (meta.get("inAlbum") or meta).get("albumRelease") or []
        )
        if self.media_formats:
            self.media = self.media_formats[0]
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
        return (
            "\n".join(map(op.attrgetter("description"), self.media_formats))
            + self.comments
        )

    @cached_property
    def original_album_name(self) -> str:
        return self.meta["name"]

    @cached_property
    def parsed_album_name(self) -> str:
        match = re.search(
            r"(Title: ?|Album(:|/Single) )([^\n:]+)(\n|$)", self.all_media_comments
        )
        return match.expand(r"\3").strip() if match else ""

    @cached_property
    def album_name(self) -> str:
        return self.parsed_album_name or self.original_album_name

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
    def parsed_albumartist(self) -> str:
        match = re.search(r"Artists?:([^\n]+)", self.all_media_comments)
        return match.expand(r"\1").strip() if match else ""

    @cached_property
    def original_albumartist(self) -> str:
        return self.meta["byArtist"]["name"]

    @cached_property
    def bandcamp_albumartist(self) -> str:
        """Return the official release albumartist.
        It is correct in half of the cases. In others, we usually find the label name.
        """
        aartist = self.parsed_albumartist or self.original_albumartist
        if self.label == aartist:
            aartist = self.parse_track_name(self.album_name).get("artist") or aartist

        aartists = Helpers.split_artists([aartist])
        remixers_str = " ".join(self.remixers)

        def not_remixer(x: str) -> bool:
            return not any(map(lambda y: y in remixers_str, {x, *x.split(" & ")}))

        valid = list(filter(not_remixer, aartists))
        if (
            len(aartists) == 1
            or len(valid) == len(aartists)
            and len(self.raw_artists) <= 4
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

    @property
    def disctitle(self) -> str:
        """Return medium's disc title if found."""
        return "" if self.media.name == DIGI_MEDIA else self.media.title

    @property
    def mediums(self) -> int:
        return self.get_vinyl_count(self.disctitle) if self.media.name == "Vinyl" else 1

    @property
    def catalognum(self) -> str:
        artists = [self.parsed_albumartist or self.original_albumartist]
        if not self._singleton or len(self.raw_artists) > 1:
            artists.extend(self.raw_artists)
            artists.extend(self.remixers)
        return self.parse_catalognum(
            self.meta["name"],
            self.disctitle,
            self.media.description + "\n" + self.comments,
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
    def json_artists(self) -> List[str]:
        artists = []
        for item in map(lambda x: x["item"], self.json_tracks):
            try:
                artists.append(item["byArtist"]["name"])
            except KeyError:
                continue
        return artists

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
    def remixers(self) -> Set[str]:
        titles = " ".join(self.track_names)
        names = re.finditer(r"\( *([^)]+) (?i:(re)?mix|edit)\)", titles, re.I)
        ft = re.finditer(r"[( ](f(ea)?t[.]? [^()]+)\)?", titles, re.I)
        return set(map(lambda x: x.expand(r"\1"), it.chain(names, ft)))

    @cached_property
    def track_artists(self) -> List[str]:
        return list(filter(op.truth, map(lambda x: x.get("artist") or "", self.tracks)))

    @cached_property
    def unique_artists(self) -> List[str]:
        return self.split_artists(self.track_artists)

    @cached_property
    def track_names(self) -> List[str]:
        raw_tracks = self.meta.get("tracks") or []
        if raw_tracks:
            return list(map(lambda x: x.split(". ", maxsplit=1)[1], raw_tracks))

        for item in map(lambda x: x["item"], self.json_tracks):
            name = item["name"]
            artist = item.get("byArtist", {}).get("name")
            if not self._singleton and artist and artist != self.label:
                name = artist + " - " + name
            raw_tracks.append(name)

        return raw_tracks

    @cached_property
    def raw_artists(self) -> List[str]:
        def only_artist(name: str) -> str:
            return re.sub(r" - .*", "", PATTERNS["track_alt"].sub("", name))

        artists = list(map(only_artist, filter(lambda x: " - " in x, self.track_names)))
        return self.split_artists(artists)

    @cached_property
    def albumartist(self) -> str:
        """Take into account the release contents and return the actual albumartist.
        * 'Various Artists' (or `va_name` configuration option) for a compilation release
        """
        if self.va:
            return self.va_name

        if self.unique_artists:
            return ", ".join(sorted(self.unique_artists))
        return self.original_albumartist

    @cached_property
    def vinyl_disctitles(self) -> str:
        return " ".join([m.title for m in self.media_formats if m.name == "Vinyl"])

    def search_albumtype(self, word: str) -> bool:
        """Return whether the given word (ep or lp) matches the release albumtype.
        True when one of the following conditions is met:
        * if {word}[0-9] is found in the catalognum
        * if it's found in the original album name or any vinyl disctitle
        * if it's found in the same sentence as 'this' or '{album_name}', where
        sentences are read from release and media descriptions.
        """
        sentences = re.split(r"[.]\s+|\n", self.all_media_comments)
        word_pat = re.compile(fr"\b{word}\b", re.I)
        catnum_pat = re.compile(fr"{word}[0-9]", re.I)
        name_pat = re.compile(fr"\b(this|{re.escape(self.clean_album_name)})\b", re.I)
        return bool(
            catnum_pat.search(self.catalognum)
            or word_pat.search(self.original_album_name + " " + self.vinyl_disctitles)
            or any(map(lambda s: word_pat.search(s) and name_pat.search(s), sentences))
        )

    @cached_property
    def is_single(self) -> bool:
        return self._singleton or len(self.track_names) == 1

    @cached_property
    def is_lp(self) -> bool:
        """Return whether the release is an LP."""
        return self.search_albumtype("lp")

    @cached_property
    def is_ep(self) -> bool:
        """Return whether the release is an EP."""
        return self.search_albumtype("ep")

    def check_albumtype_in_descriptions(self) -> str:
        """Count 'lp', 'album' and 'ep' words in the release and media descriptions
        and return the albumtype that represents the word matching the most times.
        """
        matches = re.findall(r"\b(album|ep|lp)\b", self.all_media_comments.lower())
        if matches:
            counts = Counter(map(lambda x: x.replace("lp", "album"), matches))
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

        truly_unique = set(map(first_one, self.track_artists))
        return bool(
            re.search(r"compilation|best of|anniversary", self.album_name, re.I)
        ) or (len(truly_unique) > 3 and len(self.tracks) > 4)

    @cached_property
    def albumtype(self) -> str:
        if self.is_single:
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
        if self.albumtype == "compilation":
            albumtypes.add("album")
        if self.is_lp:
            albumtypes.add("lp")
        if len({t["main_title"] for t in self.tracks}) == 1:
            albumtypes.add("single")
        for word in ["remix", "live", "soundtrack"]:
            if word in self.album_name.lower():
                albumtypes.add(word)

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
        genres = self.get_genre(kws, genre_cfg)
        if genre_cfg["capitalize"]:
            genres = map(str.capitalize, genres)
        if genre_cfg["maximum"]:
            genres = it.islice(genres, genre_cfg["maximum"])

        return ", ".join(sorted(genres)) or None

    @cached_property
    def album_name_with_eplp(self) -> str:
        match = re.search(r"[:-] ?([A-Z][\w ]+ ((?!an )[EL]P))", self.all_media_comments)
        return match.expand(r"\1") if match else ""

    @cached_property
    def clean_album_name(self) -> str:
        if self.parsed_album_name:
            return self.parsed_album_name

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
            album = self.clean_ep_lp_name(album, self.unique_artists)
        else:
            album = self.clean_name(
                album,
                self.bandcamp_albumartist,
                *self.unique_artists,
                self.parsed_albumartist,
            )
        return album or self.album_name_with_eplp or self.catalognum or self.album_name

    @property
    def _common(self) -> JSONDict:
        return dict(
            data_source=DATA_SOURCE,
            media=self.media.name,
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

    @property
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
            fields.extend(["genre", "style", "comments", "albumtypes"])
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
        self.media = self.media_formats[0]
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

    def _album(self, media: MediaInfo) -> AlbumInfo:
        """Return album for the appropriate release format."""
        self.media = media
        tracks: Iterable[JSONDict] = self.tracks
        include_digi = self.config.get("include_digital_only_tracks")
        if not include_digi and self.media.name != DIGI_MEDIA:
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
        album_info.album_id = self.media.album_id
        if self.media.name == "Vinyl":
            album_info = self.add_track_alts(album_info, self.comments)
        return album_info

    @cached_property
    def albums(self) -> Iterable[AlbumInfo]:
        """Return album for the appropriate release format."""
        return list(map(self._album, self.media_formats))
