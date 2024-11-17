import pytest

from beetsplug.bandcamp.http import urlify


@pytest.mark.parametrize(
    ("title, expected"),
    [
        ("LI$INGLE010 - cyberflex - LEVEL X", "li-ingle010-cyberflex-level-x"),
        ("LI$INGLE007 - Re:drum - Movin'", "li-ingle007-re-drum-movin"),
        ("X23 & Høbie - Exhibit A", "x23-h-bie-exhibit-a"),
        ("under.net Compilation 1.1", "under-net-compilation-11"),
    ],
)
def test_urlify(title, expected):
    assert urlify(title) == expected
