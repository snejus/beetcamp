"""Tests for searching functionality."""
import pytest
from beetsplug.bandcamp._search import RELEASE_PATTERNS, parse_and_sort_results

# simplified version of the search result HTML block
HTML_ITEM = """
<div class="searchresult data-search">
<a href="{url}">
search_item_type="a">
     {name}
     <span>some
     other stuff</span>
  by {artist}
  <div class="itemtype">
  ALBUM
  </div>
</div>
"""


def make_html_item(data):
    return HTML_ITEM.format(**data)


@pytest.fixture
def search_data():
    return {
        "name": "Release",
        "url": "https://label.bandcamp.com/album/release",
        "artist": "Artist",
        "label": "label",
        "type": "album",
    }.copy()


def test_search_logic(search_data):
    """Given a single matching release, the similarity should be 1."""
    results = parse_and_sort_results(make_html_item(search_data), **search_data)
    assert results == [{**search_data, "similarity": 1.0, "index": 1}]


def test_search_prioritises_best_matches(search_data):
    """Given two releases, the better match is found first in the output regardless
    of its position in the HTML.
    """
    expected_result = {
        **search_data,
        "name": "Specific Release",
        "url": "https://label.bandcamp.com/album/specific-release",
        "index": 1,
        "similarity": 0.955,
    }
    other_result = {
        **search_data,
        "name": "Release",
        "url": "https://label.bandcamp.com/album/release",
        "index": 2,
        "similarity": 0.925,
    }

    expected_results = [expected_result, other_result]

    html = make_html_item(other_result) + "\n" + make_html_item(expected_result)
    results = parse_and_sort_results(
        html, **{**search_data, "name": "Specific Release"}
    )
    assert results == expected_results


@pytest.mark.parametrize(
    ("test_url", "expected_label"),
    (
        (
            "https://bandcamp.materiacollective.com/track/the-illusionary-dance",
            "materiacollective",
        ),
        (
            "https://finderskeepersrecords.bandcamp.com/track/illusional-frieze",
            "finderskeepersrecords",
        ),
    ),
)
def test_search_matches(test_url, expected_label):
    test_matches = RELEASE_PATTERNS[-1].match(test_url)
    assert test_matches.group("url") == test_url
    assert test_matches.group("label") == expected_label
