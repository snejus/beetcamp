"""Pytest fixtures for tests."""

from __future__ import annotations

import json
from copy import deepcopy
from operator import itemgetter
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from beets.autotag.hooks import AlbumInfo, TrackInfo
from git import Repo
from rich.console import Console
from typing_extensions import TypeAlias

from beetsplug.bandcamp import DEFAULT_CONFIG
from beetsplug.bandcamp.metaguru import ALBUMTYPES_LIST_SUPPORT, EXTENDED_FIELDS_SUPPORT

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.config.argparsing import Parser
    from _pytest.fixtures import SubRequest
    from _pytest.terminal import TerminalReporter


JSONDict: TypeAlias = "dict[str, Any]"


def pytest_addoption(parser: Parser) -> None:
    newest_folders = sorted(
        (p for p in Path("lib_tests").glob("*") if p.is_dir()),
        key=lambda p: p.stat().st_ctime,
        reverse=True,
    )
    all_names = [f.name for f in newest_folders]
    names = [n for n in all_names if n != "dev"]
    names_set = set(names)

    base_name = ""
    for commit in Repo(".").iter_commits(paths=["./beetsplug"]):
        short_commit = str(commit)[:7]
        if short_commit in names_set:
            base_name = short_commit
            break

    parser.addoption(
        "--base",
        choices=all_names,
        default=base_name or "dev",
        help="base directory / comparing against",
    )
    parser.addoption(
        "--target",
        default="dev",
        metavar="COMMIT",
        help="target name or short commit hash",
    )
    parser.addoption(
        "--fields",
        default="*",
        help="comma-delimited list of fields to compare, all by default",
    )


def pytest_terminal_summary(
    terminalreporter: TerminalReporter, exitstatus: int, config: Config
) -> None:
    base = config.getoption("base")
    target = config.getoption("target")
    terminalreporter.write(f"--- Compared {target} against {base} ---\n")


@pytest.fixture(scope="session")
def console() -> Console:
    return Console(force_terminal=True, force_interactive=True)


@pytest.fixture
def beets_config() -> JSONDict:
    return deepcopy(DEFAULT_CONFIG)


@pytest.fixture
def digital_format() -> JSONDict:
    return {
        "@id": "https://bandcamp.com/album/hello",
        "musicReleaseFormat": "DigitalFormat",
        "description": "Includes high-quality download...",
        "name": "Album",
        "additionalProperty": [
            {"name": "some_id", "value": "some_value"},
            {"name": "item_type", "value": "a"},
        ],
    }


@pytest.fixture
def vinyl_format() -> JSONDict:
    return {
        "@id": "https://bandcamp.com/album/hello",
        "musicReleaseFormat": "VinylFormat",
        "description": "Vinyl description",
        "name": "Disctitle",
        "additionalProperty": [
            {"name": "some_id", "value": "some_value"},
            {"name": "item_type", "value": "p"},
        ],
    }


@pytest.fixture
def bundle_format() -> JSONDict:
    return {
        "@id": "https://bandcamp.com/album/bye",
        "name": "Vinyl Bundle",
        "musicReleaseFormat": "VinylFormat",
        "additionalProperty": [{"name": "item_type", "value": "b"}],
    }


@pytest.fixture
def json_track() -> JSONDict:
    return {"item": {"@id": "track_url", "name": "Artist - Title"}, "position": 1}


@pytest.fixture
def json_meta(
    digital_format: JSONDict, vinyl_format: JSONDict, json_track: JSONDict
) -> JSONDict:
    return {
        "@id": "album_id",
        "name": "Album",
        "description": "Description",
        "publisher": {
            "@id": "label_url",
            "name": "Label",
            "genre": "bandcamp.com/tag/folk",
        },
        "byArtist": {"name": "Albumartist"},
        "albumRelease": [digital_format, vinyl_format],
        "track": {"itemListElement": [json_track]},
        "keywords": ["London", "house"],
    }


@pytest.fixture
def release(
    pytestconfig: pytest.Config, request: SubRequest
) -> tuple[str, list[JSONDict | None]]:
    """Find the requested testing fixture and get:
    1. Input JSON data and return it as a single-line string (same like in htmls).
    2. Expected output JSON data (found in the 'expected' folder) as a dictionary.
    """
    if not request.param:
        return "gibberish", [None]

    json_folder = pytestconfig.rootpath / "tests" / "json"
    filename = f"{request.param}.json"

    # remove newlines and spaces
    input_json = json.dumps(json.loads((json_folder / filename).read_text()))
    expected_output = json.loads((json_folder / "expected" / filename).read_text())

    if isinstance(expected_output, dict):
        expected_output = [expected_output]
    if ALBUMTYPES_LIST_SUPPORT:
        for release in expected_output:
            release["albumtypes"] = release["albumtypes"].split("; ")

    return input_json, expected_output


@pytest.fixture
def albuminfos(
    release: tuple[str, list[JSONDict]],
) -> list[AlbumInfo | TrackInfo | None]:
    """Return each album and track as 'AlbumInfo' and 'TrackInfo' objects.

    Objects in beets>=1.5.0 have additional fields, therefore for compatibility ensure
    that only available fields are being used.
    """
    if EXTENDED_FIELDS_SUPPORT:
        t_fields = set(TrackInfo())
        a_fields = set(AlbumInfo([]))
    else:
        t_fields = set(TrackInfo(None, None).__dict__)
        a_fields = set(AlbumInfo(None, None, None, None, None).__dict__)

    def _trackinfo(track: JSONDict) -> TrackInfo:
        return TrackInfo(**dict(zip(t_fields, itemgetter(*t_fields)(track))))

    def _albuminfo(album: JSONDict) -> AlbumInfo | TrackInfo | None:
        if not album:
            return None
        if not album.get("album"):
            return _trackinfo(album)

        albuminfo = AlbumInfo(**dict(zip(a_fields, itemgetter(*a_fields)(album))))
        albuminfo.tracks = list(map(_trackinfo, album["tracks"]))
        return albuminfo

    return list(map(_albuminfo, release[1]))


@pytest.fixture
def album_for_media(albuminfos: list[AlbumInfo], preferred_media: str) -> AlbumInfo:
    """Pick the album that matches the requested 'preferred_media'.

    If none of the albums match the 'preferred_media', pick the first one from the list.
    """
    try:
        return next(filter(lambda x: x and x.media == preferred_media, albuminfos))
    except StopIteration:
        return albuminfos[0]
