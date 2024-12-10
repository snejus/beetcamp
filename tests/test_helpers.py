"""Module for the helpers module tests."""

import pytest

from beetsplug.bandcamp.helpers import Helpers, MediaInfo

pytestmark = pytest.mark.parsing


@pytest.mark.parametrize(
    "disctitle, expected",
    [
        ("2 x Vinyl LP - MTY003", 2),
        ('3 x 12" Vinyl LP - MTY003', 3),
        ("Double Vinyl LP - MTY003", 2),
        ('12" Vinyl - MTY003', 1),
        ('EP 12"Green Vinyl', 1),
        ("2LP Vinyl", 2),
    ],
)
def test_mediums_count(disctitle, expected):
    assert MediaInfo("", "Vinyl", disctitle, "").medium_count == expected


def test_unpack_props(vinyl_format):
    result = Helpers.unpack_props(vinyl_format)
    assert {"some_id", "item_type"} < set(result)


def test_bundles_get_excluded(bundle_format, digital_format):
    album_name = "Everyone Bundle"
    bundle_album_name_format = {**digital_format, "name": album_name}

    result = Helpers.get_media_formats([bundle_format, bundle_album_name_format])

    assert len(result) == 1
    assert result[0].album_id == digital_format["@id"]


@pytest.mark.parametrize(
    "artists, expected",
    [
        (["Art", "Art"], ["Art"]),
        (["Art", "Art1"], ["Art", "Art1"]),
        (["Art, Art1"], ["Art", "Art1"]),
        (["Art & Art1"], ["Art & Art1"]),
        (["Art", "Art & Art1"], ["Art", "Art1"]),
        (["Art", "Art X Art1"], ["Art", "Art1"]),
        (["1 X 1 X, Wanton"], ["1 X 1 X", "Wanton"]),
        (["1 X 1 X"], ["1 X 1 X"]),
        (["Art, Art X Art1"], ["Art", "Art1"]),
    ],
)
def test_split_artists(artists, expected):
    assert Helpers.split_artists(artists) == expected
