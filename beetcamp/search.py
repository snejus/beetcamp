"""Module with bandcamp search functionality."""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from operator import itemgetter
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus, urlsplit

from .http import http_get_text, http_post_json

if TYPE_CHECKING:
    from collections.abc import Callable

JSONDict = dict[str, Any]
SEARCH_URL = "https://bandcamp.com/search?page={}&q={}"
# The JSON endpoint bandcamp's own search box uses. The HTML page at SEARCH_URL is behind a
# JavaScript "Client Challenge" which a scraper cannot solve, so it returns a challenge stub
# with no results and searching silently yields nothing. See #99.
SEARCH_API_URL = "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic"
# Map the API's terse item types onto the words the HTML search page used.
ITEM_TYPES = {"a": "album", "t": "track", "b": "band", "f": "fan"}

log = logging.getLogger(__name__)


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
    return sort_results(
        [get_matches(block) for block in html.split("searchresult data-search")[1:]],
        **kwargs,
    )


def sort_results(results: list[JSONDict], **kwargs: str) -> list[JSONDict]:
    """Sort results by their similarity to the queried fields and index them.

    Shared by both search backends so ranking does not depend on where the rows came from.
    """
    for res in results:
        similarities = [
            get_similarity(query, res.get(field, "")) for field, query in kwargs.items()
        ]
        res["similarity"] = round(sum(similarities) / len(similarities), 3)
    results = sorted(results, key=itemgetter("similarity"), reverse=True)
    return [{"index": i + 1, **r} for i, r in enumerate(results)]


def api_results(query: str, search_type: str = "") -> list[JSONDict]:
    """Return search results from bandcamp's public JSON search API.

    Rows are mapped onto the same keys the HTML parser produced, so callers and the
    similarity scoring do not need to know which backend answered. `album`, `date` and
    `tracks` are not exposed by this endpoint; they are only used for scoring and display,
    and every read of them is a `.get(field, "")`, so their absence is harmless.
    """
    payload = {
        "fan_id": None,
        "full_page": False,
        "search_filter": search_type,
        "search_text": query,
    }
    data = http_post_json(SEARCH_API_URL, payload)
    # The API answers HTTP 200 with an error body rather than a failure status, and an
    # unrecognised shape would otherwise yield an empty list -- i.e. exactly the silent
    # "no results" that hid the broken HTML scrape. Raise so the caller warns and falls back.
    if data.get("error"):
        raise ValueError(
            f"bandcamp search API error: {data.get('error_message', 'unknown')}"
        )
    if "auto" not in data:
        raise ValueError(f"unexpected bandcamp search API response: {sorted(data)[:5]}")

    results = []
    for item in (data.get("auto") or {}).get("results") or []:
        url = item.get("item_url_path") or ""
        if not url:
            continue
        res: JSONDict = {
            "type": ITEM_TYPES.get(item.get("type", ""), item.get("type", "")),
            "name": item.get("name") or "",
            "artist": item.get("band_name") or "",
            "url": url,
            # The HTML page exposed the label as the bandcamp subdomain; derive the same.
            "label": (urlsplit(item.get("item_url_root") or url).hostname or "").split(
                "."
            )[0],
        }
        # The API sends the *string* "None" rather than null when there are no tags.
        if (genre := item.get("tag_names")) and genre != "None":
            res["genre"] = genre
        results.append(res)
    return results


def search_bandcamp(
    query: str = "",
    search_type: str = "",
    page: int = 1,
    get: Callable[[str], str] = http_get_text,
    **kwargs: Any,
) -> list[JSONDict]:
    """Return a list with item JSONs of type search_type matching the query."""
    query = query or " - ".join(
        filter(None, [kwargs.get("artist"), kwargs.get("name")])
    )
    kwargs.setdefault("name", query)

    # Prefer the JSON API: the HTML search page is behind a JavaScript "Client Challenge"
    # that a scraper cannot solve, so it yields no results at all (#99).
    try:
        return sort_results(api_results(query, search_type), **kwargs)
    except Exception:
        # Say so. This failing quietly is what let the broken HTML scrape go unnoticed.
        log.warning(
            "bandcamp search API request failed, falling back to scraping the search page"
            " (which is likely to return nothing while it is behind a client challenge)",
            exc_info=True,
        )

    url = SEARCH_URL.format(page, quote_plus(query))
    if search_type:
        url += f"&item_type={search_type}"
    return parse_and_sort_results(get(url), **kwargs)
