"""Module with bandcamp search functionality."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from operator import itemgetter
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote_plus

from .http import http_get_text
from .json_search import SearchResult, search_json

if TYPE_CHECKING:
    from collections.abc import Callable


JSONDict = dict[str, Any]
SEARCH_URL = "https://bandcamp.com/search?page={}&q={}"


def _f(field: str) -> str:
    """Return pattern matching a string that does not start with '<' or space.

    Match until the end of the line.
    """
    return rf"(?P<{field}>[^\s<][^\n]+)"


RELEASE_PATTERNS = [
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
    a, b = to_ascii(query), to_ascii(result)
    if not a or not b:
        return 0
    m = SequenceMatcher(a=a, b=b).find_longest_match(0, len(a), 0, len(b))
    return ((m.size / len(a)) * 2 + m.size / len(b)) / 3


def get_matches(text: str) -> SearchResult:
    """Reduce matches from all patterns into a single dictionary."""
    result: JSONDict = {}
    for pat in RELEASE_PATTERNS:
        if m := pat.search(text):
            result = {**m.groupdict(), **result}
    if "type" in result:
        result["type"] = result["type"].lower()
    if "date" in result:
        result["date"] = " ".join(reversed(result["date"].split()))
    return result  # type: ignore[return-value]


def parse_html_results(html: str) -> list[SearchResult]:
    """Extract search results from `html` and sort them by similarity to kwargs.

    Bandcamp search may be unpredictable, therefore search results get sorted
    regarding their similarity to what's being queried.

    `kwargs` contains field and value pairs we compare the results with. Usually,
    this has 'label', 'artist' and 'name' ('title' or 'album') fields.
    """
    return list(map(get_matches, html.split("searchresult data-search")[1:]))


class IndexedSearchResult(SearchResult):
    index: int
    similarity: float


def sort_results(
    results: list[SearchResult], **kwargs: str
) -> list[IndexedSearchResult]:
    """Sort search results by similarity to query fields."""
    for result in cast("list[IndexedSearchResult]", results):
        comp = kwargs.copy()
        if result["type"] in {"track", "album"} and (query := kwargs.get("name")):
            comp.setdefault("artist", query)

        similarities = [
            get_similarity(query, result.get(field) or "")  # type: ignore[arg-type]
            for field, query in comp.items()
        ]
        result["similarity"] = round(sum(similarities) / len(similarities), 3)
    results = sorted(results, key=itemgetter("similarity"), reverse=True)
    return [{"index": i + 1, **r} for i, r in enumerate(results)]  # type: ignore[typeddict-item]


def search_bandcamp(
    query: str = "",
    search_type: str = "",
    page: int = 1,
    get: Callable[[str], str] = http_get_text,
    **kwargs: Any,
) -> list[IndexedSearchResult]:
    """Return a list with item JSONs of type search_type matching the query."""
    query = query or " - ".join(
        filter(None, [kwargs.get("artist"), kwargs.get("name")])
    )
    kwargs.setdefault("name", query)
    if page == 1:
        results = search_json(query, search_type)
    else:
        url = SEARCH_URL.format(page, quote_plus(query))
        if search_type:
            url += f"&item_type={search_type}"

        results = parse_html_results(get(url))

    return sort_results(results, **kwargs)
