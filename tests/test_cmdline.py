"""Module for command line functionality tests."""
import pytest
from beetsplug.bandcamp import get_args


@pytest.mark.parametrize(
    ["cmdline", "args"],
    [
        (
            ["https://bandcamp.com"],
            {
                "query": "",
                "release_url": "https://bandcamp.com",
                "search_type": "",
                "index": None,
            },
        ),
        (["hello"], {"query": "hello", "search_type": "", "index": None}),
        (["hello", "-a"], {"query": "hello", "search_type": "a", "index": None}),
        (["hello", "-t"], {"query": "hello", "search_type": "t", "index": None}),
        (["hello", "-l"], {"query": "hello", "search_type": "b", "index": None}),
        (
            ["hello", "-l", "-o", "1"],
            {"query": "hello", "search_type": "b", "index": 1},
        ),
    ],
)
def test_cmdline_flags(cmdline, args):
    assert vars(get_args(cmdline)) == args


def test_help_is_shown(capsys):
    with pytest.raises(SystemExit):
        get_args([])
        capture = capsys.readouterr()
        assert "options:" in capture.out
