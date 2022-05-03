"""Pytest fixtures for tests."""
import json
import re
from copy import deepcopy
from os import path

import pytest
from beetsplug.bandcamp import DEFAULT_CONFIG


@pytest.fixture
def beets_config():
    return deepcopy({**DEFAULT_CONFIG, "exclude_extra_fields": ["comments"]})


@pytest.fixture
def media_format():
    return {
        "@id": "https://bandcamp.com/album/hello",
        "musicReleaseFormat": "CDFormat",
        "item_type": "p",
        "description": "description",
        "name": "name",
    }


@pytest.fixture
def bc_media_formats():
    return [
        {
            "@id": "https://bandcamp.com/album/hello",
            "name": "Vinyl",
            "musicReleaseFormat": "VinylFormat",
            "description": "hello",
            "additionalProperty": [
                {"name": "some_id", "value": "some_value"},
                {"name": "item_type", "value": "a"},
            ],
        },
        {
            "@id": "https://bandcamp.com/album/bye",
            "name": "Vinyl Bundle",
            "musicReleaseFormat": "VinylFormat",
            "additionalProperty": [{"name": "item_type", "value": "b"}],
        },
    ]


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
