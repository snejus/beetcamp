"""Pytest fixtures for tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Union

import pytest
from beets.autotag.hooks import AlbumInfo, TrackInfo
from git import Repo
from rich.console import Console
from rich_tables.utils import make_console, pretty_diff
from typing_extensions import TypeAlias

from beetsplug.bandcamp import DEFAULT_CONFIG
from beetsplug.bandcamp.helpers import Helpers

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.config.argparsing import Parser
    from _pytest.fixtures import SubRequest
    from _pytest.terminal import TerminalReporter


JSONDict: TypeAlias = "dict[str, Any]"
console = make_console()


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


def pytest_assertrepr_compare(op: str, left, right):
    """Pretty print the difference between dict objects."""
    actual, expected = left, right

    if isinstance(actual, (list, dict)) and isinstance(expected, (list, dict)):
        with console.capture() as cap:
            console.print(pretty_diff(expected, actual))

        return ["\n", *cap.get().splitlines()]

    return None


@pytest.fixture(scope="session", name="console")
def fixture_console() -> Console:
    return console


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
def track_name() -> str:
    return "Artist - Title"


@pytest.fixture
def json_track(track_name) -> JSONDict:
    return {"item": {"@id": "track_url", "name": track_name}, "position": 1}


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


JSON_DIR = Path("tests") / "json"
RELEASES = [p.stem for p in JSON_DIR.glob("*.json")]


@pytest.fixture(params=RELEASES)
def release(request: SubRequest) -> str:
    """Return the name of the release test case."""
    return request.param


@pytest.fixture
def bandcamp_data_path(release: str) -> Path:
    """Return path to the Bandcamp JSON data file."""
    return JSON_DIR / f"{release}.json"


@pytest.fixture
def bandcamp_html(bandcamp_data_path: Path) -> str:
    """Return Bandcamp JSON data in a single line as like it's found in HTML."""
    try:
        contents = bandcamp_data_path.read_text()
    except FileNotFoundError:
        return ""

    # load and dump the data to remove newlines and spaces
    return json.dumps(json.loads(contents))


JSONDictOrList = Union[Dict[str, Any], List[Dict[str, Any]]]


@pytest.fixture
def expected_release(bandcamp_data_path: Path) -> list[AlbumInfo] | TrackInfo | None:
    """Return corresponding expected release JSON data.

    Until beets 1.5.0, TrackInfo and AlbumInfo objects only supported a limited set
    of fields, thus drop the extra fields from the expected data.
    """
    path = bandcamp_data_path.parent / "expected" / bandcamp_data_path.name
    try:
        release_datastr = path.read_text()
    except FileNotFoundError:
        return None

    release_data = json.loads(release_datastr)

    if isinstance(release_data, dict):
        return Helpers.check_list_fields(TrackInfo(**release_data))

    return [Helpers.check_list_fields(AlbumInfo(**r)) for r in release_data]


@pytest.fixture
def album_for_media(
    expected_release: list[AlbumInfo] | None, preferred_media: str
) -> AlbumInfo | None:
    """Pick the album that matches the requested 'preferred_media'.

    If none of the albums match the 'preferred_media', pick the first one from the list.
    """
    if expected_release is None:
        return None

    albums = expected_release
    return next(filter(lambda x: x.media == preferred_media, albums), albums[0])
