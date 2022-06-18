"""Tests for any logic found in the main plugin module."""
import json
from logging import getLogger

import pytest
from beets.autotag.hooks import AlbumInfo
from beets.library import Item
from beetsplug.bandcamp import DEFAULT_CONFIG, BandcampAlbumArt, BandcampPlugin, urlify

LABEL_URL = "https://label.bandcamp.com"
ALBUM_URL = f"{LABEL_URL}/album/release"

_p = pytest.param


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


def test_coverart(monkeypatch, beets_config):
    with open("tests/json/album.json", encoding="utf-8") as f:
        text = "".join(f.read().splitlines())

    img_url = json.loads(text)["image"]

    monkeypatch.setattr(BandcampAlbumArt, "_get", lambda *args: text)

    album = Item(mb_albumid="https://bandcamp.com/album/")
    log = getLogger(__name__)
    for cand in BandcampAlbumArt(log, beets_config).get(album, None, []):
        assert cand.url == img_url


@pytest.mark.usefixtures("release")
@pytest.mark.parametrize(
    ["release", "preferred_media", "expected_media"],
    [
        ("album", "Vinyl", "Vinyl"),
        ("album", "CD", "Digital Media"),
        ("album", None, "Digital Media"),
        (None, None, None),
    ],
    indirect=["release"],
)
def test_album_for_id(monkeypatch, album_for_media, preferred_media, expected_media):
    """Check that when given an album id, the plugin returns a _single_ album in the
    preferred media format.
    """
    html, expected_album = album_for_media
    if expected_album:
        album_id = expected_album.album_id
    else:
        album_id = "https://bandcamp.com/album/doesntexist"

    monkeypatch.setattr(BandcampPlugin, "_get", lambda *args: html)
    pl = BandcampPlugin()
    pl.beets_config["match"]["preferred"]["media"].set([preferred_media])
    album = pl.album_for_id(album_id)

    if expected_album:
        assert isinstance(album, AlbumInfo)
        assert album.media == expected_media
        assert vars(album) == vars(expected_album)
    else:
        assert album is None


@pytest.mark.usefixtures("release")
@pytest.mark.parametrize(["release"], [["album"]], indirect=["release"])
def test_candidates(monkeypatch, albuminfos):
    html, expected_albums = albuminfos
    first = expected_albums[0]

    monkeypatch.setattr(BandcampPlugin, "_get", lambda *args: html)

    artist, album = first.artist, first.album
    item = Item(albumartist=artist, album=album, mb_albumid=first.album_id)
    pl = BandcampPlugin()
    pl.config.set(DEFAULT_CONFIG)

    candidates = list(pl.candidates([item], artist, album, False))
    assert len(candidates) == len(expected_albums)
    assert candidates == expected_albums
