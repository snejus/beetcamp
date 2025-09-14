"""Module the Metaguru class functionality."""

from copy import deepcopy
from datetime import date

import pytest

from beetsplug.bandcamp.metaguru import Metaguru

pytestmark = pytest.mark.parsing

_p = pytest.param


@pytest.mark.parametrize(
    "release_desc, vinyl_desc, creds, expected",
    [
        _p("", "", "", None, id="empty"),
        _p("hello", "", "", "hello", id="only main desc"),
        _p("", "sick vinyl", "", "sick vinyl", id="only media desc"),
        _p("", "", "credit", "credit", id="only credits"),
        _p("stuff", "sick vinyl", "creds", "stuff\nsick vinyl\ncreds", id="all"),
        _p("hello", "hello", "", "hello", id="no dupes"),
        _p("Hello hi", "hello,hi", "", "Hello hi", id="no dupes normalized"),
    ],
)
def test_comments(creds, expected, json_meta):
    json_meta.update(creditText=creds)
    config = {"comments_separator": "\n"}
    assert Metaguru(json_meta, config).comments == expected


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Berlin, Germany", "DE"),
        ("Oslo, Norway", "NO"),
        ("London, UK", "GB"),
        ("Malmö, Sweden", "SE"),
        ("UK", "GB"),
        ("Seattle, Washington", "US"),
        ("Los Angeles, California", "US"),
        ("New York", "US"),
        ("No, Ones Land", "XW"),
        ("", "XW"),
        ("Utrecht, The Netherlands", "NL"),
        ("Russia", "RU"),
        ("Montreal, Québec", "CA"),
        ("St. Louis, Missouri", "US"),
        ("Washington, D.C.", "US"),
        ("Seoul, South Korea", "KR"),
    ],
)
def test_parse_country(beets_config, name, expected, json_meta):
    json_meta["publisher"].update(foundingLocation={"name": name})
    assert Metaguru(json_meta, beets_config).country == expected


@pytest.mark.parametrize(
    "date, expected",
    [("08 Dec 2020 00:00:00 GMT", date(2020, 12, 8)), (None, None)],
)
def test_handles_missing_publish_date(beets_config, date, expected, json_meta):
    json_meta.update(datePublished=date)
    assert Metaguru(json_meta, beets_config).release_date == expected


def test_digi_only_option(json_track, json_meta, beets_config):
    beets_config["include_digital_only_tracks"] = False
    digi_only_track = deepcopy(json_track)
    digi_only_track["item"]["name"] = "Artist - Di Title (Digital)"
    digi_only_track["position"] = 2
    json_meta["track"]["itemListElement"].append(digi_only_track)

    guru = Metaguru(json_meta, beets_config)
    media_to_album = {a.media: a for a in guru.albums}

    assert len(media_to_album["Digital Media"].tracks) == len(
        json_meta["track"]["itemListElement"]
    )
    assert len(media_to_album["Vinyl"].tracks) == 1
    assert "Digital" not in media_to_album["Vinyl"].tracks[0].title


def test_artist_parsing_with_dash_separators_in_titles(beets_config):
    """Test that track titles with ' - ' separators don't override JSON album artist.

    This reproduces the issue where:
    - Track titles like "Satie: Complete Piano Works - Track Title" were parsed
      as artist + title
    - Multiple different "artists" from track titles created a combined
      albumartist
    - The correct albumartist "carrie z" from JSON metadata was ignored

    See: https://github.com/snejus/beetcamp/issues/47
    """
    # Mock data based on the carrie z issue
    mock_data = {
        "@id": "https://carriez.bandcamp.com/album/satie-complete-piano-works-volume-10",
        "name": "Satie: Complete Piano Works Volume 10",
        "byArtist": {
            "@id": "https://carriez.bandcamp.com/",
            "name": "carrie z"
        },
        "publisher": {
            "@id": "https://carriez.bandcamp.com/",
            "name": "carrie z"
        },
        "track": {
            "itemListElement": [
                {
                    "item": {
                        "@id": "https://carriez.bandcamp.com/track/prelude",
                        "name": "Satie: Complete Piano Works - Prélude en "
                               "tapisserie (1906)",
                        "position": 1
                    },
                    "byArtist": {"name": ""}
                },
                {
                    "item": {
                        "@id": "https://carriez.bandcamp.com/track/psaumes",
                        "name": "Psaumes (1895) - 1. Losing Grip",
                        "position": 2
                    },
                    "byArtist": {"name": ""}
                },
                {
                    "item": {
                        "@id": "https://carriez.bandcamp.com/track/another",
                        "name": "Satie: Complete Piano Works - Another Track",
                        "position": 3
                    },
                    "byArtist": {"name": ""}
                },
                {
                    "item": {
                        "@id": "https://carriez.bandcamp.com/track/psaumes2",
                        "name": "Psaumes (1895) - 2. Another One",
                        "position": 4
                    },
                    "byArtist": {"name": ""}
                },
                {
                    "item": {
                        "@id": "https://carriez.bandcamp.com/track/final",
                        "name": "Satie: Complete Piano Works - Final Track",
                        "position": 5
                    },
                    "byArtist": {"name": ""}
                }
            ]
        }
    }

    guru = Metaguru(mock_data, beets_config)

    # Test that the albumartist is correctly set to the JSON artist
    assert guru.albumartist == "carrie z"

    # Test that all tracks have the correct artist
    for i, track in enumerate(guru.tracks, 1):
        assert track.artist == "carrie z", \
            f"Track {i} artist should be 'carrie z', got '{track.artist}'"

    # Test that track titles contain the previously parsed "artist" parts
    expected_titles = [
        "Satie: Complete Piano Works - Prélude en tapisserie (1906)",
        "Psaumes (1895) - 1. Losing Grip",
        "Satie: Complete Piano Works - Another Track",
        "Psaumes (1895) - 2. Another One",
        "Satie: Complete Piano Works - Final Track"
    ]

    for i, (track, expected_title) in enumerate(zip(guru.tracks,
                                                    expected_titles), 1):
        assert track.title == expected_title, \
            f"Track {i} title should be '{expected_title}', got '{track.title}'"
