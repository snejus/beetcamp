import pytest

from beetsplug.bandcamp.names import Names

_p = pytest.param


@pytest.mark.parametrize(
    "names, album_artist, expected",
    [
        (["T1 - A1 x A2"], "A3", ["T1 - A1 x A2"]),
        (["T1 - A1 x A2"], "A1", ["A1 x A2 - T1"]),
        (["T1 - A1 x A2", "T2 - A1 x A2"], "A1", ["A1 x A2 - T1", "A1 x A2 - T2"]),
    ],
)
def test_ensure_artist_first(names, album_artist, expected):
    assert Names({}, album_artist=album_artist).ensure_artist_first(names) == expected


@pytest.mark.parametrize(
    "track_name, expected_titles",
    [
        ("Artist - Title - Label", ["Artist - Title"]),
        ("Title - Label", ["Title"]),
    ],
)
def test_remove_label(json_meta, expected_titles):
    names = Names(json_meta, "a")
    names.resolve()

    assert names.titles == expected_titles


@pytest.mark.parametrize(
    "original_name, albumartist, expected_catalognum",
    [
        ("Album [CAT001]", "", "CAT001"),
        ("CAT001 - Album", "", "CAT001"),
        ("CAT001- Album", "", "CAT001"),
        ("CAT001 -Album", "", "CAT001"),
        ("Album - CAT001", "", "CAT001"),
        ("Album | CAT001", "", "CAT001"),
        ("Album [CAT001]", "CAT001", None),
        ("Album [Very weird cat1]", "", "Very weird cat1"),
    ],
)
def test_album_catalognum(original_name, albumartist, expected_catalognum):
    meta = {"name": original_name}

    names = Names(meta, albumartist)
    assert names.catalognum == expected_catalognum
