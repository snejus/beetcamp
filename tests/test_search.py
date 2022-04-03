import pytest
from beetsplug.bandcamp import BandcampPlugin

# simplified version of the search result HTML block
HTML_ITEM = """
<div class="heading">
<a href="{}">
     {}
     <span>some
     other stuff</span>
  by {}
</div>
"""


def make_html_item(data):
    return HTML_ITEM.format(data["url"], data["release"], data["artist"])


def test_search_logic():
    """Given a single matching release, the similarity should be 1."""
    query, artist = "Release", "Artist"
    expected_result = {
        "release": query,
        "url": "https://label.bandcamp.com/album/release",
        "artist": artist,
        "similarity": 1.0,
    }
    html = make_html_item(expected_result)
    results = BandcampPlugin._parse_and_sort_results(html, query, artist)
    assert results == [expected_result]


def test_search_prioritises_best_matches():
    """Given two releases, the better match is found first in the output regardless
    of its position in the HTML.
    """
    query, artist = "Specific Release", "Artist"
    expected_result = {
        "release": query,
        "url": "https://label.bandcamp.com/album/specific-release",
        "artist": artist,
        "similarity": 1.0,
    }
    other_result = {
        "release": "Release",
        "url": "https://label.bandcamp.com/album/release",
        "artist": artist,
        "similarity": 0.72,
    }

    html = make_html_item(other_result) + "\n" + make_html_item(expected_result)
    expected_results = [expected_result, other_result]

    results = BandcampPlugin._parse_and_sort_results(html, query, artist)
    assert results == expected_results
