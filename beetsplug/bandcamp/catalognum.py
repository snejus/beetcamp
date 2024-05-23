from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from itertools import starmap
from typing import Callable, Generic, Pattern, Tuple, TypeVar

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
    (?<![]/@-])         # cannot be preceded by these characters
    (?<!by\ )
    (
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
    (
          (?<![A-Z].)[A-Z]{2,}\ 0\d{2}  # MNQ 049, SOP 063, SP 040
        | [A-Z]+[. ][A-Z]\d{3,}         # M.A025, HANDS D300
        | [A-Z]{4,}\d(?!\.)             # ROAD6, FREELAB9
        | \d*[A-Z$]{3,}[.-]?\d{3}       # EDLX.034, HEY-101, LI$INGLE025
        | [A-Z][A-z]{2,}0\d{2}          # Fabrik038, GiBS027, PSRL_001
        | [A-Z]{3,4}(CD)?\.?\d{2,}      # TAR30, NEN.39, ZENCD30
        | [A-Z]{2}\d{5}                 # RM12012, DD13109
        | [A-Z]{5}\d{2}                 # PNKMN18, LBRNM11
        | [A-Z]{6,}0\d{1}               # BODYHI01, DYNMCSS01
        | [A-z]+-[A-z]+[ ]?\d{2,}       # o-ton 119
        | [A-z]{2,3}-?0\d{2,}           # SS-023, mt001, src002
        | [A-z+]+[ ]?(?:(?i:[EL]P))\d+  # Dystopian LP01, a+w lp036
        | [a-z]+(?:cd|lp|:)\d+          # ostgutlp45, reni:7
        | [A-Z]+\d+[-_]\d{2,}           # P90-003, CC2_011
        | [A-Z]+_[A-Z]\d{1,3}           # PRL_S03
    )
    (?: # optionally followed by
        ([.-]\d+)?                      # .1 in RAWVA01.1RP, -1322 in SOP 063-1322
        (
            (?<=\d\d)-?[A-Z]+           # CD in IBM001CD (needs at least two preceding digits)
          | RP                          # RP in RAWVA01.1RP
        )?
    )?
    """
    )
    LABEL_MATCH_TEMPLATE = CONSTRAINT_TEMPLATE.format(
        r"(?<!by\ )(?i:{}[ -]?[A-Z]*\d+([A-Z]|\.\d+)*)"
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
    delimited = cached_patternprop(rf"(?:[\[(])(?!.*MIX){MATCH}(?:[])]|)$", re.VERBOSE)
    # can possibly be followed up by a second catalogue number
    anywhere = cached_patternprop(rf"({MATCH}(\ [/-]\ {MATCH})?)", re.VERBOSE)

    @classmethod
    @lru_cache
    def for_label(cls, label: str) -> Pattern[str]:
        prefixes = {label}
        endings = "Records", "Recordings", "Productions"
        prefixes |= {label.replace(f" {e}", "") for e in endings}

        for prefix in [p for p in prefixes if " " in p]:
            # add concatenated first letters
            prefixes.add("".join(word[0] for word in prefix.split()))

        if " " in label:
            # add the first word too
            prefixes.add(label.split()[0])

        str_pattern = f"(?:{'|'.join(map(re.escape, prefixes))})"

        return re.compile(cls.LABEL_MATCH_TEMPLATE.format(str_pattern), re.VERBOSE)

    @staticmethod
    @lru_cache(maxsize=None)
    def find(
        cases: Tuple[Tuple[Pattern[str], str], ...], label: str, artistitles: str
    ) -> str:
        """Try getting the catalog number using supplied pattern/string pairs."""

        label = label.lower()

        def find(pat: Pattern[str], string: str) -> str:
            """Return the match.

            It is legitimate if it is
            * not found in any of the track artists or titles
            * made of the label name when it has a space and is shorter than 6 chars
            """
            for m in pat.finditer(string):
                catnum = m.group(1).strip()
                if (
                    catnum.lower()
                    not in f"{artistitles}{label}{label.replace(' ', '')}"
                ):
                    return catnum
            return ""

        try:
            return next(filter(None, starmap(find, cases)))
        except StopIteration:
            return ""
