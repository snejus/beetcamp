"""Tests for searching functionality."""
import pytest
from beetsplug.bandcamp.search import get_matches, parse_and_sort_results

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
    return HTML_ITEM.format(**data, date="26 November 2021")


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
    expected_data = {**search_data, "date": "2021 November 26"}
    results = parse_and_sort_results(make_html_item(search_data), **expected_data)
    assert results == [{**expected_data, "similarity": 1.0, "index": 1}]


def test_search_logic_alternate_domain_name(search_data):
    # test same dataset, but with alternate domain name, such as mydomain.com
    """Given a single matching release, the similarity should be 1."""
    search_data["url"] = "https://mydomain.com/album/release"
    expected_data = {**search_data, "date": "2021 November 26", "label": "mydomain"}
    results = parse_and_sort_results(make_html_item(search_data), **expected_data)
    assert results == [{**expected_data, "similarity": 1.0, "index": 1}]


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

    expected_results = [
        {**expected_result, "date": "2021 November 26"},
        {**other_result, "date": "2021 November 26"},
    ]

    html = make_html_item(other_result) + "\n" + make_html_item(expected_result)
    results = parse_and_sort_results(
        html, **{**search_data, "name": "Specific Release"}
    )
    assert results == expected_results


# fmt: off
@pytest.mark.parametrize(
    ("test_url", "expected_label"),
    (
        ("https://bandcamp.materiacollective.com/track/the-illusionary-dance", "materiacollective"),  # noqa
        ("https://finderskeepersrecords.bandcamp.com/track/illusional-frieze", "finderskeepersrecords"),  # noqa
        ("https://compiladoaspen.bandcamp.com/track/kiss-from-a-rose", "compiladoaspen"),  # noqa
        ("https://comtruise.bandcamp.com/track/karova-digital-bonus-3", "comtruise"),
        ("https://bandofholyjoy.bandcamp.com/track/lost-in-the-night", "bandofholyjoy"),
        ("https://bandcampcomp.bandcamp.com/track/everything-everything-in-birdsong-acoustic", "bandcampcomp"),  # noqa
        ("https://bandcamp.bandcamp.com/track/warm-2", "bandcamp"),
    ),
)
# fmt: on
def test_search_matches(search_data, test_url, expected_label):
    result = get_matches(make_html_item({**search_data, "url": test_url}))
    assert result["url"] == test_url
    assert result["label"] == expected_label
