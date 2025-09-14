"""Tests for searching functionality."""

from typing import Any

import pytest

from beetsplug.bandcamp.http import urlify
from beetsplug.bandcamp.search import get_matches, search_bandcamp

# simplified version of the search result HTML block
HTML_ITEM = """
<div class="searchresult data-search">
https://www.recaptcha.net/recaptcha/enterprise.js
<a href="{url}?from=search">{url}</a>
search_item_type="a">
     {name}
     <span>some
     other stuff</span>
  by {artist}
  <div class="released">
      released {date}
  </div>
  <div class="itemtype">
  ALBUM
  </div>
</div>
"""


def make_html_item(data):
    return HTML_ITEM.format(**data, date="2021 November 26")


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
def make_html_with_results(result_data):
    def make(
        names: list[str], similarities: list[float]
    ) -> tuple[str, list[dict[str, Any]]]:
        results = [
            {
                **result_data,
                "name": n,
                "url": f"https://label.bandcamp.com/album/{urlify(n)}",
            }
            for n in names
        ]
        html = "\n".join(map(make_html_item, results))
        expected_results = [
            {**r, "date": "26 November 2021", "index": idx, "similarity": s}
            for idx, (r, s) in enumerate(zip(results, similarities), 1)
        ]
        return html, expected_results

    return make


def test_search_logic(make_html_with_results):
    """Given a single matching release, the similarity should be 1."""
    html, expected_results = make_html_with_results(["Release"], [1.0])
    assert (
        search_bandcamp(artist="Artist", name="Release", get=lambda *_: html)
        == expected_results
    )


def test_search_prioritises_best_matches(make_html_with_results):
    """Search results are sorted by similarity."""
    html, expected_results = make_html_with_results(
        ["Specific Release", "Specific Release With Long Name", "Release"],
        [1.0, 0.919, 0.812],
    )
    assert (
        search_bandcamp(artist="Artist", name="Specific Release", get=lambda *_: html)
        == expected_results
    )


# fmt: off
@pytest.mark.parametrize(
    "test_url, expected_label",
    [
        ("https://bandcamp.materiacollective.com/track/the-illusionary-dance", "materiacollective"),  # noqa: E501
        ("https://finderskeepersrecords.bandcamp.com/track/illusional-frieze", "finderskeepersrecords"),  # noqa: E501
        ("https://compiladoaspen.bandcamp.com/track/kiss-from-a-rose", "compiladoaspen"),  # noqa: E501
        ("https://comtruise.bandcamp.com/track/karova-digital-bonus-3", "comtruise"),
        ("https://bandofholyjoy.bandcamp.com/track/lost-in-the-night", "bandofholyjoy"),
        ("https://bandcampcomp.bandcamp.com/track/everything-everything-in-birdsong-acoustic", "bandcampcomp"),  # noqa: E501
        ("https://bandcamp.bandcamp.com/track/warm-2", "bandcamp"),
    ],
)
def test_search_matches(result_data, test_url, expected_label):
    result = get_matches(make_html_item({**result_data, "url": test_url}))
    assert result["url"] == test_url
    assert result["label"] == expected_label
