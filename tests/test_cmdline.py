"""Module for command line functionality tests."""

import sys

import pytest
from beetsplug.bandcamp import get_args


# fmt: off
@pytest.mark.parametrize(
    "cmdline, args",
    [
        (["https://bandcamp.com"], {"query": "", "release_url": "https://bandcamp.com", "search_type": "", "index": None, "page": 1}),
        (["hello"], {"query": "hello", "search_type": "", "index": None, "page": 1}),
        (["hello", "-a"], {"query": "hello", "search_type": "a", "index": None, "page": 1}),
        (["hello", "-t"], {"query": "hello", "search_type": "t", "index": None, "page": 1}),
        (["hello", "-l"], {"query": "hello", "search_type": "b", "index": None, "page": 1}),
        (["hello", "-l", "-o", "1"], {"query": "hello", "search_type": "b", "index": 1, "page": 1}),
        (["hello", "-l", "-p", "2"], {"query": "hello", "search_type": "b", "index": None, "page": 2}),
    ],
)
# fmt: on
def test_cmdline_flags(cmdline, args):
    sys.argv = ["beetcamp", *cmdline]
    assert vars(get_args()) == args


def test_required_parameter(capsys):
    sys.argv = ["beetcamp"]
    with pytest.raises(SystemExit):
        get_args()

    capture = capsys.readouterr()
    assert "error: one of the arguments" in capture.err
