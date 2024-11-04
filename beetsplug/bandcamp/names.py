"""Module for parsing track names."""

import operator as op
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property, reduce
from os.path import commonprefix
from typing import List, Optional, Tuple

from ordered_set import OrderedSet

from .catalognum import Catalognum
from .helpers import REMIX, Helpers, JSONDict


@dataclass
class Names:
    """Responsible for parsing track names in the entire release context."""

    # Title [Some Album EP]
    ALBUM_IN_TITLE = re.compile(r"[- ]*\[([^\]]+ [EL]P)\]+", re.I)
    SEPARATOR_PAT = re.compile(r"(?<= )[|\u2013\u2014-](?= )")
    TITLE_IN_QUOTES = re.compile(r'^(.+[^ -])[ -]+"([^"]+)"$')
    NUMBER_PREFIX = re.compile(r"((?<=^)|(?<=- ))\d{1,2}\W+(?=\D)")

    meta: JSONDict
    album_artist: str
    album_in_titles: Optional[str] = None
    catalognum_in_titles: Optional[str] = None
    titles: List[str] = field(default_factory=list)

    @cached_property
    def label(self) -> str:
        try:
            item = self.meta.get("inAlbum", self.meta)["albumRelease"][0]["recordLabel"]
        except (KeyError, IndexError):
            item = self.meta["publisher"]

        return item.get("name") or ""

    @cached_property
    def original_album(self) -> str:
        return str(self.meta["name"])

    @cached_property
    def json_tracks(self) -> List[JSONDict]:
        try:
            return [{**t, **t["item"]} for t in self.meta["track"]["itemListElement"]]
        except KeyError as e:
            print(str(e))
            if "track" in str(e):
                # a single track release
                return [{**self.meta}]

            # no tracks (sold out release or defunct label, potentially)
            return []

    @cached_property
    def original_titles(self) -> List[str]:
        return [i["name"] for i in self.json_tracks]

    @cached_property
    def catalognum_in_album(self) -> Optional[str]:
        if cat := Catalognum.from_album(self.original_album):
            return cat

        return None

    @cached_property
    def catalognum(self) -> Optional[str]:
        for cat in (self.catalognum_in_album, self.catalognum_in_titles):
            if cat and cat != self.album_artist:
                return cat

        return None

    @property
    def common_prefix(self) -> str:
        return commonprefix(self.titles)

    @classmethod
    def split_quoted_titles(cls, names: List[str]) -> List[str]:
        if len(names) > 1:
            matches = list(filter(None, map(cls.TITLE_IN_QUOTES.match, names)))
            if len(matches) == len(names):
                return [m.expand(r"\1 - \2") for m in matches]

        return names

    def remove_album_catalognum(self, names: List[str]) -> List[str]:
        if catalognum := self.catalognum_in_album:
            pat = re.compile(rf"(?i)[([]{re.escape(catalognum)}[])]")
            return [pat.sub("", n) for n in names]

        return names

    @classmethod
    def remove_number_prefix(cls, names: List[str]) -> List[str]:
        """Remove track number prefix from the track names.

        If there is more than one track and at least half of the track names have
        a number prefix remove it from the names.
        """
        if len(names) == 1:
            return names

        prefix_matches = [cls.NUMBER_PREFIX.search(n) for n in names]
        if len([p for p in prefix_matches if p]) > len(names) / 2:
            return [
                n.replace(p.group() if p else "", "")
                for n, p in zip(names, prefix_matches)
            ]

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

        matches = [m for mat in map(cls.SEPARATOR_PAT.findall, names) for m in mat]
        if not matches:
            return "-"

        delim, count = Counter(matches).most_common(1).pop()
        return delim if (len(names) == 1 or count > len(names) / 2) else "-"

    @classmethod
    def normalize_delimiter(cls, names: List[str]) -> List[str]:
        """Ensure the same delimiter splits artist and title in all names."""
        delim = cls.find_common_track_delimiter(names)
        pat = re.compile(f" +{re.escape(delim)} +")
        return [pat.sub(" - ", n) for n in names]

    def remove_label(self, names: List[str]) -> List[str]:
        """Remove label name from the end of track names.

        See https://gutterfunkuk.bandcamp.com/album/gutterfunk-all-subject-to-vibes-various-artists-lp  # noqa: E501
        """
        remove_label = re.compile(rf"([:-]+ |\[){re.escape(self.label)}(\]|$)", re.I)
        return [remove_label.sub(" ", n).strip() for n in names]

    def eject_common_catalognum(
        self, names: List[str]
    ) -> Tuple[Optional[str], List[str]]:
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
            candidates = dict.fromkeys((common_words[0], common_words[-1]))
            for m in map(Catalognum.anywhere.search, candidates):
                if m:
                    catalognum = m.group(1)
                    names = [n.replace(m.string, "").strip("|- ") for n in names]

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

    def ensure_artist_first(self, names: List[str]) -> List[str]:
        """Ensure the artist is the first part of the track name."""
        splits = [n.split(" - ", 1) for n in names]
        if (
            # every track was split at least into two parts
            all(len(s) > 1 for s in splits)
            # every track has the same title
            and len(unique_titles := {t for _, t in splits}) == 1
            # there's an overlap between album artists and parts of the unique title
            and (
                set(Helpers.split_artists(unique_titles.pop()))
                & set(Helpers.split_artists(self.album_artist))
            )
        ):
            return [f"{a} - {t}" for t, a in splits]

        return names

    def resolve(self) -> None:
        if not self.original_titles:
            return

        self.catalognum_in_titles, titles = self.eject_common_catalognum(
            self.remove_album_catalognum(self.split_quoted_titles(self.original_titles))
        )
        self.album_in_titles, titles = self.eject_album_name(
            self.parenthesize_remixes(
                self.remove_label(
                    self.normalize_delimiter(self.remove_number_prefix(titles))
                )
            )
        )
        self.titles = self.ensure_artist_first(titles)
