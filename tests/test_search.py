"""Tests for searching functionality."""

from typing import Any

import pytest

from beetcamp.search import search_bandcamp, sort_results


@pytest.fixture
def result_data():
    return {
        "name": "Release",
        "url": "https://label.bandcamp.com/album/release",
        "artist": "Artist",
        "label": "label",
        "type": "album",
    }


@pytest.fixture
def make_results(result_data):
    def build_results(names: list[str]) -> list[dict[str, Any]]:
        return [
            {
                **result_data,
                "name": name,
                "url": (
                    f"https://label.bandcamp.com/album/{name.lower().replace(' ', '-')}"
                ),
            }
            for name in names
        ]

    return build_results


def test_search_logic(make_results):
    """A matching release has the maximum similarity."""
    results = make_results(["Release"])

    assert sort_results(results, artist="Artist", name="Release") == [
        {**results[0], "index": 1, "similarity": 1.0}
    ]


def test_search_prioritises_best_matches(make_results):
    """Search results are sorted by similarity."""
    results = make_results(
        ["Specific Release", "Specific Release With Long Name", "Release"]
    )

    assert sort_results(results, artist="Artist", name="Specific Release") == [
        {**results[0], "index": 1, "similarity": 1.0},
        {**results[1], "index": 2, "similarity": 0.919},
        {**results[2], "index": 3, "similarity": 0.812},
    ]


def test_search_bandcamp(monkeypatch):
    api = {
        "auto": {
            "results": [
                {
                    "type": "a",
                    "name": "Black Sands",
                    "band_name": "Bonobo",
                    "item_url_root": "https://bonobomusic.bandcamp.com",
                    "item_url_path": "https://bonobomusic.bandcamp.com/album/black-sands",
                },
                {
                    "type": "b",
                    "name": "Bonobo",
                    "is_label": False,
                    "item_url_root": "https://bonobomusic.bandcamp.com",
                    "item_url_path": None,
                },
                {
                    "type": "b",
                    "name": "Bonobo Label",
                    "is_label": True,
                    "item_url_root": "https://bonobolabel.bandcamp.com",
                    "item_url_path": None,
                },
            ]
        }
    }
    monkeypatch.setattr(
        "beetcamp.json_search.http_post_json", lambda *_args, **_kwargs: api
    )

    assert search_bandcamp(None, query="bonobo") == [
        {
            "index": 1,
            "type": "artist",
            "name": "Bonobo",
            "url": "https://bonobomusic.bandcamp.com",
            "label": "bonobomusic",
            "artist": None,
            "genre": None,
            "tags": None,
            "similarity": 1.0,
        },
        {
            "index": 2,
            "type": "label",
            "name": "Bonobo Label",
            "url": "https://bonobolabel.bandcamp.com",
            "label": "bonobolabel",
            "artist": None,
            "genre": None,
            "tags": None,
            "similarity": 0.833,
        },
        {
            "index": 3,
            "type": "album",
            "name": "Black Sands",
            "url": "https://bonobomusic.bandcamp.com/album/black-sands",
            "label": "bonobomusic",
            "artist": "Bonobo",
            "genre": None,
            "tags": None,
            "similarity": 0.571,
        },
    ]
