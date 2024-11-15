"""End to end tests aimed at catching issues with html updates on bandcamp side."""

import pytest

from beetsplug.bandcamp import BandcampPlugin

pytestmark = pytest.mark.need_connection


def test_get_html():
    """Check whether content is being returned."""
    url = "https://ute-rec.bandcamp.com/album/ute004"
    should_contain = "UTE004 by Mikkel Rev, released 17 July 2020"

    plugin = BandcampPlugin()
    html = plugin._get(url)

    assert html
    assert should_contain in html


def test_return_none_for_gibberish():
    """Check whether None is being returned."""
    url = "https://ute-rec.bandcamp.com/somegibberish2113231"

    plugin = BandcampPlugin()
    html = plugin._get(url)

    assert not html
