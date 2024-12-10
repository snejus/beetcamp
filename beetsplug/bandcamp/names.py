"""Module for parsing track names."""

from __future__ import annotations

import operator as op
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property, reduce
from os.path import commonprefix

from .catalognum import Catalognum
from .helpers import Helpers, JSONDict, cached_patternprop
from .track import Remix


@dataclass
class Names:
    """Responsible for parsing track names in the entire release context."""

    # Title [Some Album EP]
    ALBUM_IN_TITLE = cached_patternprop(r"[- ]*\[([^\]]+ [EL]P)\]+", re.I)
    SEPARATOR_PAT = cached_patternprop(r"(?<=\s)[|\u2013\u2014-](?=\s)")
    TITLE_IN_QUOTES = cached_patternprop(r'^(.+[^ -])[ -]+"([^"]+)"$')
    NUMBER_PREFIX = cached_patternprop(r"((?<=^)|(?<=- ))\d{1,2}\W+(?=\D)")

    meta: JSONDict = field(repr=False)
    album_artist: str
    album_in_titles: str | None = None
    catalognum_in_titles: str | None = None
    titles: list[str] = field(default_factory=list)

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
    def singleton(self) -> bool:
        return "track" not in self.meta

    @cached_property
    def json_tracks(self) -> list[JSONDict]:
        if self.singleton:
            return [{**self.meta, "byArtist": {"name": self.album_artist}}]

        if tracks := self.meta["track"].get("itemListElement"):
            return [{**t, **t["item"]} for t in tracks]

        # no tracks (sold out release or defunct label, potentially)
        return []

    @cached_property
    def original_titles(self) -> list[str]:
        return [i["name"] for i in self.json_tracks]

    @cached_property
    def _catalognum_in_album_match(self) -> re.Match[str] | None:
        return Catalognum.in_album_pat.search(self.original_album)

    @cached_property
    def catalognum_in_album(self) -> str | None:
        if m := self._catalognum_in_album_match:
            return next(filter(None, m.groups()))

        return None

    @cached_property
    def album(self) -> str:
        if m := self._catalognum_in_album_match:
            return self.original_album.replace(m[0], "")

        return self.original_album

    @cached_property
    def catalognum(self) -> str | None:
        for cat in (self.catalognum_in_album, self.catalognum_in_titles):
            if cat and cat != self.album_artist:
                return cat

        return None

    @property
    def common_prefix(self) -> str:
        return commonprefix(self.titles)

    @classmethod
    def split_quoted_titles(cls, names: list[str]) -> list[str]:
        if len(names) > 1:
            matches = list(filter(None, map(cls.TITLE_IN_QUOTES.match, names)))
            if len(matches) == len(names):
                return [m.expand(r"\1 - \2") for m in matches]

        return names

    def remove_album_catalognum(self, names: list[str]) -> list[str]:
        if catalognum := self.catalognum_in_album:
            pat = re.compile(rf"(?i)[([]{re.escape(catalognum)}[])]")
            return [pat.sub("", n) for n in names]

        return names

    @classmethod
    def remove_number_prefix(cls, names: list[str]) -> list[str]:
        """Remove track number prefix from the track names.

        If there is more than one track and at least half of the track names have
        a number prefix remove it from the names.
        """
        prefix_matches = [cls.NUMBER_PREFIX.search(n) for n in names]
        if len([p for p in prefix_matches if p]) > len(names) / 2:
            return [
                n.replace(p.group() if p else "", "")
                for n, p in zip(names, prefix_matches)
            ]

        return names

    @classmethod
    def find_common_track_delimiter(cls, names: list[str]) -> str:
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
    def normalize_delimiter(cls, names: list[str]) -> list[str]:
        """Ensure the same delimiter splits artist and title in all names.

        Additionally, assume that a tab character is a delimiter and replace it
        accordingly.
        """
        delim = cls.find_common_track_delimiter(names)
        pat = re.compile(rf"\s+[{re.escape(delim)}]\s+|\t")
        return [pat.sub(" - ", n) for n in names]

    def remove_label(self, names: list[str]) -> list[str]:
        """Remove label name from the end of track names.

        See https://gutterfunkuk.bandcamp.com/album/gutterfunk-all-subject-to-vibes-various-artists-lp  # noqa: E501
        """
        remove_label = re.compile(rf"([:-]+ |\[){re.escape(self.label)}(\]|$)", re.I)
        return [remove_label.sub(" ", n).strip() for n in names]

    @staticmethod
    def eject_common_catalognum(names: list[str]) -> tuple[str | None, list[str]]:
        """Return catalognum found in every track title.

        1. Split each track name into words
        2. Find the list of words that are common to all tracks
        3. Check the *first* and the *last* word for the catalog number
           - If found, return it and remove it from every track name
        """
        catalognum = None

        names_tokens = [name.split() for name in names]
        sets = [set(tokens) for tokens in names_tokens]
        common_words_set = reduce(op.and_, sets) if sets else set()

        first_name_words = names_tokens[0]
        words = [first_name_words[0], first_name_words[-1]]
        for word in (w for w in words if w in common_words_set):
            if m := Catalognum.anywhere.search(word):
                catalognum = m.group(1)
                names = [n.replace(m.string, "").strip("|- ") for n in names]

        return catalognum, names

    @classmethod
    def eject_album_name(cls, names: list[str]) -> tuple[str | None, list[str]]:
        matches = list(map(cls.ALBUM_IN_TITLE.search, names))
        albums = {m.group(1).replace('"', "") for m in matches if m}
        if len(albums) != 1:
            return None, names

        return albums.pop(), [
            (n.replace(m.group(), "") if m else n) for m, n in zip(matches, names)
        ]

    def ensure_artist_first(self, names: list[str]) -> list[str]:
        """Ensure the artist is the first part of the track name."""
        splits = [n.split(" - ", 1) for n in names]
        left = [s[0] for s in splits]
        if (
            # every track was split at least into two parts
            all(len(s) > 1 for s in splits)
            and (
                (
                    # every track has the same title
                    len(unique_titles := {t for _, t in splits}) == 1
                    # album artists and parts of the unique title overlap
                    and (
                        set(Helpers.split_artists(unique_titles.pop()))
                        & set(Helpers.split_artists(self.album_artist))
                    )
                )
                # or there are at least 2 remixes on the left side of the delimiter
                or sum(bool(Remix.PATTERN.search(x)) for x in left) > 1
            )
        ):
            return [f"{a} - {t}" for t, a in splits]

        return names

    def resolve(self) -> None:
        if not self.original_titles:
            return

        titles = self.split_quoted_titles(self.original_titles)
        if self.singleton:
            titles = [self.album]
        else:
            titles = self.remove_album_catalognum(titles)
            self.catalognum_in_titles, titles = self.eject_common_catalognum(titles)
            titles = self.remove_number_prefix(titles)

        titles = self.normalize_delimiter(titles)
        titles = self.remove_label(titles)
        self.album_in_titles, titles = self.eject_album_name(titles)
        self.titles = self.ensure_artist_first(titles)
