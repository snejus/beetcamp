"""Tests that compare beetcamp outputs against expected JSON outputs."""
from operator import itemgetter

import pytest
from beetsplug.bandcamp._metaguru import NEW_BEETS, Metaguru

pytestmark = pytest.mark.jsons


def check(actual, expected) -> None:
    if NEW_BEETS:
        assert dict(actual) == expected
    else:
        actual = vars(actual)
        keys = set(actual.keys())
        new_expected = dict(zip(keys, itemgetter(*keys)(expected)))
        assert actual == new_expected


@pytest.mark.parametrize(
    "release", ["single_track_release", "single_only_track_name"], indirect=["release"]
)
def test_parse_single_track_release(release, beets_config):
    html, expected = release
    actual = Metaguru.from_html(html, beets_config).singleton
    check(actual, expected)


@pytest.mark.parametrize(
    "release",
    [
        "album",
        "album_with_track_alt",
        "compilation",
        "ep",
        "artist_mess",
        "description_meta",
        "single_with_remixes",
        "remix_artists",
        "edge_cases",
        "issues_18",
        "media_with_track_alts_in_desc",
        "artist_catalognum",
    ],
    indirect=["release"],
)
def test_parse_various_types(release, beets_config):
    html, expected_albums = release

    actual_albums = Metaguru.from_html(html, beets_config).albums

    assert len(actual_albums) == len(expected_albums)
    actual_albums.sort(key=lambda x: x.album_id)
    expected_albums.sort(key=lambda x: x["album_id"])

    for actual, expected in zip(actual_albums, expected_albums):
        assert hasattr(actual, "tracks")
        assert len(actual.tracks) == len(expected["tracks"])

        actual_tracks = sorted(actual.tracks, key=lambda t: t.index)
        expected_tracks = sorted(expected["tracks"], key=lambda t: t["index"])
        expected["tracks"] = actual.tracks = None

        check(actual, expected)

        for actual_track, expected_track in zip(actual_tracks, expected_tracks):
            check(actual_track, expected_track)
