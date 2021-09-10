"""End to end tests aimed at catching html updates on bandcamp side."""
import pytest
from beets.library import Item
from beetsplug.bandcamp import BandcampPlugin

pytestmark = pytest.mark.need_connection


def check_album(actual, expected):
    expected.tracks.sort(key=lambda t: t.index)
    actual.tracks.sort(key=lambda t: t.index)

    for actual_track, expected_track in zip(actual.tracks, expected.tracks):
        assert vars(actual_track) == vars(expected_track)
    actual.tracks = None
    expected.tracks = None

    assert vars(actual) == vars(expected)


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


def test_search():
    query = "matriark"
    search_type = "track"
    expect_to_find = "https://mega-tech.bandcamp.com/track/arangel"

    plugin = BandcampPlugin()
    urls = list(plugin._search(query, search_type))

    assert expect_to_find in urls


def test_get_single_track_album(single_track_release):
    expected_track = single_track_release.singleton
    url = single_track_release.album_id

    plugin = BandcampPlugin()
    actual = plugin.get_track_info(url)

    assert vars(actual) == vars(expected_track)


def test_candidates(ep):
    expected_album = ep.albuminfo
    plugin = BandcampPlugin()

    albums = plugin.candidates([], expected_album.artist, expected_album.album, False)

    assert albums
    check_album(next(albums), expected_album)


def test_singleton_item_candidates(single_track_release):
    """Normally it takes ~10s to search and find a match."""
    expected = single_track_release.singleton
    pl = BandcampPlugin()

    candidates = pl.item_candidates(Item(), expected.artist, expected.title)
    for track in candidates:
        if track.title == expected.title:
            assert vars(track) == vars(expected)
            break
    else:
        pytest.fail("Expected singleton was not returned.")


def test_singleton_cheat_mode(single_track_release):
    """In the cheat mode it should take around 1-2s to match a singleton."""
    expected = single_track_release.singleton
    pl = BandcampPlugin()

    item = Item()
    item.comments = "Visit " + expected.artist_id
    item.title = expected.artist + " - " + expected.title

    candidates = pl.item_candidates(item, expected.artist, item.title)
    track = next(candidates)
    assert vars(track) == vars(expected)


@pytest.mark.parametrize("method", ["album_for_id", "track_for_id"])
def test_handle_non_bandcamp_url(method):
    """The plugin should not break if a non-bandcamp URL is presented."""
    pl = BandcampPlugin()
    url = "https://www.discogs.com/Nightwish-Angels-Fall-First/release/2709470"
    album = getattr(pl, method)(url)
    assert album is None
