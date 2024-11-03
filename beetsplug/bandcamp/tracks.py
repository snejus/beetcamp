"""Module with tracks parsing functionality."""

import itertools as it
from dataclasses import dataclass
from functools import cached_property
from typing import Iterator, List, Set

from .track import Track
from .names import Names


@dataclass
class Tracks:
    tracks: List[Track]
    names: Names

    def __iter__(self) -> Iterator[Track]:
        return iter(self.tracks)

    def __len__(self) -> int:
        return len(self.tracks)

    @classmethod
    def from_names(cls, names: Names) -> "Tracks":
        tracks = names.json_tracks
        for track, name in zip(tracks, names.titles):
            track["name"] = name

        album_artist = names.album_artist
        if (
            len(tracks) > 1
            and names.original_album in names.common_prefix
            and album_artist != names.label
            and "," not in album_artist
        ):
            for track in tracks:
                track["album_artist"] = album_artist

        return cls(list(map(Track.make, tracks)), names)

    @cached_property
    def first(self) -> Track:
        return self.tracks[0]

    @cached_property
    def raw_names(self) -> List[str]:
        return [j.name for j in self.tracks]

    @property
    def original_artists(self) -> List[str]:
        """Return all unique unsplit (original) main track artists."""
        return list(dict.fromkeys(j.artist for j in self.tracks))

    @property
    def artists(self) -> List[str]:
        """Return all unique split main track artists.

        "Artist1 x Artist2" -> ["Artist1", "Artist2"]
        """
        return list(dict.fromkeys(it.chain(*(j.artists for j in self.tracks))))

    @property
    def remixers(self) -> List[str]:
        """Return all remix artists."""
        return [
            t.remix.remixer for t in self.tracks if t.remix and t.remix.by_other_artist
        ]

    @property
    def other_artists(self) -> Set[str]:
        """Return all unique remix and featuring artists."""
        ft = [j.ft for j in self.tracks if j.ft]
        return set(it.chain(self.remixers, ft))

    @property
    def all_artists(self) -> Set[str]:
        """Return all unique (1) track, (2) remix, (3) featuring artists."""
        return self.other_artists | set(self.original_artists)

    @cached_property
    def artists_and_titles(self) -> Set[str]:
        """Return a set with all artists and titles."""
        return set(self.raw_names) | self.all_artists

    def allocate_track_alt(self, track_alt: str) -> None:
        """Move the track_alt back to artist or title for the tracks that have it.

        Loop across tracks that have track_alt and:
        1. Make it the artist if track does not already have it, and (at least one
           other artist was found or the same track_alt ended up on each track).
        2. Return it to the beginning of the title otherwise
        """
        track_alt_tracks = [t for t in self.tracks if t.track_alt]

        same_track_alt_on_all = len(track_alt_tracks) == len(self)
        parsed_any_artists = any(t for t in self.tracks if t.artist)

        may_set_artist = parsed_any_artists or same_track_alt_on_all
        for t in track_alt_tracks:
            if not t.artist and may_set_artist:
                t.artist = track_alt
            else:
                t.title = t.json_item["name"]
            t.track_alt = None

    def set_missing_artists(self, missing_count: int, albumartist: str) -> None:
        """Set artist for tracks that do not have it.

        Firstly, check how many tracks are missing artists. If there are 1-3 tracks
        which have it set, this is most likely because the titles had ' - ' separator
        and our logic split it into artist. For each, ensure that
            (1) Artist was not set in the JSON metadata
            (2) This string is not part of the albumartist
            (3) Albumartist is not found anywhere in the title
        If so, move this string back to the title and replace it by the albumartist.

        If only one artist is missing, check whether the title can be split by '-'
        without spaces or some other UTF-8 equivalent (most likely an alternative
        representation of a dash).

        Otherwise, use the albumartist as the default.
        """
        tracks_without_artist = [t for t in self if not t.artist]
        if 1 <= len(self) - len(tracks_without_artist) < 4:
            aartist = albumartist.lower()
            for t in (
                t
                for t in self
                if (artist := t.artist.lower())
                and not t.json_artist
                and artist not in aartist
                and aartist not in f"{artist}{t.ft_artist.lower()}{t.title.lower()}"
            ):
                t.title = f"{t.artist} - {t.title}"
                t.artist = ""
        elif missing_count < len(self) / 2:
            for t in tracks_without_artist:
                # split the title by '-' (without spaces) or something unknown in ' ? '
                if (
                    len(split := t.title.split("-")) > 1
                    or len(split := Names.SEPARATOR_PAT.split(t.title)) > 1
                ):
                    t.artist, t.title = map(str.strip, split)

        for t in (t for t in self.tracks if not t.artist):
            # default to the albumartist
            t.artist = albumartist

    def post_process(self, albumartist: str) -> None:
        """Perform adjustments that require knowledge of all parsed tracks.

        Context of a single track is not enough to handle these edge cases.
        """
        unique_track_alts = {t.track_alt for t in self.tracks if t.track_alt}
        if len(unique_track_alts) == 1 and len(self) > 1:
            self.allocate_track_alt(unique_track_alts.pop())

        if missing_artist_count := sum(1 for t in self.tracks if not t.artist):
            self.set_missing_artists(missing_artist_count, albumartist)
