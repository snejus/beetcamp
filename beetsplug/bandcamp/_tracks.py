import itertools as it
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from functools import reduce
from typing import Iterator, List, Optional, Set, Tuple

from beets.autotag import TrackInfo
from ordered_set import OrderedSet as ordset  # type: ignore
from rich import print

from ._helpers import PATTERNS, Helpers, JSONDict

if sys.version_info.minor > 7:
    from functools import cached_property  # pylint: disable=ungrouped-imports
else:
    from cached_property import cached_property  # type: ignore

DIGI_ONLY_PATTERNS = [
    re.compile(r"^(DIGI(TAL)? ?[\d.]+|Bonus\W{2,})\W*"),
    re.compile(
        r"[^\w)]+(bandcamp[^-]+|digi(tal)?)(\W*(\W+|only|bonus|exclusive)\W*$)", re.I
    ),
    re.compile(r"[^\w)]+(bandcamp exclusive )?bonus( track)?(\]|\W*$)", re.I),
]
DELIMITER_PAT = re.compile(r" ([^\w&()+/[\] ]) ")


@dataclass
class JSONTrack:
    track_id: str
    index: int
    title: str
    artist: str
    duration: int
    lyrics: str
    label: str
    delim: str

    @classmethod
    def from_json(cls, json: JSONDict, label: str, delim: str) -> "JSONTrack":
        item = json["item"]
        return cls(
            item["@id"],
            json["position"],
            item["name"],
            item.get("byArtist", {}).get("name"),
            cls.get_duration(item),
            cls.get_lyrics(item),
            label,
            delim,
        )

    @staticmethod
    def get_duration(item: JSONDict) -> int:
        try:
            h, m, s = map(int, re.findall(r"[0-9]+", item["duration"]))
        except KeyError:
            return 0
        else:
            return h * 3600 + m * 60 + s

    @staticmethod
    def get_lyrics(item: JSONDict) -> str:
        try:
            return item["recordingOf"]["lyrics"]["text"].replace("\r", "")
        except KeyError:
            return ""

    @cached_property
    def name(self) -> str:
        title = self.title.replace(f" {self.delim} ", " - ")
        if self.artist and self.artist != self.label:
            return f"{self.artist} - {title}"
        return title

    @cached_property
    def artists(self) -> List[str]:
        name = PATTERNS["track_alt"].sub("", self.name)
        return Helpers.split_artists(name.split(f" {self.delim} ")[:-1])


@dataclass
class Track:
    EP_ALBUM_PAT = re.compile(r" *\[([^\]]+ [EL]P)\]+")
    BAD_REMIX_PAT = re.compile(r"- ([^()]*(Remix|Mix|Edit))$")

    json: JSONTrack
    name: str
    single: bool

    album: str = ""
    artist: str = ""
    title: str = ""
    main_title: str = ""
    ft: str = ""
    track_alt: Optional[str] = None

    @cached_property
    def no_digi_name(self) -> str:
        """Return the track title which is clear from digi-only artifacts."""
        return reduce(lambda a, b: b.sub("", a), DIGI_ONLY_PATTERNS, self.name)

    @cached_property
    def digi_only(self) -> bool:
        """Return True if the track is digi-only."""
        return self.json.name != self.no_digi_name

    @cached_property
    def artist_with_ft(self) -> str:
        return self.artist + (f" {self.ft}" if self.ft else "")

    @staticmethod
    def clean_name(track: "Track", catalognum: str) -> "Track":
        """Remove catalogue number and leading numerical index if they are found."""
        name = track.no_digi_name

        # Title[Album LP] -> Title
        match = Track.EP_ALBUM_PAT.search(name)
        if match:
            track.album = match.group(1).replace('"', "").strip()
            name = name.replace(match.group(), "")
        # CAT123 Artist - Title -> Artist - Title
        name = Helpers.clean_name(name, catalognum)
        # 04. Title -> Title
        name = re.sub(fr"^0*{track.json.index}(?!\W\d)\W+", "", name)
        # Title - Some Remix -> Title (Some Remix)
        name = Track.BAD_REMIX_PAT.sub("(\\1)", name)
        track.name = name
        return track

    @staticmethod
    def parse_track_alt(name: str) -> Tuple[Optional[str], str]:
        track_alt = None
        match = PATTERNS["track_alt"].match(name)
        if match:
            track_alt = match.group(1).upper()
            name = name.replace(match.group(), "")
        return track_alt, name

    def parse_name(self) -> "Track":
        self.track_alt, name = self.parse_track_alt(self.name)
        parts = name.split(" - ")
        if len(parts) == 1:
            # only if not split, then attempt at correcting it
            # some titles contain such patterns like below, so we want to avoid
            # splitting them if there's no reason to
            parts = re.split(r" -|- ", name)
        parts = list(map(lambda x: x.strip(" -"), parts))
        title = parts.pop(-1)

        if not self.track_alt:
            self.track_alt, title = self.parse_track_alt(title)
        self.title = title

        # find the remixer
        match = re.search(r" *\( *[^)(]+?(?i:(re)?mix|edit)\)", title, re.I)
        remixer = match.group() if match else ""

        # remove duplicate artists case-insensitively, and keeping the order
        artists = ordset((next(orig) for _, orig in it.groupby(ordset(parts), str.lower)))
        artist = ", ".join(artists)
        # remove remixer
        artist = artist.replace(remixer, "").strip(",")
        # split them taking into account other delimiters
        artists = ordset(Helpers.split_artists(parts))

        # remove remixer. We cannot use equality here since it is not reliable
        # consider
        #           Hello, Bye - Nice day (Bye Lovely Day Mix)
        # Bye != Bye Lovely Day, therefore we check whether 'Bye' is found in
        # 'Bye Lovely Day' instead
        for artist in filter(lambda x: x in remixer, artists.copy()):
            artists.discard(artist)
            artist = ", ".join(artists)

        self.artist = artist

        # find the featuring artist, remove it from artist/title and make it available
        # in the `ft` field, later to be appended to the artist
        for fld in "artist", "title":
            value = getattr(self, fld, "")
            match = PATTERNS["ft"].search(value)
            if match:
                # replacing with a space in case it's found in the middle of the title
                # if it's at the end, it gets stripped
                setattr(self, fld, value.replace(match.group().rstrip(), "").strip())
                self.ft = match.group(1).strip("([]) ")

        self.main_title = PATTERNS["remix_or_ft"].sub("", self.title)
        return self

    @property
    def info(self) -> TrackInfo:
        return TrackInfo(
            index=self.json.index if not self.single else None,
            medium_index=self.json.index if not self.single else None,
            medium=None,
            track_id=self.json.track_id,
            artist=self.artist_with_ft,
            title=self.title,
            length=self.json.duration,
            track_alt=self.track_alt,
            lyrics=self.json.lyrics,
        )


