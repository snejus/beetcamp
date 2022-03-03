import re
from operator import itemgetter

import pytest
from pytest_lazyfixture import lazy_fixture

from beetsplug.bandcamp._metaguru import NEW_BEETS, Metaguru

pytestmark = pytest.mark.jsons


@pytest.fixture(name="release")
def _release(request):
    """Read the json data and make it span a single line - same like it's found in htmls.
    Prepend JSON data with a multiline track list.
    Fixture names map to the testfiles (minus the extension).
    """
    info = request.param
    fixturename = next(iter(request._parent_request._fixture_defs.keys()))
    if fixturename.startswith("issues"):
        filename = "tests/json/issues/{}.json".format(fixturename.replace("issues_", ""))
    else:
        filename = "tests/json/{}.json".format(fixturename)

    if filename:
        with open(filename) as file:
            json = re.sub(r"\n *", "", file.read())

        if info.singleton:
            return json, info

        tracklist = []
        for track in info.albuminfo.tracks:
            tracklist.append(
                f"{track['index']}. "
                + (f"{track['track_alt']}. " if track["track_alt"] else "")
                + f"{track['artist']} - {track['title']}"
            )
        return "\n".join([*tracklist, json]), info


def check(actual, expected) -> None:
    if NEW_BEETS:
        assert actual == expected
    else:
        assert vars(actual) == vars(expected)


@pytest.mark.parametrize(
    "release",
    map(lazy_fixture, ["single_track_release", "single_only_track_name"]),
    indirect=["release"],
)
def test_parse_single_track_release(release, beets_config):
    html, expected = release
    actual = Metaguru.from_html(html, beets_config).singleton
    if hasattr(actual, "comments"):
        actual.pop("comments")

    check(actual, expected.singleton)


@pytest.mark.parametrize(
    "release",
    map(
        lazy_fixture,
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
        ],
    ),
    indirect=["release"],
)
def test_parse_various_types(release, beets_config):
    html, expected_release = release
    beets_config["preferred_media"] = expected_release.media
    guru = Metaguru.from_html(html, beets_config)

    actual_album = guru.album
    expected_album = expected_release.albuminfo
    if hasattr(actual_album, "comments"):
        actual_album.pop("comments")

    assert hasattr(actual_album, "tracks")
    assert len(actual_album.tracks) == len(expected_album.tracks)

    expected_tracks = sorted(expected_album.tracks, key=lambda t: t.index)
    actual_tracks = sorted(actual_album.tracks, key=lambda t: t.index)

    actual_album.tracks = None
    expected_album.tracks = None
    check(actual_album, expected_album)

    for actual_track, expected_track in zip(actual_tracks, expected_tracks):
        check(actual_track, expected_track)
