"""Pytest fixtures for tests."""
import json
import re
from copy import deepcopy
from operator import itemgetter
from os import path

import pytest
from beets.autotag.hooks import AlbumInfo, TrackInfo
from beetsplug.bandcamp import DEFAULT_CONFIG
from rich.console import Console


@pytest.fixture(scope="session")
def console():
    return Console(force_terminal=True, force_interactive=True)


@pytest.fixture
def beets_config():
    return deepcopy({**DEFAULT_CONFIG, "exclude_extra_fields": ["comments"]})


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
    if filename.startswith("issues"):
        input_folder = path.join(input_folder, "issues")
        filename = filename.replace("issues_", "")

    with open(path.join(input_folder, filename), encoding="utf-8") as in_f:
        input_json = re.sub(r"\n *", "", in_f.read())
    with open(path.join(input_folder, "expected", filename), encoding="utf-8") as out_f:
        expected_output = json.load(out_f)
    if isinstance(expected_output, dict):
        expected_output = [expected_output]

    return input_json, expected_output


@pytest.fixture
def albuminfos(release):
    """Return each album and track as 'AlbumInfo' and 'TrackInfo' objects.

    Objects in beets>=1.5.0 have additional fields, therefore for compatibility ensure
    that only available fields are being used.
    """
    t_fields = list(TrackInfo(None, None).__dict__)
    a_fields = list(AlbumInfo(None, None, None, None, None).__dict__)

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
