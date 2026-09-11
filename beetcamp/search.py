"""Module with bandcamp search functionality."""

from __future__ import annotations

from difflib import SequenceMatcher
from operator import itemgetter
from typing import TYPE_CHECKING, TypedDict, cast

from typing_extensions import NotRequired, Unpack

from .json_search import SearchResult, search_json

if TYPE_CHECKING:
    from .json_search import SearchTypeCode


class SearchFilters(TypedDict):
    artist: NotRequired[str]
    name: NotRequired[str]


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


class IndexedSearchResult(SearchResult):
    index: int
    similarity: float


def sort_results(
    results: list[SearchResult], **kwargs: Unpack[SearchFilters]
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
    search_type: SearchTypeCode | None,
    query: str | None = None,
    **kwargs: Unpack[SearchFilters],
) -> list[IndexedSearchResult]:
    """Return a list with item JSONs of type search_type matching the query."""
    query = query or " - ".join(
        filter(None, [kwargs.get("artist"), kwargs.get("name")])
    )
    kwargs.setdefault("name", query)
    results = search_json(query, search_type)

    return sort_results(results, **kwargs)
