"""Tests for any logic found in the main plugin module."""

import json
from itertools import zip_longest

import pytest
from beets.autotag.hooks import AlbumInfo
from beets.library import Item
from beets.plugins import log
from beetsplug.bandcamp import DEFAULT_CONFIG, BandcampAlbumArt, BandcampPlugin, urlify

LABEL_URL = "https://label.bandcamp.com"
ALBUM_URL = f"{LABEL_URL}/album/release"

_p = pytest.param


def check_album(actual, expected):
    expected.tracks.sort(key=lambda t: t.index)
    actual.tracks.sort(key=lambda t: t.index)

    for actual_track, expected_track in zip(actual.tracks, expected.tracks):
        assert vars(actual_track) == vars(expected_track)
    actual.tracks = None
    expected.tracks = None
    assert vars(actual) == vars(expected)


@pytest.mark.parametrize(
    "comments, expected_url",
    [
        ("Visit https://label.bandcamp.com", "https://label.bandcamp.com"),
        ("Visit https://supercommuter.net", "https://supercommuter.net"),
        ("Visit https://no-top-level-domain", None),
    ],
)
def test_parse_label_url_in_comments(comments, expected_url):
    assert BandcampPlugin.parse_label_url(comments) == expected_url


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
    assert BandcampPlugin()._find_url_in_item(item, album, "album") == expected_url


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("LI$INGLE010 - cyberflex - LEVEL X", "li-ingle010-cyberflex-level-x"),
        ("LI$INGLE007 - Re:drum - Movin'", "li-ingle007-re-drum-movin"),
        ("X23 & Høbie - Exhibit A", "x23-h-bie-exhibit-a"),
    ],
)
def test_urlify(title, expected):
    assert urlify(title) == expected


@pytest.fixture
def plugin(monkeypatch, release):
    html, _ = release
    monkeypatch.setattr(BandcampPlugin, "_get", lambda *args: html)
    pl = BandcampPlugin()
    pl.config.set(DEFAULT_CONFIG)
    return pl


@pytest.mark.parametrize("method", ["album_for_id", "track_for_id"])
def test_handle_non_bandcamp_url(method):
    """The plugin should not break if a non-bandcamp URL is presented."""
    assert getattr(BandcampPlugin(), method)("https://www.some-random-url") is None


@pytest.mark.usefixtures("release")
@pytest.mark.parametrize(
    ["release", "preferred_media", "expected_media"],
    [
        ("album", "Vinyl", "Vinyl"),
        ("album", "CD", "Digital Media"),
        ("album", "", "Digital Media"),
        (None, None, None),
    ],
    indirect=["release"],
)
def test_album_for_id(plugin, album_for_media, preferred_media, expected_media):
    """Check that when given an album id, the plugin returns a _single_ album in the
    preferred media format.
    """
    expected_album = album_for_media
    if expected_album:
        album_id = expected_album.album_id
    else:
        album_id = "https://bandcamp.com/album/doesntexist"
    plugin.beets_config["match"]["preferred"]["media"].set([preferred_media])

    album = plugin.album_for_id(album_id)

    if expected_album:
        assert isinstance(album, AlbumInfo)
        assert album.media == expected_media
        check_album(album, expected_album)
    else:
        assert album is None


@pytest.mark.usefixtures("release")
@pytest.mark.parametrize("release", ["album"], indirect=["release"])
def test_candidates(plugin, albuminfos):
    first = albuminfos[0]
    artist, album = first.artist, first.album
    item = Item(albumartist=artist, album=album, mb_albumid=first.album_id)

    candidates = list(plugin.candidates([item], artist, album, False))

    assert len(candidates) == len(albuminfos)
    for actual, expected in zip(candidates, albuminfos):
        check_album(actual, expected)


@pytest.mark.usefixtures("release")
@pytest.mark.parametrize("release", ["single_track_release"], indirect=["release"])
def test_singleton_candidates(plugin, albuminfos):
    first = albuminfos[0]
    artist, title = first.artist, first.title
    item = Item(artist=artist, title=title, mb_trackid=first.track_id)

    candidates = list(plugin.item_candidates(item, artist, title))

    assert len(candidates) == len(albuminfos)
    for actual, expected in zip_longest(candidates, albuminfos):
        assert vars(actual) == vars(expected)


def test_bandcamp_plugin_name():
    assert BandcampPlugin().data_source == "bandcamp"


@pytest.fixture
def bandcamp_item():
    return Item(mb_albumid="https://bandcamp.com/album/")


def test_coverart(monkeypatch, bandcamp_item, beets_config):
    with open("tests/json/album.json", encoding="utf-8") as f:
        text = "".join(f.read().splitlines())

    img_url = json.loads(text)["image"]

    monkeypatch.setattr(BandcampAlbumArt, "_get", lambda *args: text)

    for candidate in BandcampAlbumArt(log, beets_config).get(bandcamp_item, None, []):
        assert candidate.url == img_url


def test_no_coverart_non_bandcamp_url(beets_config):
    album = Item(mb_albumid="123-abc-12323")
    with pytest.raises(StopIteration):
        next(BandcampAlbumArt(log, beets_config).get(album, None, []))


def test_no_coverart_empty_response(monkeypatch, bandcamp_item, beets_config):
    monkeypatch.setattr(BandcampAlbumArt, "_get", lambda *args: "")
    with pytest.raises(StopIteration):
        next(BandcampAlbumArt(log, beets_config).get(bandcamp_item, None, []))


@pytest.mark.parametrize(
    "html",
    (
        "empty",
        json.dumps({"@id": "", "image": "someurl"}),  # no tracks
        json.dumps({"@id": "", "track": [], "image": "someurl"}),  # no label
        json.dumps(
            {"@id": "", "track": [], "publisher": {"name": "Label"}}
        ),  # missing image
    ),
)
def test_no_coverart_bad_html(monkeypatch, html, bandcamp_item, beets_config):
    monkeypatch.setattr(BandcampAlbumArt, "_get", lambda *args: html)
    with pytest.raises(StopIteration):
        next(BandcampAlbumArt(log, beets_config).get(bandcamp_item, None, []))
