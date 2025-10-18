"""Tests for any logic found in the main plugin module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from beets.autotag import AlbumInfo, TrackInfo
from confuse import ConfigView
import pytest
from beets import config as beets_config
from beets.library import Album, Item
from beets.plugins import log

from beetsplug.bandcamp import (
    DEFAULT_CONFIG,
    BandcampAlbumArt,
    BandcampPlugin,
    BandcampRequestsHandler,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from _pytest.mark import ParameterSet
    from typing_extensions import LiteralString


LABEL_URL: LiteralString = "https://label.bandcamp.com"
ALBUM_URL: LiteralString = f"{LABEL_URL}/album/release"

_p: Callable[..., ParameterSet] = pytest.param


def check_album(actual, expected) -> None:
    expected.tracks.sort(key=lambda t: t.index)
    actual.tracks.sort(key=lambda t: t.index)

    for actual_track, expected_track in zip(actual.tracks, expected.tracks):
        assert vars(actual_track) == vars(expected_track)
    actual.tracks = None
    expected.tracks = None
    assert vars(actual) == vars(expected)


@pytest.mark.parametrize(
    argnames="comments, expected_url",
    argvalues=[
        ("Visit https://label.bandcamp.com", "https://label.bandcamp.com"),
        ("Visit https://supercommuter.net", "https://supercommuter.net"),
        ("Visit https://no-top-level-domain", None),
    ],
)
def test_parse_label_url_in_comments(comments: str, expected_url: str | None) -> None:
    assert BandcampPlugin.parse_label_url(text=comments) == expected_url


@pytest.mark.parametrize(
    argnames="mb_albumid, comments, album, expected_url",
    argvalues=[
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
def test_find_url(
    mb_albumid: str, comments: str, album: str, expected_url: str
) -> None:
    """URLs in `mb_albumid` and `comments` fields must be found."""
    item: Item = Item(mb_albumid=mb_albumid, comments=comments)
    assert (
        BandcampPlugin()._find_url_in_item(item=item, name=album, type_="album")
        == expected_url
    )


@pytest.fixture
def plugin(monkeypatch: pytest.MonkeyPatch, bandcamp_html: str) -> BandcampPlugin:
    def _get(*_: str) -> str:
        return bandcamp_html

    monkeypatch.setattr(BandcampRequestsHandler, "_get", _get)
    pl: BandcampPlugin = BandcampPlugin()
    pl.config.set(DEFAULT_CONFIG)
    return pl


@pytest.mark.parametrize(argnames="method", argvalues=["album_for_id", "track_for_id"])
def test_handle_non_bandcamp_url(method: str):
    """The plugin should not break if a non-bandcamp URL is presented."""
    assert getattr(BandcampPlugin(), method)("https://www.some-random-url") is None


@pytest.mark.parametrize(
    argnames="release, preferred_media",
    argvalues=[
        ("album", "Vinyl"),
        ("album", "CD"),
        ("album", ""),
        (None, None),
    ],
)
def test_album_for_id(
    plugin: BandcampPlugin,
    album_for_media: AlbumInfo | None,
    preferred_media: str | None,
) -> None:
    """For an album id, the plugin returns a _single_ album in the preferred format."""
    expected_album: AlbumInfo | None = album_for_media
    album_id: str | None
    if not expected_album or not (album_id := expected_album.album_id):
        album_id = "https://bandcamp.com/album/doesntexist"
    beets_config["match"]["preferred"]["media"].set(value=[preferred_media])

    album: AlbumInfo | None = plugin.album_for_id(album_id=album_id)

    assert album == expected_album


@pytest.mark.parametrize(argnames="release", argvalues=["album"])
def test_candidates(plugin: BandcampPlugin, expected_release: list[TrackInfo]) -> None:
    first: TrackInfo = expected_release[0]
    artist: str
    album: str
    artist, album = first.artist or "", first.album or ""
    item: Item = Item(albumartist=artist, album=album, mb_albumid=first.album_id)

    candidates: list[AlbumInfo] = list(
        plugin.candidates(items=[item], artist=artist, album=album, va_likely=False)
    )

    assert candidates == expected_release


@pytest.mark.parametrize(argnames="release", argvalues=["single_track_release"])
def test_singleton_candidates(
    plugin: BandcampPlugin, expected_release: TrackInfo
) -> None:
    artist: str
    title: str
    artist, title = expected_release.artist or "", expected_release.title or ""
    item: Item = Item(artist=artist, title=title, mb_trackid=expected_release.track_id)

    candidates: list[TrackInfo] = list(
        plugin.item_candidates(item=item, artist=artist, title=title)
    )

    assert candidates == [expected_release]


def test_bandcamp_plugin_name() -> None:
    assert BandcampPlugin().data_source == "bandcamp"


@pytest.fixture
def bandcamp_album() -> Album:
    return Album(mb_albumid="https://bandcamp.com/album/")


def test_coverart(
    monkeypatch: pytest.MonkeyPatch, bandcamp_album: Album, beets_config: ConfigView
) -> None:
    text: str = Path("tests/json/album.json").read_text(encoding="utf-8")

    img_url: str | None = json.loads(text)["image"]

    def _get(*_: str) -> str:
        return text

    monkeypatch.setattr(BandcampRequestsHandler, "_get", _get)

    for candidate in BandcampAlbumArt(log=log, config=beets_config).get(
        album=bandcamp_album, plugin=None, paths=[]
    ):
        assert candidate.url == img_url


def test_no_coverart_non_bandcamp_url(beets_config: ConfigView):
    album: Album = Album(mb_albumid="123-abc-12323")
    with pytest.raises(StopIteration):
        _ = next(
            BandcampAlbumArt(log=log, config=beets_config).get(
                album, plugin=None, paths=[]
            )
        )


def test_no_coverart_empty_response(
    monkeypatch: pytest.MonkeyPatch, bandcamp_album: Album, beets_config: ConfigView
) -> None:
    def _get(*_: str) -> str:
        return ""

    monkeypatch.setattr(BandcampRequestsHandler, "_get", _get)
    with pytest.raises(StopIteration):
        _ = next(
            BandcampAlbumArt(log=log, config=beets_config).get(
                album=bandcamp_album, plugin=None, paths=[]
            )
        )


@pytest.mark.parametrize(
    argnames="html",
    argvalues=[
        "empty",
        json.dumps({"@id": "", "image": "someurl"}),  # no tracks
        json.dumps({"@id": "", "track": [], "image": "someurl"}),  # no label
        json.dumps(
            {
                "@id": "",
                "track": [],
                "publisher": {"name": "Label"},
            }
        ),  # missing image
    ],
)
def test_no_coverart_bad_html(
    monkeypatch: pytest.MonkeyPatch,
    html: str,
    bandcamp_album: Album,
    beets_config: ConfigView,
) -> None:
    def _get(*_: str) -> str:
        return html

    monkeypatch.setattr(BandcampRequestsHandler, "_get", _get)
    with pytest.raises(StopIteration):
        _ = next(
            BandcampAlbumArt(log=log, config=beets_config).get(
                album=bandcamp_album, plugin=None, paths=[]
            )
        )
