"""End to end tests aimed at catching html updates on bandcamp side."""
import pytest
from beets.autotag.hooks import AlbumInfo, TrackInfo
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


@pytest.mark.parametrize("release", ["ep"], indirect=["release"])
def test_candidates(release):
    _, expected_albums = release
    expected_album = AlbumInfo(**expected_albums[0])
    expected_album.tracks = list(map(lambda x: TrackInfo(**x), expected_album.tracks))

    plugin = BandcampPlugin()

    albums = plugin.candidates([], expected_album.artist, expected_album.album, False)

    assert albums
    check_album(next(albums), expected_album)


@pytest.mark.parametrize("release", ["single_track_release"], indirect=["release"])
def test_singleton_item_candidates(release):
    """Our test singleton should be the first search result."""
    _, expected_track = release
    expected = TrackInfo(**expected_track)

    pl = BandcampPlugin()

    track = next(pl.item_candidates(Item(), expected.artist, expected.title))
    assert track
    assert vars(track) == vars(expected)


@pytest.mark.parametrize("method", ["album_for_id", "track_for_id"])
def test_handle_non_bandcamp_url(method):
    """The plugin should not break if a non-bandcamp URL is presented."""
    pl = BandcampPlugin()
    url = "https://www.discogs.com/Nightwish-Angels-Fall-First/release/2709470"
    album = getattr(pl, method)(url)
    assert album is None
