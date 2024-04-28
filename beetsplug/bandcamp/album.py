"""Module with album parsing logic."""

import re
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Dict, List, Set

from .helpers import PATTERNS, Helpers

JSONDict = Dict[str, Any]


@dataclass
class AlbumName:
    _series = r"(?i:\b(part|volume|pt|vol)\b\.?)"
    SERIES = re.compile(rf"{_series}[ ]?[A-Z\d.-]+\b")
    SERIES_FMT = re.compile(rf"^(.+){_series} *0*")
    INCL = re.compile(r"[^][\w]*inc[^()]+mix(es)?[^()-]*\W?", re.I)
    CLEAN_EPLP = re.compile(r"(?:[([]|Double ){0,2}(\b[EL]P\b)\S?", re.I)
    EPLP_ALBUM = re.compile(
        r"\b((?:(?!VA|Various|-)[^: ]+ )+)([EL]P(?! *\d)(?: [\w#][^ ]+$)?)"
    )
    IN_QUOTES = re.compile(r"((['\"])([^'\"]+)\2( VA\d+)*)( |$)")
    WITHOUT_QUOTES = re.compile(r"^['\"](.+)['\"]$")
    CLEAN_VA_EXCLUDE = re.compile(r"\w various artists \w", re.I)
    CLEAN_VA = re.compile(
        r"""
          (?<=^)v/?a\b(?!\ \w)[^A-z(]*
        | \W*Various\ Artists?\b(?!\ [A-z])[^A-z(]*
    """,
        re.IGNORECASE + re.VERBOSE,
    )

    original: str
    description: str
    from_track_titles: Optional[str]

    remove_artists = True

    @cached_property
    def in_description(self) -> str:
        """Check description for the album name header and return whatever follows it
        if found.
        """
        m = re.search(r"(Title: ?|Album(:|/Single) )([^\n]+)", self.description)
        if m:
            self.remove_artists = False
            return m.group(3).strip()
        return ""

    @cached_property
    def mentions_compilation(self) -> bool:
        return bool(re.search(r"compilation|best of|anniversary", self.original, re.I))

    @cached_property
    def parsed(self) -> str:
        """
        Search for the album name in the following order and return the first match:
        1. Album name is found in *all* track names
        2. When 'EP' or 'LP' is in the release name, album name is what precedes it.
        3. If some words are enclosed in quotes in the release name, it is assumed
           to be the album name. Remove the quotes in such case.
        """
        if len(self.albums_in_titles) == 1:
            return next(iter(self.albums_in_titles))

        album = self.original
        m = self.EPLP_ALBUM.search(album)
        if m:
            album = " ".join(i.strip(" '") for i in m.groups())
        else:
            m = self.IN_QUOTES.search(album)
            if m:
                album = m.group(1)

        return self.WITHOUT_QUOTES.sub(r"\1", album)

    @cached_property
    def album_sources(self) -> List[str]:
        return list(filter(None, [self.in_description, self.parsed, self.original]))

    @cached_property
    def name(self) -> str:
        return self.in_description or self.parsed or self.original

    @cached_property
    def series(self) -> str:
        m = self.SERIES.search("\n".join(self.album_sources))
        return m.group() if m else ""

    @staticmethod
    def format_series(m: re.Match) -> str:  # type: ignore[type-arg]
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
        series = self.series
        if not series:
            return album

        if series.lower() not in album.lower():
            # series was not given in the description, but found in the original name
            if series[0].isalpha():
                series = f", {series}"

            album += series
        else:
            # move from the beginning to the end of the album
            album, moved = re.subn(rf"^({series})\W+(.+)", r"\2, \1", album)
            if not moved:
                # otherwise, ensure that it is delimited by a comma
                album = re.sub(rf"(?<=\w)( {series}(?!\)))", r",\1", album)

        return self.SERIES_FMT.sub(self.format_series, album)

    @staticmethod
    def remove_label(name: str, label: str) -> str:
        if not label:
            return name

        pattern = re.compile(
            rf"""
            \W*               # pick up any punctuation
            (?<!\w[ ])        # cannot be preceded by a simple word
            \b{re.escape(label)}\b
            (?!'|[ -][A-Za-z])  # cannot be followed by a word
            ([^[\]\w]|\d)*    # pick up any digits and punctuation
        """,
            flags=re.VERBOSE | re.IGNORECASE,
        )
        return pattern.sub(" ", name).strip()

    @classmethod
    def remove_va(cls, name: str) -> str:
        if not cls.CLEAN_VA_EXCLUDE.search(name):
            return cls.CLEAN_VA.sub(" ", name)

        return name

    @classmethod
    def clean(cls, name: str, to_clean: List[str], label: str = "") -> str:
        """Return clean album name.

        Catalogue number and artists to be removed are provided as 'to_clean'.
        """
        name = PATTERNS["ft"].sub(" ", name)
        name = re.sub(r"^\[(.*)\]$", r"\1", name)

        for w in map(re.escape, filter(None, to_clean)):
            name = re.sub(rf" *(?i:(compiled )?by|vs|\W*split w) {w}", "", name)
            if not re.search(
                rf"\w {w} \w|(of|&) {w}|{w}(['_\d]| (deluxe|[el]p\b|&))", name, re.I
            ):
                name = re.sub(
                    rf"""
    (?<! x )
    (^|[^\])\w])+
    (?i:{w})
    ([^(\[\w]| _|(\d+$))*
                    """,
                    " ",
                    name,
                    flags=re.VERBOSE,
                ).strip()

        name = cls.remove_va(name)
        name = cls.remove_label(Helpers.clean_name(name), label)
        name = cls.INCL.sub("", name).strip("- ")

        # uppercase EP and LP, and remove surrounding parens / brackets
        name = cls.CLEAN_EPLP.sub(lambda x: x.group(1).upper(), name)
        return name.strip(" /")

    def check_eplp(self, album: str) -> str:
        """Return album name followed by 'EP' or 'LP' if that's given in the comments.

        When album is given, search for the album.
        Otherwise, search for (Capital-case Album Name) (EP or LP) and return the match.
        """
        if album:
            look_for = re.escape(f"{album} ")
        else:
            look_for = r"((?!The|This)\b[A-Z][^ \n]+\b )+"

        m = re.search(rf"{look_for}[EL]P\b", self.description)
        return m.group() if m else album

    def get(
        self,
        catalognum: str,
        original_artists: List[str],
        artists: List[str],
        label: str,
    ) -> str:
        album = self.name
        to_clean = [catalognum]
        if self.remove_artists:
            to_clean.extend(original_artists + artists)
        to_clean = sorted(filter(None, set(to_clean)), key=len, reverse=True)

        album = self.clean(album, to_clean, label)
        if album.startswith("("):
            album = self.name

        album = self.check_eplp(self.standardize_series(album))

        if "split ep" in album.lower() or (not album and len(artists) == 2):
            album = " / ".join(artists)

        return album or catalognum or self.name
