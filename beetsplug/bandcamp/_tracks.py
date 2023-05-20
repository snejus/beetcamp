"""Module with tracks parsing functionality."""
import itertools as it
import operator as op
import re
import sys
from collections import Counter
from dataclasses import dataclass
from functools import reduce
from typing import Iterator, List, Optional, Set

from ordered_set import OrderedSet

from ._helpers import CATNUM_PAT, Helpers, JSONDict, _remix_pat
from .track import Track

if sys.version_info.minor > 7:
    from functools import cached_property  # pylint: disable=ungrouped-imports
else:
    from cached_property import cached_property  # type: ignore # pylint: disable=import-error # noqa

digiwords = r"""
    # must contain at least one of
    (\W*(bandcamp|digi(tal)?|exclusive|bonus|bns|unreleased))+
    # and may be followed by
    (\W(track|only|tune))*
    """
DIGI_ONLY_PATTERN = re.compile(
    rf"""
\s*  # all preceding space
(
      (^{digiwords}[.:\d\s]+\s)     # begins with 'Bonus.', 'Bonus 1.' or 'Bonus :'
 | [\[(]{digiwords}[\])]\W*         # delimited by brackets, '[Bonus]', '(Bonus) -'
 |   [*]{digiwords}[*]              # delimited by asterisks, '*Bonus*'
 |  ([ ]{digiwords}$)               # might not be delimited if at the end, '... Bonus'
)
\s*  # all succeeding space
    """,
    re.I | re.VERBOSE,
)
DELIMITER_PAT = re.compile(r" ([^\w&()+/[\] ]) ")
ELP_ALBUM_PAT = re.compile(r"[- ]*\[([^\]]+ [EL]P)\]+")  # Title [Some Album EP]
TITLE_IN_QUOTES = re.compile(r'^(.+[^ -])[ -]+"([^"]+)"$')
NUMBER_PREFIX = re.compile(r"(^|- )\d{2,}\W* ")


@dataclass
class Tracks(List[Track]):
    tracks: List[Track]

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

        names = [i.get("name", "") for i in tracks]
        names = cls.split_quoted_titles(names)
        names = cls.remove_number_prefix(names)
        delim = cls.track_delimiter(names)
        for track, name in zip(tracks, names):
            track["name_parts"] = {"clean": name}
            track["delim"] = delim
        tracks = cls.common_name_parts(tracks, names)
        return cls([Track.from_json(t, delim, Helpers.get_label(meta)) for t in tracks])

    @cached_property
    def first(self) -> Track:
        return self.tracks[0]

    @staticmethod
    def split_quoted_titles(names: List[str]) -> List[str]:
        if len(names) > 1 and all(TITLE_IN_QUOTES.match(n) for n in names):
            return [TITLE_IN_QUOTES.sub(r"\1 - \2", n) for n in names]
        return names

    @staticmethod
    def remove_number_prefix(names: List[str]) -> List[str]:
        if len(names) > 1 and all(NUMBER_PREFIX.search(n) for n in names):
            return [NUMBER_PREFIX.sub(r"\1", n) for n in names]
        return names

    @staticmethod
    def common_name_parts(tracks, names):
        # type: (List[JSONDict], List[str]) -> List[JSONDict]
        """Parse track names for parts that require knowledge of the other names.

        1. Split each track name into words
        2. Find the list of words that are common to all tracks
           a. check the *first* and the *last* word for the catalog number
              1. If found, remove it from every track name
           b. check whether tracks start the same way. This indicates an album with
              one unique root title and a couple of its remixes. This is especially
              relevant when the remix is not delimited appropriately.
        Return the catalog number and the new list of names.
        """
        names_tokens = map(str.split, names)
        common_words = reduce(op.and_, [OrderedSet(x) for x in names_tokens])
        if not common_words:
            return tracks

        matches = (CATNUM_PAT["anywhere"].search(common_words[i]) for i in [0, -1])
        try:
            cat, word = next(((m.group(1), m.string) for m in matches if m))
        except StopIteration:
            pass
        else:
            for track in tracks:
                track["name_parts"].update(
                    catalognum=cat,
                    clean=track["name_parts"]["clean"].replace(word, "").strip(),
                )

        joined = " ".join(common_words)
        if joined in names:  # it is one of the track names (root title)
            for track in tracks:
                leftover = track["name_parts"]["clean"].replace(joined, "").lstrip()
                # looking for a remix without brackets
                if re.fullmatch(_remix_pat, leftover, re.I):
                    track["name_parts"]["clean"] = f"{joined} ({leftover})"

        return tracks

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

    @cached_property
    def single_catalognum(self) -> Optional[str]:
        """Return catalognum if every track contains the same one."""
        cats = [t.catalognum for t in self if t.catalognum]
        if len(cats) == len(self) and len(set(cats)) == 1:
            return cats[0]
        return None

    @cached_property
    def albums_in_titles(self) -> Set[str]:
        return {t.album for t in self if t.album}

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
                #  it is most probably the edge case where the `main_title` is a
                #  legitimate artist and the track title is something like 'Hello Remix'
                if t.remix and (t.main_title in albumartist):
                    t.artist, t.title = t.main_title, t.remix.remix
                # this is the only artist that didn't get parsed - relax the rule
                # and try splitting with '-' without spaces
                split = t.title.split("-")
                if len(split) == 1:
                    # attempt to split by another ' ? ' where '?' may be some utf-8
                    # alternative of a dash
                    split = [s for s in DELIMITER_PAT.split(t.title) if len(s) > 1]
                if len(split) > 1:
                    t.artist, t.title = split
            if not t.artist:
                # default to the albumartist
                t.artist = albumartist

    @staticmethod
    def track_delimiter(names: List[str]) -> str:
        """Return the track parts delimiter that is in effect in the current release.
        In some (rare) situations track parts are delimited by a pipe character
        or some UTF-8 equivalent of a dash.

        This checks every track for the first character (see the regex for exclusions)
        that splits it. The character that splits the most and at least half of
        the tracks is the character we need.

        If no such character is found, or if we have just one track, return a dash '-'.
        """

        def get_delim(string: str) -> str:
            m = DELIMITER_PAT.search(string)
            return m.group(1) if m else "-"

        delim, count = Counter(map(get_delim, names)).most_common(1).pop()
        return delim if (len(names) == 1 or count > len(names) / 2) else "-"
