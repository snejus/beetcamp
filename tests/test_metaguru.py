"""Module the Metaguru class functionality."""

from copy import deepcopy
from datetime import date

import pytest

from beetcamp.metaguru import Metaguru

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


@pytest.mark.parametrize(
    "track_names, expected_titles",
    [
        (
            [
                "Satie: Complete Piano Works - Prélude en tapisserie (1906)",
                "Psaumes (1895) - 1. Losing Grip",
                "Psaumes (1895) - 2. Complicated",
            ],
            [
                "Satie: Complete Piano Works - Prélude en tapisserie (1906)",
                "Psaumes (1895) - Losing Grip",
                "Psaumes (1895) - Complicated",
            ],
        ),
        (
            [
                "Prélude en tapisserie (1906)",
                "Psaumes (1895) - 1. Losing Grip",
                "Psaumes (1895) - 2. Complicated",
            ],
            [
                "Prélude en tapisserie (1906)",
                "Psaumes (1895) - Losing Grip",
                "Psaumes (1895) - Complicated",
            ],
        ),
    ],
)
def test_prefers_root_artist_when_track_artists_look_like_title_fragments(
    json_meta, beets_config, track_names, expected_titles
):
    json_meta["name"] = "Satie: Complete Piano Works - Volume 10"
    json_meta["byArtist"]["name"] = "carrie z"
    json_meta["publisher"]["name"] = "carrie z"
    json_meta["track"]["itemListElement"] = [
        {"position": idx, "item": {"@id": f"track{idx}", "name": name}}
        for idx, name in enumerate(track_names, start=1)
    ]

    guru = Metaguru(json_meta, beets_config)

    assert guru.albumartist == "carrie z"
    assert [t.artist for t in guru.tracks] == ["carrie z", "carrie z", "carrie z"]
    assert [t.title for t in guru.tracks] == expected_titles


def test_preliminary_albumartist_ignores_soundtrack_title_prefix(json_meta, beets_config):
    json_meta["name"] = "Neon White OST 2 - The Burn That Cures"
    json_meta["byArtist"]["name"] = "Machine Girl"
    json_meta["publisher"]["name"] = "Machine Girl"
    json_meta["track"]["itemListElement"] = [
        {"position": idx, "item": {"@id": f"track{idx}", "name": name}}
        for idx, name in enumerate(
            ["Sermon", "Peace of Mind", "Heavenly Delight"],
            start=1,
        )
    ]

    guru = Metaguru(json_meta, beets_config)

    assert guru.preliminary_albumartist == "Machine Girl"
