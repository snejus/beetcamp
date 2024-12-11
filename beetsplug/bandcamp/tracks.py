"""Module with tracks parsing functionality."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import cached_property
from os.path import commonprefix
from typing import TYPE_CHECKING, Any

from .names import Names
from .track import Track

ordset = dict.fromkeys

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass
class Tracks:
    DISC_BY_LETTER = {
        "A": 1,
        "B": 1,
        "C": 2,
        "D": 2,
        "E": 3,
        "F": 3,
        "G": 4,
        "H": 4,
        "I": 5,
        "J": 5,
    }
    tracklist: list[Track]
    names: Names

    def __iter__(self) -> Iterator[Track]:
        return iter(self.tracklist)

    def __len__(self) -> int:
        return len(self.tracklist)

    def __getitem__(self, idx: int) -> Track:
        return self.tracklist[idx]

    @classmethod
    def from_names(cls, names: Names) -> Tracks:
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

        obj = cls(list(map(Track.make, tracks)), names)
        obj.handle_wild_track_alt()
        obj.fix_title_split()
        return obj

    @property
    def tracks_without_artist(self) -> list[Track]:
        return [t for t in self if not t.artist]

    @cached_property
    def first(self) -> Track:
        return self[0]

    @cached_property
    def raw_names(self) -> list[str]:
        return [j.name for j in self]

    @property
    def original_artists(self) -> list[str]:
        """Return all unique unsplit (original) main track artists."""
        return list(dict.fromkeys(j.artist for j in self))

    @property
    def artists(self) -> list[str]:
        """Return all unique split main track artists.

        "Artist1 x Artist2" -> ["Artist1", "Artist2"]
        """
        return list(dict.fromkeys(a for t in self for a in t.artists))

    @cached_property
    def lead_artists(self) -> list[str]:
        """Return all lead artists.

        Keep the first artist in collaborations:
        [A] -> [A]
        [A, A & B] -> [A]
        [A & B, A & C] -> [A]
        [A, B] -> [A, B]
        [A, B, B & C] -> [A, B]
        [A, B & C, B & D] -> [A, B]

        But keep collaborations in tact if artists do not appear on their own:
        [A & B] -> [A & B]
        [A, B & C] -> [A, B & C]
        """
        lead_artists = list(dict.fromkeys(t.lead_artist for t in self))
        unique_artists = set(self.artists)
        if not unique_artists:
            return []

        return [
            (
                a
                if a in unique_artists
                or len(collabs := [u for u in unique_artists if a in u]) > 1
                else collabs[0]
            )
            for a in lead_artists
        ]

    @property
    def collaborators(self) -> set[str]:
        """Return all unique remix and featuring artists."""
        artists = set(self.artists)
        remixers = {
            r
            for t in self
            if t.remix and (r := t.remix.artist) and all(a not in r for a in artists)
        }
        feat = {j.ft for j in self if j.ft}
        return remixers | feat

    @cached_property
    def artists_and_titles(self) -> set[str]:
        """Return a set with all artists and titles."""
        return set(self.raw_names) | self.collaborators | set(self.original_artists)

    def discard_collaborators(self, artists: list[str]) -> list[str]:
        collaborators = " ".join(self.collaborators).lower()

        return [
            a
            for a in artists
            if any(sa not in collaborators for sa in a.lower().split(" & "))
        ]

    def fix_title_split(self) -> None:
        if 1 <= len(tracks := self.tracks_without_artist) < len(self) / 2:
            for t in (t for t in tracks if t.remix):
                # reset the artist if it got removed because it's in the remix text
                if len(t.name_split) > 1:
                    t.artist = " - ".join(t.name_split[:-1])
                else:
                    t.artist = t.json_artist

        # identify a track where artist was incorrectly parsed from the title
        # while a llegitimate artist was available in the JSON data.
        not_json_artist_tracks = [
            t
            for t in self
            if t.artist
            and "," not in t.json_artist
            and not commonprefix([t.json_artist, t.artist])
            and not commonprefix([t.json_artist, t.remix.remixer if t.remix else ""])
            and t.json_artist.lower() not in t.name.lower()
        ]
        if len(not_json_artist_tracks) == 1 and len(self) > 2:
            for t in not_json_artist_tracks:
                t.title = f"{t.artist} - {t.title}"
                t.artist = t.json_artist

    def handle_wild_track_alt(self) -> None:
        """Handle tracks that have incorrectly parsed `track_alt` field.

        If there is a single unique `track_alt` value and multiple tracks in the
        release, assign the `track_alt` value to the `artist` or reset the `title` to
        the initial track's name.

        Clear the `track_alt` value after assignment.
        """
        unique_track_alts = {t.track_alt for t in self if t.track_alt}
        if len(unique_track_alts) == 1 and len(self) > 1:
            track_alt_tracks = [t for t in self if t.track_alt]

            same_track_alt_on_all = len(track_alt_tracks) == len(self)
            parsed_any_artists = any(t for t in self if t.artist)

            may_set_artist = parsed_any_artists or same_track_alt_on_all
            unique_track_alt = unique_track_alts.pop()
            for t in track_alt_tracks:
                if not t.artist and may_set_artist:
                    t.artist = unique_track_alt
                else:
                    t.title = t.json_item["name"]
                t.track_alt = None

    def fix_track_artists(self, albumartist: str) -> None:
        """Adjust track artists in the context of the entire album.

        Firstly, check whether the artist is 'the'. If so, prepend it to the title and
        reset the artist.

        Then, check how many tracks are missing artists. If there are 1-3 tracks
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
        for t in (t for t in self if t.artist):
            # the artist cannot be 'the', so it's most likely a part of the title
            if t.artist.lower() == "the":
                t.title = f"{t.artist} {t.title}"
                t.artist = ""

        if not self.tracks_without_artist:
            return

        if 1 <= len(self) - len(self.tracks_without_artist) < 4:
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

        if 1 <= len(tracks := self.tracks_without_artist) < len(self) / 2:
            for t in tracks:
                if (
                    len(split := t.title.split("-", 1)) > 1
                    or len(split := Names.SEPARATOR_PAT.split(t.title, 1)) > 1
                ):
                    t.artist, t.title = map(str.strip, split)

        for t in self.tracks_without_artist:
            # default to the albumartist
            t.artist = albumartist

    def for_media(
        self, media: str, comments: str, include_digi: bool
    ) -> list[dict[str, Any]]:
        if not include_digi and media != "Digital Media":
            tracks_ = [t for t in self if not t.digi_only]
        else:
            tracks_ = list(self)

        medium_total = {"medium_total": len(tracks_)}
        tracks = [t.info | medium_total for t in tracks_]
        if len(tracks) == 1 or media != "Vinyl":
            return tracks

        # using an ordered set here in case of duplicates
        track_alts = ordset(Track.TRACK_ALT_PAT.findall(comments))
        if len(track_alts) != len(tracks):
            return tracks

        mediums = [self.DISC_BY_LETTER[ta[0]] for ta in track_alts]
        total_by_medium = Counter(mediums)
        index_by_medium = dict.fromkeys(total_by_medium, 1)
        for track, (track_alt, medium) in zip(tracks, zip(track_alts, mediums)):
            track.update(
                track_alt=track_alt,
                medium=medium,
                medium_total=total_by_medium[medium],
                medium_index=index_by_medium[medium],
            )
            index_by_medium[medium] += 1

        return tracks
