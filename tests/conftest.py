"""Pytest fixtures for tests."""
import json
import re
from copy import deepcopy
from os import path

import pytest
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
    """Read the json data and remove new line chars - same like it's found in htmls.
    Each of the JSON test cases has a corresponding 'expected' JSON output data file.
    """
    filename = request.param + ".json"
    input_folder = path.join("tests", "json")
    if filename.startswith("issues"):
        input_folder = path.join(input_folder, "issues")
        filename = filename.replace("issues_", "")

    with open(path.join(input_folder, filename), encoding="utf-8") as in_f:
        input_json = re.sub(r"\n *", "", in_f.read())
    with open(path.join(input_folder, "expected", filename), encoding="utf-8") as out_f:
        expected_output = json.load(out_f)

    return input_json, expected_output
