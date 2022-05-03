"""Tests for searching functionality."""
import pytest
from beets.library import Item
from beetsplug.bandcamp import BandcampPlugin

_p = pytest.param

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
    query, artist, label = "Release", "Artist", "label"
    expected_result = {
        "release": query,
        "url": f"https://{label}.bandcamp.com/album/release",
        "artist": artist,
        "label": label,
        "similarity": 1.0,
    }
    html = make_html_item(expected_result)
    results = BandcampPlugin._parse_and_sort_results(html, query, artist, label)
    assert results == [expected_result]


def test_search_prioritises_best_matches():
    """Given two releases, the better match is found first in the output regardless
    of its position in the HTML.
    """
    query, artist, label = "Specific Release", "Artist", "label"
    expected_result = {
        "release": query,
        "url": f"https://{label}.bandcamp.com/album/specific-release",
        "artist": artist,
        "label": label,
        "similarity": 1.0,
    }
    other_result = {
        "release": "Release",
        "url": f"https://{label}.bandcamp.com/album/release",
        "artist": artist,
        "label": label,
        "similarity": 0.875,
    }

    html = make_html_item(other_result) + "\n" + make_html_item(expected_result)
    expected_results = [expected_result, other_result]

    results = BandcampPlugin._parse_and_sort_results(html, query, artist, label)
    assert results == expected_results


LABEL_URL = "https://label.bandcamp.com"
ALBUM_URL = f"{LABEL_URL}/album/release"


@pytest.mark.parametrize(
    ("mb_albumid", "comments", "album", "expected_url"),
    [
        _p(ALBUM_URL, "", "a", ALBUM_URL, id="found in mb_albumid"),
        _p("random_url", "", "a", "", id="invalid url"),
        _p(
            "random_url",
            f"Visit {LABEL_URL}",
            "Release",
            ALBUM_URL,
            id="label in comments",
        ),
        _p(
            "random_url",
            f"Visit {LABEL_URL}",
            "ø ø ø",
            "",
            id="label in comments, album only invalid chars",
        ),
    ],
)
def test_find_url(mb_albumid, comments, album, expected_url):
    """URLs in `mb_albumid` and `comments` fields must be found."""
    item = Item(mb_albumid=mb_albumid, comments=comments)
    assert BandcampPlugin()._find_url(item, album, "album") == expected_url
