"""Module with bandcamp search functionality."""
import re
from difflib import SequenceMatcher
from html import unescape
from operator import itemgetter
from typing import Any, Callable, Dict, List

import requests

JSONDict = Dict[str, Any]
SEARCH_URL = "https://bandcamp.com/search?q={}"


def _f(field: str) -> str:
    """Return pattern matching a string that does not start with '<' or space
    until the end of the line.
    """
    return rf"(?P<{field}>[^ <][^\n]+)"


RELEASE_PATTERNS = [
    re.compile(r"itemtype..\n\s+" + _f("type")),
    re.compile(r"search_item_type=[^>]+>\n\s+" + _f("name")),
    re.compile(r"\n\s+genre: " + _f("genre")),
    re.compile(r"\n\s+from " + _f("album")),
    re.compile(r"\n\s+by " + _f("artist")),
    re.compile(r"\n\s+released " + _f("date")),
    re.compile(r"\n\s+(?P<tracks>\d+) tracks"),
    re.compile(
        r"""
(?P<url>
    https://
    (?:bandcamp[.])?
    (?P<label>(?!bandcamp|com)[^.]+)
    [.](?!bcbits)[\w/.-]+
)""",
        re.VERBOSE,
    ),
]


def to_ascii(string: str) -> str:
    """Lowercase and translate non-ascii chars to '?'."""
    return string.lower().encode("ascii", "replace").decode()


def get_similarity(a: str, b: str) -> float:
    """Return the similarity between two strings normalized to [0, 1].
    We take into account how well the result matches the query, e.g.
        query: "foo"
        result: "foo bar"
    Similarity is then:
        (2 * (len("foo") / len("foo")) + len("foo") / len("foo bar")) / 3
    2/3 of the result is how much of the query is found in the result,
    and 1/3 is a penalty for the non-matching part.
    """
    a, b = to_ascii(a), to_ascii(b)
    if not a or not b:
        return 0
    match = SequenceMatcher(a=a, b=b).find_longest_match(0, len(a), 0, len(b))
    return ((match.size / len(a)) * 2 + match.size / len(b)) / 3


def get_matches(text: str) -> JSONDict:
    """Reduce matches from all patterns into a single dictionary."""
    result: JSONDict = {}
    for pat in RELEASE_PATTERNS:
        for m in pat.finditer(text):
            result.update(m.groupdict())
    result["type"] = result["type"].lower()
    if "date" in result:
        result["date"] = " ".join(reversed(result["date"].split()))
    return result


def parse_and_sort_results(html: str, **kwargs: str) -> List[JSONDict]:
    """Given the html string, parse metadata for each entity and sort them
    by the field/value pairs given in kwargs.
    """
    results: List[JSONDict] = []
    for block in html.split("searchresult data-search")[1:]:
        similarities = []
        res = get_matches(block)
        for field, expected in kwargs.items():
            similarities.append(get_similarity(expected, res.get(field, "")))

        res["similarity"] = round(sum(similarities) / len(similarities), 3)
        results.append(res)
    results = sorted(results, key=itemgetter("similarity"), reverse=True)
    return [{"index": i + 1, **r} for i, r in enumerate(results)]


def get_bandcamp_url(url: str) -> str:
    response = requests.get(url)
    response.raise_for_status()
    return unescape(response.text)


def search_bandcamp(
    query: str = "",
    search_type: str = "",
    get: Callable[[str], str] = get_bandcamp_url,
    **kwargs,
) -> List[JSONDict]:
    """Return a list with item JSONs of type search_type matching the query.
    Bandcamp search may be unpredictable, therefore search results get sorted
    regarding their similarity to what's being queried.
    """
    url = SEARCH_URL.format(query)
    if search_type:
        url += "&item_type=" + search_type
    kwargs["name"] = query
    return parse_and_sort_results(get(url), **kwargs)
