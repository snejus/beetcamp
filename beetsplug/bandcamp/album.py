"""Module with album parsing logic."""
import sys
from dataclasses import dataclass
import re
from typing import List, Set, Dict, Any

from ._helpers import PATTERNS, Helpers

if sys.version_info.minor > 7:
    from functools import cached_property  # pylint: disable=ungrouped-imports
else:
    from cached_property import cached_property  # type: ignore # pylint: disable=import-error # noqa

JSONDict = Dict[str, Any]


@dataclass
class AlbumName:
    _series = r"(?i:\b(part|volume|pt|vol)\b\.?)"
    SERIES = re.compile(rf"{_series}[ ]?[A-Z\d.-]+\b")
    SERIES_FMT = re.compile(rf"^(.+){_series} *0*")
    INCL = re.compile(r"[^][\w]*inc[^()]+mix(es)?[^()-]*\W?", re.I)
    EPLP = re.compile(r"\S*(?:Double )?(\b[EL]P\b)\S*", re.I)

    meta: JSONDict
    description: str
    albums_in_titles: Set[str]

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
    def original(self) -> str:
        return self.meta.get("name") or ""

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
        for pat in [
            r"(((&|#?\b(?!Double|VA|Various)(\w|[^\w| -])+) )+[EL]P)",
            r"((['\"])([^'\"]+)\2( VA\d+)*)( |$)",
        ]:
            m = re.search(pat, album)
            if m:
                album = m.group(1).strip()
                return re.sub(r"^['\"](.+)['\"]$", r"\1", album)
        return album

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
            (?![ -][A-Za-z])  # cannot be followed by a word
            ([^[\]\w]|\d)*    # pick up any digits and punctuation
        """,
            flags=re.VERBOSE | re.IGNORECASE,
        )
        return pattern.sub(" ", name).strip()

    @classmethod
    def clean(cls, name: str, to_clean: List[str], label: str = "") -> str:
        """Return clean album name.

        Catalogue number and artists to be removed are provided as 'to_clean'.
        """
        name = PATTERNS["ft"].sub(" ", name)
        name = re.sub(r"^\[(.*)\]$", r"\1", name)

        escaped = [re.escape(x) for x in filter(None, to_clean)] + [
            r"Various Artists?\b(?! [A-z])( \d+)?"
        ]
        for arg in escaped:
            name = re.sub(rf" *(?i:(compiled )?by|vs|\W*split w) {arg}", "", name)
            if not re.search(rf"\w {arg} \w|of {arg}", name, re.I):
                name = re.sub(
                    rf"(^|[^'\])\w]|_|\b)+(?i:{arg})([^'(\[\w]|_|(\d+$))*", " ", name
                ).strip()

        name = cls.remove_label(Helpers.clean_name(name), label)
        name = cls.INCL.sub("", name).strip("- ")

        # uppercase EP and LP, and remove surrounding parens / brackets
        name = cls.EPLP.sub(lambda x: x.group(1).upper(), name)
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

        m = re.search(rf"{look_for}[EL]P", self.description)
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

        album = self.clean(album, sorted(to_clean, key=len, reverse=True), label)
        if album.startswith("("):
            album = self.name

        album = self.check_eplp(self.standardize_series(album))

        if "split ep" in album.lower() or (not album and len(artists) == 2):
            album = " / ".join(artists)

        return album or catalognum or self.name
