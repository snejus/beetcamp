from __future__ import annotations

from typing import Any, Literal, TypedDict
from urllib.parse import urlparse

from typing_extensions import NotRequired

from .http import http_post_json

SEARCH_API_URL = "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic"
SEARCH_TYPE_TO_FILTER = {"a": "a", "b": "b", "t": "t"}

JSONDict = dict[str, Any]
SearchTypeCode = Literal["a", "b", "f", "t"]
ResultType = Literal["album", "fan", "label", "track"]
TYPE_BY_CODE: dict[str, ResultType] = {
    "a": "album",
    "b": "label",
    "f": "fan",
    "t": "track",
}


class BandcampSearchBase(TypedDict):
    id: int
    name: str
    item_url_root: str
    img: str | None
    img_id: int | None
    art_id: int | None
    stat_params: str


class BandcampAlbumSearch(BandcampSearchBase):
    type: Literal["a"]
    band_id: int
    band_name: str
    item_url_path: str
    tag_names: list[str] | None


class BandcampLabelSearch(BandcampSearchBase):
    type: Literal["b"]
    is_label: bool
    location: NotRequired[str | None]
    genre_name: NotRequired[str | None]
    tag_names: list[str] | None


class BandcampTrackSearch(BandcampSearchBase):
    type: Literal["t"]
    band_id: int
    band_name: str
    album_id: int | None
    album_name: str | None
    item_url_path: str


class BandcampFanSearch(BandcampSearchBase):
    type: Literal["f"]
    collection_size: int
    genre_name: NotRequired[str | None]
    image_id: NotRequired[int | None]
    username: str


BandcampSearchResult = (
    BandcampAlbumSearch | BandcampLabelSearch | BandcampTrackSearch | BandcampFanSearch
)


class BandcampSearchAutoResponse(TypedDict, total=False):
    stat_params_for_tag: str
    time_ms: int
    ac_error: bool
    results: list[BandcampSearchResult]


class BandcampSearchResponse(TypedDict, total=False):
    auto: BandcampSearchAutoResponse
    genre: JSONDict
    tag: JSONDict
    __api_special__: str
    error_type: str


class BandcampSearchRequest(TypedDict):
    search_text: str
    search_filter: str
    fan_id: int | None
    full_page: bool


class SearchResult(TypedDict, total=False):
    type: ResultType
    name: str
    label: str
    url: str
    artist: str | None
    genre: str | None
    album: str | None
    date: str | None
    tracks: str | None
    tags: list[str] | None


def _guess_label(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    parts = host.split(".")
    if host.startswith("bandcamp.") and "." in host.removeprefix("bandcamp."):
        return parts[1]
    if ".bandcamp." in host:
        return host.split(".bandcamp.")[0]
    return host.split(".")[0] if host else ""


def _api_result_to_release(result: BandcampSearchResult) -> SearchResult:
    url = str(result.get("item_url_path") or result.get("item_url_root"))
    result_type = TYPE_BY_CODE[result["type"]]
    return {
        "type": result_type,
        "name": result["name"],
        "label": _guess_label(url),
        "url": url,
        "artist": result.get("band_name"),  # type: ignore[typeddict-item]
        "genre": result.get("genre_name"),  # type: ignore[typeddict-item]
        "tags": result.get("tag_names"),  # type: ignore[typeddict-item]
    }


def search_json(query: str, search_type: str) -> list[SearchResult]:
    payload: BandcampSearchRequest = {
        "search_text": query,
        "search_filter": SEARCH_TYPE_TO_FILTER.get(search_type, ""),
        "fan_id": None,
        "full_page": True,
    }
    response: BandcampSearchResponse = http_post_json(SEARCH_API_URL, json=payload)
    raw_results = response["auto"]["results"]
    return list(filter(None, map(_api_result_to_release, raw_results)))
