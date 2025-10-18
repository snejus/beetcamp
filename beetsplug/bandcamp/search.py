"""Module with bandcamp search functionality."""

from __future__ import annotations

import difflib
import re
from operator import itemgetter
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

from beetsplug.bandcamp.http import http_get_text

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any, Literal

    from typing_extensions import LiteralString, TypeAlias

    JSONDict = dict[str, Any]

    SearchType: TypeAlias = Literal["a", "t"]

SEARCH_URL: LiteralString = "https://bandcamp.com/search?page={}&q={}"


def _f(field: str) -> str:
    """Return pattern matching a string that does not start with '<' or space.

    Match until the end of the line.
    """
    return rf"(?P<{field}>[^\s<][^\n]+)"


RELEASE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"itemtype..\n\s+" + _f("type")),
    re.compile(r"search_item_type=[^>]+>\n\s+" + _f("name")),
    re.compile(r"\n\s+genre: " + _f("genre")),
    re.compile(r"\n\s+from " + _f("album")),
    re.compile(r"\n\s+by " + _f("artist")),
    re.compile(r"\n\s+released " + _f("date")),
    re.compile(r"\n\s+(?P<tracks>\d+) tracks"),
    re.compile(r">https://bandcamp\.(?P<label>[^.<]+)\.[^<]+<"),
    re.compile(r">https://(?P<label>[^.]+)\.bandcamp\.[^<]+<"),
    re.compile(r">https://(?P<label>(?!bandcamp)[^/]+)\.[^<]+<"),
    re.compile(r">(?P<url>https://[^<]+)<"),
]


def to_ascii(string: str) -> str:
    """Lowercase and translate non-ascii chars to '?'."""
    return string.lower().encode("ascii", "replace").decode()


def get_similarity(query: str, result: str) -> float:
    """Return the similarity between two strings normalized to [0, 1].

    We take into account how well the result matches the query, e.g.
        query: "foobar"
        result: "foo bar"
    Similarity is then:
        (2 * (len("foo") / len("foobar")) + len("foo") / len("foo bar")) / 3

    2/3 of the weight is how much of the query is found in the result,
    and 1/3 is a penalty for the non-matching part.
    """
    a: str
    b: str
    a, b = to_ascii(query), to_ascii(result)
    if not a or not b:
        return 0
    m: difflib.Match = difflib.SequenceMatcher(a=a, b=b).find_longest_match(
        0, len(a), 0, len(b)
    )
    return ((m.size / len(a)) * 2 + m.size / len(b)) / 3


def get_matches(text: str) -> JSONDict:
    """Reduce matches from all patterns into a single dictionary."""
    result: JSONDict = {}
    pat: re.Pattern[str]
    for pat in RELEASE_PATTERNS:
        m: re.Match[str] | None
        if m := pat.search(text):
            result = {**m.groupdict(), **result}
    if "type" in result:
        result["type"] = result["type"].lower()
    if "date" in result:
        result["date"] = " ".join(reversed(result["date"].split()))
    return result


def parse_and_sort_results(html: str, **kwargs: str) -> list[JSONDict]:
    """Extract search results from `html` and sort them by similarity to kwargs.

    Bandcamp search may be unpredictable, therefore search results get sorted
    regarding their similarity to what's being queried.

    `kwargs` contains field and value pairs we compare the results with. Usually,
    this has 'label', 'artist' and 'name' ('title' or 'album') fields.
    """
    results: list[JSONDict] = []
    block: str
    for block in html.split("searchresult data-search")[1:]:
        res: JSONDict = get_matches(block)
        similarities: list[float] = [
            get_similarity(query, res.get(field, "")) for field, query in kwargs.items()
        ]
        res["similarity"] = round(sum(similarities) / len(similarities), 3)
        results.append(res)
    results = sorted(results, key=itemgetter("similarity"), reverse=True)
    return [{"index": i + 1, **r} for i, r in enumerate(results)]


def search_bandcamp(
    query: str | None = None,
    search_type: SearchType | None = None,
    page: int | None = None,
    get: Callable[[str], str] | None = None,
    **kwargs: str,
) -> list[JSONDict]:
    """Return a list with item JSONs of type search_type matching the query."""
    if page is None:
        page = 1
    if get is None:
        get = http_get_text
    if not query:
        query = " - ".join(filter(None, [kwargs.get("artist"), kwargs.get("name")]))
    _ = kwargs.setdefault("name", query)
    url: str = SEARCH_URL.format(page, quote_plus(string=query))
    if search_type:
        url += f"&item_type={search_type}"
    return parse_and_sort_results(get(url), **kwargs)