@dataclass
class Tracks(list):
    meta: JSONDict
    json_tracks: List[JSONTrack]
    tracks: List[Track] = field(default_factory=list)

    def __iter__(self) -> Iterator[Track]:
        return iter(self.tracks or [])

    def __len__(self) -> int:
        return len(self.json_tracks or [])

    @classmethod
    def from_json(cls, meta: JSONDict) -> "Tracks":
        try:
            tracks = meta["track"]["itemListElement"]
        except KeyError:
            tracks = [{"item": meta, "position": 1}]
        try:
            label = meta["albumRelease"][0]["recordLabel"]["name"]
        except (KeyError, IndexError):
            label = meta["publisher"]["name"]
        delim = Tracks.track_delimiter([i["item"]["name"] for i in tracks])
        return cls(meta, [JSONTrack.from_json(t, label, delim) for t in tracks])

    @cached_property
    def artists(self) -> List[str]:
        return [t.artist for t in self.tracks]

    @cached_property
    def raw_names(self) -> List[str]:
        return [j.name for j in self.json_tracks]

    @cached_property
    def raw_artists(self) -> List[str]:
        return list(ordset(it.chain(*(j.artists for j in self.json_tracks))))

    @cached_property
    def raw_remixers(self) -> Set[str]:
        titles = " ".join(self.raw_names)
        names = re.finditer(r"\( *([^)]+) (?i:(re)?mix|edit)\)", titles, re.I)
        ft = re.finditer(r"[( ](f(ea)?t[.]? [^()]+)\)?", titles, re.I)
        return set(map(lambda x: x.group(1), it.chain(names, ft)))

    def adjust_artists(self, aartist: str) -> None:
        track_alts = {t.track_alt for t in self.tracks if t.track_alt}
        artists = [t.artist for t in self.tracks if t.artist]
        count = len(self)
        for idx, t in enumerate(self):
            if not t.track_alt and len(track_alts) == count - 1 and not t.digi_only:
                # the only track without a track alt - most likely it's still in the
                # artist field, but we need to relax the rules to see -> check for
                # a single or two letters, like 'A' or 'AB'
                match = re.match(r"([A-B]{,2})\W+", t.artist)
                if match:
                    t.track_alt = match.group(1)
                    t.artist = t.artist.replace(match.group(), "", 1)
            elif t.track_alt and len(track_alts) == 1:
                # the only track that parsed a track alt - it's most likely a mistake
                if t.artist:
                    # one title was confused for a track alt, like 'C4'
                    # this would have shifted the artist to become the title as well
                    # so let's reverse it all
                    t.title, t.artist = t.track_alt, t.title
                else:
                    # one artist was confused for a track alt, like 'B2', - reverse this
                    t.artist = t.track_alt
                t.track_alt = None

            if not t.artist:
                if len(artists) == count - 1:
                    # this is the only artist that didn't get parsed - relax the rule
                    # and try splitting with '-' without spaces
                    split = t.title.split("-")
                    if len(split) > 1:
                        t.artist, t.title = split
                if not t.artist:
                    # use the albumartist
                    t.artist = aartist

    @staticmethod
    def track_delimiter(names: List[str]) -> str:
        """Return the track parts delimiter that is in effect in the current release.
        In some (unusual) situations track parts are delimited by a pipe character
        instead of dash.

        This checks every track looking for the first character (see the regex for
        exclusions) that splits it. The character that split the most and
        at least half of the tracklist is the character we need.
        """

        def get_delim(string: str) -> str:
            match = DELIMITER_PAT.search(string)
            return match.group(1) if match else "-"

        most_common = Counter(map(get_delim, names)).most_common(1)
        if not most_common:
            return ""
        delim, count = most_common.pop()
        return delim if (len(names) == 1 or count > len(names) / 2) else "-"

    def parse(self, albumartist: str, catalognum: str, single: bool) -> "Tracks":
        """Parse relevant details from the tracks' JSON."""

        # delim = self.track_delimiter(self.raw_names)
        for name, json_track in zip(self.raw_names, self.json_tracks):
            track = Track(json_track, name, single)
            track = Track.clean_name(track, catalognum)
            track.parse_name()
            self.tracks.append(track)

        self.adjust_artists(albumartist)
        return self
