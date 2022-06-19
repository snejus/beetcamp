"""Module for command line functionality tests."""
import pytest
from beetsplug.bandcamp import get_args


@pytest.mark.parametrize(
    ["cmdline", "args"],
    [
        (
            ["https://bandcamp.com"],
            {"query": "", "release_url": "https://bandcamp.com", "search_type": ""},
        ),
        (["hello"], {"query": "hello", "search_type": ""}),
        (["hello", "-a"], {"query": "hello", "search_type": "a"}),
        (["hello", "-t"], {"query": "hello", "search_type": "t"}),
        (["hello", "-l"], {"query": "hello", "search_type": "b"}),
    ],
)
def test_cmdline_flags(cmdline, args):
    assert vars(get_args(cmdline)) == args


def test_help_is_shown(capsys):
    with pytest.raises(SystemExit):
        get_args([])
        capture = capsys.readouterr()
        assert "options:" in capture.out
