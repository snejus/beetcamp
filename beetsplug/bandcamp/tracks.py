"""Module with tracks parsing functionality."""

import itertools as it
from dataclasses import dataclass
from functools import cached_property
from itertools import starmap
from typing import Iterator, List, Optional, Set

from .helpers import Helpers, JSONDict
from .track import Track
from .track_names import TrackNames


@dataclass
class Tracks:
    tracks: List[Track]
    names: TrackNames

    def __iter__(self) -> Iterator[Track]:
        return iter(self.tracks)

    def __len__(self) -> int:
        return len(self.tracks)

    @classmethod
    def from_json(cls, meta: JSONDict) -> "Tracks":
        try:
            tracks = [{**t, **t["item"]} for t in meta["track"]["itemListElement"]]
        except (TypeError, KeyError):
            tracks = [meta]

        names = TrackNames.make(
            [i.get("name", "") for i in tracks], Helpers.get_label(meta)
        )
        return cls(list(starmap(Track.make, zip(tracks, names))), names)

    @property
    def album(self) -> Optional[str]:
        return self.names.album

    @property
    def catalognum(self) -> Optional[str]:
        return self.names.catalognum

    @cached_property
    def first(self) -> Track:
        return self.tracks[0]

    @cached_property
    def raw_names(self) -> List[str]:
        return [j.name for j in self.tracks]

    @cached_property
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
            t.remix.remixer
            for t in self.tracks
            if t.remix and not t.remix.by_other_artist
        ]

    @property
    def other_artists(self) -> Set[str]:
        """Return all unique remix and featuring artists."""
        ft = [j.ft for j in self.tracks if j.ft]
        return set(it.chain(self.remixers, ft))

    @cached_property
    def all_artists(self) -> Set[str]:
        """Return all unique (1) track, (2) remix, (3) featuring artists."""
        return self.other_artists | set(self.original_artists)

    @cached_property
    def artistitles(self) -> str:
        """Returned artists and titles joined into one long string."""
        return " ".join(it.chain(self.raw_names, self.all_artists)).lower()

    def adjust_artists(self, albumartist: str) -> None:
        """Handle some track artist edge cases.

        These checks require knowledge of the entire release, therefore cannot be
        performed within the context of a single track.

        * When artist name is mistaken for the track_alt
        * When artist and title are delimited by '-' without spaces
        * When artist and title are delimited by a UTF-8 dash equivalent
        * Defaulting to the album artist
        """
        track_alts = {t.track_alt for t in self.tracks if t.track_alt}
        artists = [t.artist for t in self.tracks if t.artist]

        for t in [track for track in self.tracks if not track.artist]:
            if t.track_alt and len(track_alts) == 1:  # only one track_alt
                # the only track that parsed a track alt - it's most likely a mistake
                # one artist was confused for a track alt, like 'B2', - reverse this
                t.artist, t.track_alt = t.track_alt, None
            elif len(artists) == len(self) - 1:  # only 1 missing artist
                # if this is a remix and the parsed title is part of the albumartist or
                # is one of the track artists, we made a mistake parsing the remix:
                #  it is most probably the edge case where the `title_without_remix` is a
                #  legitimate artist and the track title is something like 'Hello Remix'
                if t.remix and (t.title_without_remix in albumartist):
                    t.artist, t.title = t.title_without_remix, t.remix.remix
                # this is the only artist that didn't get parsed - relax the rule
                # and try splitting with '-' without spaces
                split = t.title.split("-")
                if len(split) == 1:
                    # attempt to split by another ' ? ' where '?' may be some utf-8
                    # alternative of a dash
                    split = [
                        s for s in TrackNames.DELIMITER_PAT.split(t.title) if len(s) > 1
                    ]
                if len(split) > 1:
                    t.artist, t.title = split
            if not t.artist:
                # default to the albumartist
                t.artist = albumartist
