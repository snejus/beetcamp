"""Data prep / fixtures for tests."""
import json
import re
from copy import deepcopy

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
def release(request):
    """Read the json data and make it span a single line - same like it's found in htmls.
    Prepend JSON data with a multiline track list.
    Each of the JSON test cases has a corresponding 'expected' JSON output data file.
    """
    name = request.param
    if name.startswith("issues"):
        filename = "tests/json/issues/{}".format(name.replace("issues_", ""))
    else:
        filename = "tests/json/{}".format(name)

    with open(filename + ".json") as input_f:
        input_json = re.sub(r"\n *", "", input_f.read())
    with open(filename + "_expected.json") as expected_f:
        expected_output = json.load(expected_f)

    return input_json, expected_output
