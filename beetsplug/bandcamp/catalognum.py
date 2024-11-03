from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from itertools import starmap
from typing import Callable, Generic, Iterable, Pattern, Tuple, TypeVar

T = TypeVar("T")


class cached_classproperty(Generic[T]):
    def __init__(self, getter: Callable[..., T]) -> None:
        self.getter = getter
        self.cache: dict[type[object], T] = {}

    def __get__(self, instance: object, owner: type[object]) -> T:
        if owner not in self.cache:
            self.cache[owner] = self.getter(owner)

        return self.cache[owner]


def cached_patternprop(
    pattern: str, flags: int = 0
) -> cached_classproperty[Pattern[str]]:
    """Pattern is compiled and cached the first time it is accessed."""
    return cached_classproperty(lambda _: re.compile(pattern, flags))


@dataclass
class Catalognum:
    CONSTRAINT_TEMPLATE = r"""
    (?<![]/@.-])        # cannot be preceded by these characters
    (?<!by\ )
    (?:
      \b
      (?!(?i:vol|ep))   # exclude anything starting with 'vol' or 'ep'
      {}
      (?<!\bVA\d)       # cannot end with VA1
      (?<!\bVA\d\d)     # cannot end with VA01
      (?<!\bVA\d\d\d)   # cannot end with VA001
      (?<!\b20\d\d)     # cannot end with a year
      \b
      (?!["'%,-])       # cannot be followed by these characters
    )
    """
    MATCH = CONSTRAINT_TEMPLATE.format(
        r"""
    (?:
          (?<![A-Z].)[A-Z]{2,}\ 0\d{2}  # MNQ 049, SOP 063, SP 040
        | [A-Z]+[. ][A-Z]\d{3,}         # M.A025, HANDS D300
        | (?:                           # ROAD6, FREELAB9
          (?<!\ )[A-Z]{4,}\d(?!\.)  # not preceded by space
          |      [A-Z]{4,}\d(?=$)   # or at the end of the line
        )
        | \d*[A-Z$]{3,}[.-]?\d{3}       # EDLX.034, HEY-101, LI$INGLE025
        | [A-Z][A-z]{2,}0\d{2}          # Fabrik038, GiBS027, PSRL_001
        | [A-Z]{3,4}(?:CD)?[.!]?\d{2,}  # TAR30, NEN.39, ZENCD30, TMF!12
        | [A-Z]{2}\d{5}                 # RM12012, DD13109
        | [A-Z]{5}\d{2}                 # PNKMN18, LBRNM11
        | [A-Z]{6,}0\d{1}               # BODYHI01, DYNMCSS01
        | [A-z]+-[A-z]+[ ]?\d{2,}       # o-ton 119
        | [A-z]{2,3}-?0\d{2,}           # SS-023, mt001, src002
        | [A-z+]+[ ]?(?:(?i:[EL]P))\d+  # Dystopian LP01, a+w lp036
        | [a-z]+(?:cd|lp|:)\d+          # ostgutlp45, reni:7
        | [A-Z]+\d+[-_]\d{2,}           # P90-003, CC2_011
        | [A-Z]+_[A-Z]\d{1,3}           # PRL_S03
        | [A-Z]{2,}\d+[A-Z]\d{2,}       # SK11X015
        | [A-Z]{2}(?!999)\d{3}          # ST172
    )
    (?: # optionally followed by
        (?:[.-]\d+)?                    # .1 in RAWVA01.1RP, -1322 in SOP 063-1322
        (?:
            (?!MIX)
            (?<=\d\d)-?[A-Z]+           # CD in IBM001CD (needs two preceding digits)
          | RP                          # RP in RAWVA01.1RP
        )?
    )?
    """
    )
    LABEL_MATCH_TEMPLATE = CONSTRAINT_TEMPLATE.format(
        r"(?<!by\ )((?i:{}[ -]?[A-Z]*\d+([A-Z]|\.\d+)*))"
    )

    # Preceded by some variation of 'Catalogue number:'."""
    header = cached_patternprop(
        r"""
        # Cat. Number: ABC123
        # (a) 'Cat'
        # (b) '. Number:'
        # (c) ' '
        # (1) 'ABC123'
        ^
        (?i:cat     # (a) starts with 'cat' (ignoring case)
          (?:       # (b) optionally match '. Number:' or similar
            (?:\W|a?l)  # punctuation or 'l' or 'al', like 'Cat ', 'Catl', 'Catal'
            .*?         # anything
          )?
        )
        \W          # (c) some sort of punctuation preceding the catalogue number
        (           # (1) catalogue number group
          [A-Z\d]{2}    # must start with two capital letters/digits
          .*?           # lazy anything
          \w            # must end with an alphanumeric char
        )
        (\W\W|$)    # match as much as possible but stop before
                    # something like ' - All right reserved'
        """,
        re.M | re.VERBOSE,
    )
    # beginning or end of line
    start_end = cached_patternprop(rf"((^{MATCH})|({MATCH}$))", re.M | re.VERBOSE)
    # enclosed by parens or square brackets, but not ending with MIX
    delimited = cached_patternprop(rf"(?:[\[(])({MATCH})(?:[])]|$)", re.VERBOSE)
    # can possibly be followed up by a second catalogue number
    anywhere = cached_patternprop(rf"({MATCH}(?:\ [-/]\ {MATCH})?)", re.VERBOSE)
    in_album_pat = cached_patternprop(
        r"""
          (^\d*[A-Z]+\d+)(?::|\s[|-])\s # '^ABC123: ' or '^ABC123 - ' or '^ABC123 | '
          # or
        | \s[|-]\s([A-Z]+\d+$)          # ' - ABC123$' or ' | ABC123$'
          # or
        | [([]                          # just about anything within parens or brackets
          (?!Part|VA\b|LP\b)            # does not start with 'Part', 'VA', 'LP'
          ([^])]*[A-Z][^])]*\d+)        # at least one upper letter, ends with a digit
          [])]                          # closing bracket or parens
          (?!.*\[)                      # no bracket in the rest of the string
        """,
        re.VERBOSE,
    )

    label_suffix = cached_patternprop(
        r" (?:Records|Recordings|Productions|Music)$", re.I
    )
    punctuation = cached_patternprop(r"\W")

    release_description: str
    album: str
    label: str
    artists_and_titles: Iterable[str]

    @classmethod
    def from_album(cls, album: str) -> str | None:
        if m := cls.in_album_pat.search(album):
            return next(filter(None, m.groups()))

        return None

    @cached_property
    def label_variations(self) -> set[str]:
        """Return variations of the label name.

        This includes the label name without any punctuation and suffixes.
        """
        variations = {self.label, self.label_suffix.sub("", self.label)}
        variations |= {self.punctuation.sub("", v) for v in variations}

        return variations

    @cached_property
    def excluded_text(self) -> str:
        """Words that cannot be matched as a catalogue number."""
        return " ".join([*self.artists_and_titles, *self.label_variations]).lower()

    @cached_property
    def label_pattern(self) -> Pattern[str]:
        """Pattern to match catalogue numbers prefixed by the label name.

        Extend label variations with acronyms and the first word of the label.
        Return the pattern where each variation is OR'ed together.
        """
        prefixes = self.label_variations

        for prefix in [p for p in prefixes if " " in p]:
            acronym = "".join(word[0] for word in prefix.split())
            prefixes.add(acronym)

        if " " in self.label and len(first := self.label.split()[0]) > 1:
            # add the first word too
            prefixes.add(first)

        str_pattern = f"(?:{'|'.join(map(re.escape, prefixes))})"

        return re.compile(self.LABEL_MATCH_TEMPLATE.format(str_pattern), re.VERBOSE)

    @cached_property
    def in_album_or_release_description(self) -> str | None:
        """Return the catalogue number found in the album name or release description.

        This is defined as a cached property so that the search is performed once for
        a certain release.
        """
        return self.find([
            (self.anywhere, self.album),
            (self.label_pattern, self.album),
            (self.start_end, self.release_description),
            (self.anywhere, self.release_description),
            (self.label_pattern, self.release_description),
        ])

    def search(self, pat: Pattern[str], string: str) -> str | None:
        """Search text with the given pattern and return matching catalogue number.

        This returns the first match which is not in the excluded text.
        """
        if not string:
            return None

        for m in pat.finditer(string):
            catnum = m.group(1).strip()
            if catnum.lower() not in self.excluded_text:
                return catnum

        return None

    def find(
        self, patterns_and_texts: Iterable[Tuple[Pattern[str], str]]
    ) -> str | None:
        """Try getting the catalog number using supplied pattern/string pairs."""

        try:
            return next(filter(None, starmap(self.search, patterns_and_texts)))
        except StopIteration:
            return None

    def get(self, media_description: str) -> str | None:
        return (
            self.find([
                (self.header, media_description),
                (self.header, self.release_description),
                (self.anywhere, media_description),
                (self.label_pattern, media_description),
            ])
            or self.in_album_or_release_description
        )
