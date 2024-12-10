"""Module with bandcamp search functionality."""

import re
from collections.abc import Callable
from difflib import SequenceMatcher
from operator import itemgetter
from typing import Any
from urllib.parse import quote_plus

from .http import http_get_text

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


def get_matches(text: str) -> JSONDict:
    """Reduce matches from all patterns into a single dictionary."""
    result: JSONDict = {}
    for pat in RELEASE_PATTERNS:
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
    for block in html.split("searchresult data-search")[1:]:
        res = get_matches(block)
        similarities = [
            get_similarity(query, res.get(field, "")) for field, query in kwargs.items()
        ]
        res["similarity"] = round(sum(similarities) / len(similarities), 3)
        results.append(res)
    results = sorted(results, key=itemgetter("similarity"), reverse=True)
    return [{"index": i + 1, **r} for i, r in enumerate(results)]


def search_bandcamp(
    query: str = "",
    search_type: str = "",
    page: int = 1,
    get: Callable[[str], str] = http_get_text,
    **kwargs: Any,
) -> list[JSONDict]:
    """Return a list with item JSONs of type search_type matching the query."""
    url = SEARCH_URL.format(page, quote_plus(query))
    if search_type:
        url += f"&item_type={search_type}"
    kwargs["name"] = query
    return parse_and_sort_results(get(url), **kwargs)
