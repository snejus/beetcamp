"""Module for the plugin functionality that has to do with beets."""

import pytest
from beets.library import Item
from beetsplug.bandcamp import BandcampPlugin


@pytest.fixture(name="guru")
def _guru():
    def call(field):
        return {"description": "new_description", "lyrics": "new_lyrics"}[field]

    return call


@pytest.mark.parametrize(
    "item,excluded,expected",
    [
        (
            Item(),
            set(),
            {"description": "new_description", "lyrics": "new_lyrics"},
        ),
        (
            Item(comments="old_description"),
            set(),
            {"description": "old_description", "lyrics": "new_lyrics"},
        ),
        (
            Item(comments="Visit https://bandcamp"),
            set(),
            {"description": "new_description", "lyrics": "new_lyrics"},
        ),
    ],
)
def test_add_additional_data(item, excluded, expected, guru):
    pl = BandcampPlugin()

    pl.verify_and_add(item, guru, excluded)
    assert item.comments == expected["description"]
    assert item.lyrics == expected["lyrics"]
