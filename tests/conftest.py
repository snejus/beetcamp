"""Pytest fixtures for tests."""

import json
import os
import re
from copy import deepcopy
from glob import glob
from operator import itemgetter
from os import path

import pytest
from beets.autotag.hooks import AlbumInfo, TrackInfo
from beetsplug.bandcamp import DEFAULT_CONFIG
from beetsplug.bandcamp.metaguru import ALBUMTYPES_LIST_SUPPORT
from rich.console import Console


def pytest_addoption(parser):
    newest_folders = sorted(
        glob(os.path.join("lib_tests", f"*{os.path.sep}")),
        key=os.path.getctime,
        reverse=True,
    )
    all_names = [f.split(os.path.sep)[-2] for f in newest_folders]
    names = [n for n in all_names if n != "dev"]
    parser.addoption(
        "--base",
        choices=all_names,
        default=names[0] if names else "dev",
        help="base directory / comparing against",
    )
    parser.addoption(
        "--target",
        default="dev",
        metavar="COMMIT",
        help="target name or short commit hash",
    )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    base = config.getoption("base")
    target = config.getoption("target")
    terminalreporter.write(f"--- Compared {target} against {base} ---\n")


@pytest.fixture(scope="session")
def console():
    return Console(force_terminal=True, force_interactive=True)


@pytest.fixture
def beets_config():
    return deepcopy(DEFAULT_CONFIG)


@pytest.fixture
def digital_format():
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
def vinyl_format():
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
def bundle_format():
    return {
        "@id": "https://bandcamp.com/album/bye",
        "name": "Vinyl Bundle",
        "musicReleaseFormat": "VinylFormat",
        "additionalProperty": [{"name": "item_type", "value": "b"}],
    }


@pytest.fixture
def json_track():
    return {"item": {"@id": "track_url", "name": "Artist - Title"}, "position": 1}


@pytest.fixture
def json_meta(digital_format, vinyl_format, json_track):
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
def release(request):
    """Find the requested testing fixture and get:
    1. Input JSON data and return it as a single-line string (same like in htmls).
    2. Expected output JSON data (found in the 'expected' folder) as a dictionary.
    """
    if not request.param:
        return "gibberish", [None]

    filename = request.param + ".json"
    input_folder = path.join("tests", "json")

    with open(path.join(input_folder, filename), encoding="utf-8") as in_f:
        input_json = re.sub(r"\n *", "", in_f.read())
    with open(path.join(input_folder, "expected", filename), encoding="utf-8") as out_f:
        expected_output = json.load(out_f)
    if isinstance(expected_output, dict):
        expected_output = [expected_output]
    if ALBUMTYPES_LIST_SUPPORT:
        for release in expected_output:
            release["albumtypes"] = release["albumtypes"].split("; ")

    return input_json, expected_output


@pytest.fixture
def albuminfos(release):
    """Return each album and track as 'AlbumInfo' and 'TrackInfo' objects.

    Objects in beets>=1.5.0 have additional fields, therefore for compatibility ensure
    that only available fields are being used.
    """
    t_fields = list(TrackInfo(None, None).__dict__ or TrackInfo())
    a_fields = list(AlbumInfo(None, None, None, None, None).__dict__ or AlbumInfo([]))

    def _trackinfo(track):
        return TrackInfo(**dict(zip(t_fields, itemgetter(*t_fields)(track))))

    def _albuminfo(album):
        if not album:
            return None
        if album.get("album"):
            albuminfo = AlbumInfo(**dict(zip(a_fields, itemgetter(*a_fields)(album))))
            albuminfo.tracks = list(map(_trackinfo, album["tracks"]))
        else:
            albuminfo = _trackinfo(album)
        return albuminfo

    return list(map(_albuminfo, release[1]))


@pytest.fixture
def album_for_media(albuminfos, preferred_media):
    """Pick the album that matches the requested 'preferred_media'.
    If none of the albums match the 'preferred_media', pick the first one from the list.
    """
    try:
        return next(filter(lambda x: x and x.media == preferred_media, albuminfos))
    except StopIteration:
        return albuminfos[0]
