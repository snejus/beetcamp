"""Tests that compare beetcamp outputs against expected JSON outputs."""

import pytest
from beets.autotag.hooks import TrackInfo

from beetsplug.bandcamp.metaguru import Metaguru

pytestmark = pytest.mark.jsons


def test_bandcamp_json(beets_config, bandcamp_html, expected_release):
    guru = Metaguru.from_html(bandcamp_html, beets_config)

    actual = guru.singleton if isinstance(expected_release, TrackInfo) else guru.albums

    assert actual == expected_release
