"""Module with album parsing logic."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from re import Match
from typing import TYPE_CHECKING, Any

from .helpers import Helpers, cached_patternprop
from .track import Remix, Track

if TYPE_CHECKING:
    from collections.abc import Iterable

JSONDict = dict[str, Any]


@dataclass
class AlbumName:
    SPLIT_RELEASE_ARTIST_COUNT = 2

    _series = r"(?i:\b(part|volume|pt|vol)\b\.?)"
    SERIES = cached_patternprop(rf"{_series}[ ]?[A-Z\d.-]+\b")
    SERIES_FMT = cached_patternprop(rf"^(.+){_series} *0*")
    REMIX_IN_TITLE = cached_patternprop(
        r"""
            (?<=remixes\ )\([^()]+\)$
          | \((?:inc|\+)[^()]*mix(?:es)?\)
          | (?:incl\.|with\ remixes)[^()+]+
          | \W*(?:\+|w/)[\w\s/]*remix(?:ed)?$
          | \(tracks\ from[^)]+\)
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    CLEAN_EPLP = cached_patternprop(r"(?:[([]|Double ){0,2}(\b[EL]P\b)\S?", re.I)
    EPLP_ALBUM = cached_patternprop(
        r"\b(?!VA|0\d|-)([^\s:]+\b|[&, ])+ [EL]P\b( [\w#][^ ]+$)?"
    )
    EPLP_ALBUM_LINE = cached_patternprop(
        r"\b(?=[A-Z])(((?!Vinyl|VA|-)[^:\s]+ )+)[EL]P$", re.M
    )
    QUOTED_ALBUM = cached_patternprop(r"\B(['\"])([^'\"]+)\1\B( VA\d+| [EL]P)?", re.I)
    ALBUM_IN_DESC = cached_patternprop(r"(?:Title *: ?|Album(?: *:|/Single) )([^\n]+)")
    CLEAN_VA_EXCLUDE = cached_patternprop(r"\w various artists \w", re.I)
    CLEAN_VA = cached_patternprop(
        r"""(^v[./]?a|\W*Various(?:\ Artists?)?)\b(?!\ [A-z])[^A-z(]*""",
        re.IGNORECASE,
    )
    COMPILATION_IN_TITLE = cached_patternprop(r"compilation|best of|anniversary", re.I)
    YEAR_RANGE = cached_patternprop(r"20[12]\d - 20[12]\d")

    original: str
    description: str
    from_track_titles: str | None

    remove_artists = True

    @cached_property
    def from_description(self) -> str | None:
        """Try finding album name in the release description."""
        if m := self.ALBUM_IN_DESC.search(self.description):
            self.remove_artists = False
            return m.group(1).strip()

        return None

    @cached_property
    def mentions_compilation(self) -> bool:
        return bool(self.COMPILATION_IN_TITLE.search(self.original))

    @cached_property
    def from_title(self) -> str | None:
        """Try to guess album name from the original title.

        Return the first match from below, defaulting to None:
        1. If 'EP' or 'LP' is in the original name, album name is what precedes it.
        2. If quotes are used in the title, they probably contain the album name.
        """
        if m := self.QUOTED_ALBUM.search(self.original):
            return m.expand(r"\2\3")

        return m.group() if (m := self.EPLP_ALBUM.search(self.original)) else None

    @cached_property
    def album_names(self) -> list[str]:
        priority_list = [
            self.from_track_titles,
            self.from_description,
            self.from_title,
            self.original,
        ]
        return list(filter(None, priority_list))

    @cached_property
    def name(self) -> str:
        return next(iter(self.album_names), "")

    @cached_property
    def series_part(self) -> str | None:
        """Return series if it is found in any of the album names."""
        for name in self.album_names:
            if m := self.SERIES.search(name):
                return m.group()

        return None

    @staticmethod
    def format_series(m: Match[str]) -> str:
        """Format the series part in an album.

        * Ensure 'Vol' or 'Pt' is suffixed by '.'
        * Ensure that it is followed by a space
        * Leading zeroes from the number are already removed by 'SERIES_FMT'.
        """
        album, series = m.groups()
        if album[0].isupper() and not series[0].isupper():
            series = series.capitalize()

        suffix = "." if len(series) in {2, 3} else ""
        return f"{album}{series}{suffix} "

    def standardize_series(self, album: str) -> str:
        """Standardize 'Vol', 'Part' etc. format."""
        if not (series := self.series_part):
            return album

        if series.lower() not in album.lower():
            # series found in the original name was not given in the description, but
            album += f", {series}"
        else:
            # move from the beginning to the end of the album
            album, moved = re.subn(rf"^({series})\W+(.+)", r"\2, \1", album)
            if not moved:
                # otherwise, ensure that it is delimited by a comma
                album = re.sub(rf"(?<=\w)( {series}(?!\)))", r",\1", album)

        return self.SERIES_FMT.sub(self.format_series, album)

    @classmethod
    def remove_va(cls, name: str) -> str:
        if not cls.CLEAN_VA_EXCLUDE.search(name):
            return cls.CLEAN_VA.sub(" ", name)

        return name

    @staticmethod
    def remove_pattern(name: str, pattern: str) -> str:
        allowed_chars = r"[*|,. \u2013\u2020]"
        return re.sub(
            rf"""
            (
                (?P<br>[([])                # match either an opening bracket/parens
              | (^|{allowed_chars})+        # and line start or any of the allowed chars
            )
            {pattern}
            (?(br)[])]                      # match closing brackets if they were opened
              | ({allowed_chars}|-|\d+$)*   # otherwise remove any of these chars
            )
            """,
            " ",
            name,
            flags=re.VERBOSE | re.IGNORECASE,
        ).strip("_: -")

    @classmethod
    def remove_label(cls, name: str, label: str) -> str:
        return cls.remove_pattern(
            name,
            rf"""
            (?<!\w[ ])          # cannot be preceded by a simple word
            \b{re.escape(label)}\b
            (?!:\ Vol)          # cannot be followed by ': Vol'
            (?!.[&#A-z])        # cannot be followed by a word
            """,
        )

    @classmethod
    def remove_artist(cls, name: str, artist: str) -> str:
        artist = re.escape(artist).replace(r",\ ", r"(,\ |\ [x&]\ )")
        return cls.remove_pattern(
            name,
            rf"""
            (?<!\ [x&,]\ )                      # keep B in 'A x B', 'A & B', 'A, B'
            (?<!\ (of|vs)\ )                    # keep B in 'A of B', 'A vs B'
            (((compiled\ |selected\ )?by)\ )?   # remove these prefixes if present
            {artist}                            # match the word we want to remove
            (\ x\ [^-]+)?                       # remove other artist ' x C' if present
            (?![':,.\w])                        # cannot be followed by these characters
            (?!\ [a-wyz&])                      # cannot be followed by ' &' ' ep'
            """,
        )

    @classmethod
    def remove_catalognum(cls, name: str, catalognum: str) -> str:
        return cls.remove_pattern(name, rf"{re.escape(catalognum)}(?!\ deluxe)")

    @classmethod
    def clean(
        cls,
        name: str,
        artists: list[str] | None = None,
        catalognum: str | None = None,
        label: str | None = None,
    ) -> str:
        """Return clean album name.

        Catalogue number and artists to be removed are provided as 'to_clean'.
        """
        name = Helpers.remove_ft(name)
        if catalognum:
            name = cls.remove_catalognum(name, catalognum)

        for artist in filter(None, artists or []):
            name = cls.remove_artist(name, artist)

        name = cls.remove_va(name)
        name = Helpers.clean_name(name)
        if label:
            name = cls.remove_label(name, label)
        name = cls.REMIX_IN_TITLE.sub(" ", name).strip("- ")

        # uppercase EP and LP, and remove surrounding parens / brackets
        name = cls.CLEAN_EPLP.sub(lambda x: x.group(1).upper(), name)
        return name.strip(" /")

    def find_artist(self, catalognum: str) -> str | None:
        album = self.original
        if self.YEAR_RANGE.match(album):
            return None

        album = self.clean(album, catalognum=catalognum)
        if remix := Remix.from_name(album):
            album = album.replace(remix.full, "").strip()

        if len(split := Track.DELIM_NOT_INSIDE_PARENS.split(album)) > 1:
            return split[0]

        return None

    def check_eplp(self, album: str) -> str:
        """Return album name followed by 'EP' or 'LP' if that's given in the comments.

        When album is given, search for the album.
        Otherwise, search for (Capital-case Album Name) (EP or LP) and return the match.
        """
        if album:
            m = re.search(rf"{re.escape(album)} [EL]P\b", self.description)
        else:
            m = self.EPLP_ALBUM_LINE.search(self.description)

        return m.group() if m else album

    def get(
        self,
        catalognum: str,
        original_artists: list[str],
        artists: list[str],
        label: str,
    ) -> str:
        original_album = self.name
        if artists and original_album.lower() == artists[0].lower():
            # if album is named by the main artist, keep it as it is
            return original_album

        artists_to_clean: Iterable[str] = []
        if self.remove_artists:
            artists_to_clean = filter(None, original_artists + artists)
        artists_to_clean = sorted(set(artists_to_clean), key=len, reverse=True)

        album = self.clean(
            original_album, artists=artists_to_clean, catalognum=catalognum, label=label
        )
        if album.startswith("("):
            album = original_album

        album = self.check_eplp(self.standardize_series(album))

        if "split ep" in album.lower() or (
            not album and len(artists) == self.SPLIT_RELEASE_ARTIST_COUNT
        ):
            album = " / ".join(artists)

        return album or catalognum or original_album
