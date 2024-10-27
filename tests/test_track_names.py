import pytest

from beetsplug.bandcamp.track_names import TrackNames


@pytest.mark.parametrize(
    "names, album_artist, expected",
    [
        (["T1 - A1 x A2"], "A3", ["T1 - A1 x A2"]),
        (["T1 - A1 x A2"], "A1", ["A1 x A2 - T1"]),
        (["T1 - A1 x A2", "T2 - A1 x A2"], "A1", ["A1 x A2 - T1", "A1 x A2 - T2"]),
    ],
)
def test_ensure_artist_first(names, album_artist, expected):
    assert TrackNames.ensure_artist_first(names, album_artist) == expected
