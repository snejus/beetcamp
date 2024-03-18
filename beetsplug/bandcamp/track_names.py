"""Module for parsing track names."""

import operator as op
import re
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass
from functools import reduce
from typing import Iterator, List, Optional, Tuple

from ordered_set import OrderedSet

from .helpers import CATNUM_PAT, REMIX


@dataclass
class TrackNames:
    """Responsible for parsing track names in the entire release context."""

    # Title [Some Album EP]
    ALBUM_IN_TITLE = re.compile(r"[- ]*\[([^\]]+ [EL]P)\]+", re.I)
    DELIMITER_PAT = re.compile(r" ([^\w&()+/[\] ]) ")
    TITLE_IN_QUOTES = re.compile(r'^(.+[^ -])[ -]+"([^"]+)"$')
    NUMBER_PREFIX = re.compile(r"((?<=^)|(?<=- ))\d{2,}\W* ")

    original: List[str]
    names: List[str]
    album: Optional[str] = None
    catalognum: Optional[str] = None

    def __iter__(self) -> Iterator[str]:
        return iter(self.names)

    @classmethod
    def split_quoted_titles(cls, names: List[str]) -> List[str]:
        if len(names) > 1:
            matches = list(filter(None, map(cls.TITLE_IN_QUOTES.match, names)))
            if len(matches) == len(names):
                return [m.expand(r"\1 - \2") for m in matches]

        return names

    @classmethod
    def remove_number_prefix(cls, names: List[str]) -> List[str]:
        prefix_matches = [cls.NUMBER_PREFIX.search(n) for n in names]
        if all(prefix_matches):
            prefixes = [m.group() for m in prefix_matches]  # type: ignore[union-attr]
            if len(set(prefixes)) > 1:
                return [n.replace(p, "") for n, p in zip(names, prefixes)]

        return names

    @classmethod
    def find_common_track_delimiter(cls, names: List[str]) -> str:
        """Return the track parts delimiter that is in effect in the current release.

        In some (rare) situations track parts are delimited by a pipe character
        or some UTF-8 equivalent of a dash.

        This checks every track for the first character (see the regex for exclusions)
        that splits it. The character that splits the most and at least half of
        the tracks is the character we need.

        If no such character is found, or if we have just one track, return a dash '-'.
        """

        def get_delim(string: str) -> str:
            m = cls.DELIMITER_PAT.search(string)
            return m.group(1) if m else "-"

        delim, count = Counter(map(get_delim, names)).most_common(1).pop()
        return delim if (len(names) == 1 or count > len(names) / 2) else "-"

    @classmethod
    def normalize_delimiter(cls, names: List[str]) -> List[str]:
        """Ensure the same delimiter splits artist and title in all names."""
        delim = cls.find_common_track_delimiter(names)
        return [n.replace(f" {delim} ", " - ") for n in names]

    @staticmethod
    def remove_label(names: List[str], label: str) -> List[str]:
        """Remove label name from the end of track names.

        See https://gutterfunkuk.bandcamp.com/album/gutterfunk-all-subject-to-vibes-various-artists-lp
        """
        return [
            (n.replace(label, "").strip(" -") if n.endswith(label) else n)
            for n in names
        ]

    @staticmethod
    def eject_common_catalognum(names: List[str]) -> Tuple[Optional[str], List[str]]:
        """Return catalognum found in every track title.

        1. Split each track name into words
        2. Find the list of words that are common to all tracks
        3. Check the *first* and the *last* word for the catalog number
           - If found, return it and remove it from every track name
        """
        catalognum = None

        names_tokens = map(str.split, names)
        common_words = reduce(op.and_, [OrderedSet(x) for x in names_tokens])
        if common_words:
            matches = (CATNUM_PAT["anywhere"].search(common_words[i]) for i in [0, -1])
            with suppress(StopIteration):
                catalognum, word = next((m.group(1), m.string) for m in matches if m)
                names = [n.replace(word, "").strip() for n in names]

        return catalognum, names

    @staticmethod
    def parenthesize_remixes(names: List[str]) -> List[str]:
        """Reformat broken remix titles for an album with a single root title.

        1. Check whether this release has a single root title
        2. Find remixes that do not have parens around them
        3. Add parens
        """
        names_tokens = map(str.split, names)
        common_words = reduce(op.and_, [OrderedSet(x) for x in names_tokens])
        joined = " ".join(common_words)
        if joined in names:  # it is one of the track names (root title)
            remix_parts = [n.replace(joined, "").lstrip() for n in names]
            return [
                (n.replace(rp, f"({rp})") if REMIX.fullmatch(rp) else n)
                for n, rp in zip(names, remix_parts)
            ]

        return names

    @classmethod
    def eject_album_name(cls, names: List[str]) -> Tuple[Optional[str], List[str]]:
        matches = list(map(cls.ALBUM_IN_TITLE.search, names))
        albums = {m.group(1).replace('"', "") for m in matches if m}
        if len(albums) != 1:
            return None, names

        return albums.pop(), [
            (n.replace(m.group(), "") if m else n) for m, n in zip(matches, names)
        ]

    @classmethod
    def make(cls, original: List[str], label: str) -> "TrackNames":
        names = cls.parenthesize_remixes(
            cls.remove_label(
                cls.normalize_delimiter(
                    cls.remove_number_prefix(cls.split_quoted_titles(original))
                ),
                label,
            )
        )
        catalognum, names = cls.eject_common_catalognum(names)
        album, names = cls.eject_album_name(names)
        return cls(original, names, album=album, catalognum=catalognum)
