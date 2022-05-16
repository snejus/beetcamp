"""Module the Metaguru class functionality."""
from copy import deepcopy
from datetime import date

import pytest
from beetsplug.bandcamp._metaguru import Metaguru

pytestmark = pytest.mark.parsing

_p = pytest.param


@pytest.mark.parametrize(
    ("descr", "disctitle", "creds", "expected"),
    [
        _p("", "", "", "", id="empty"),
        _p("hello", "", "", "hello", id="only main desc"),
        _p("", "sick vinyl", "", "sick vinyl", id="only media desc"),
        _p("", "", "credit", "credit", id="only credits"),
        _p("stuff", "sick vinyl", "creds", "stuff\nsick vinyl\ncreds", id="all"),
    ],
)
def test_comments(descr, disctitle, creds, expected, json_meta, vinyl_format):
    vinyl_format["description"] = disctitle
    json_meta.update(description=descr, albumRelease=[vinyl_format], creditText=creds)
    config = {"comments_separator": "\n"}
    assert Metaguru(json_meta, config).comments == expected


@pytest.mark.parametrize(
    ("name", "expected"),
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
def test_parse_country(name, expected, json_meta):
    json_meta["publisher"].update(foundingLocation={"name": name})
    assert Metaguru(json_meta).country == expected


@pytest.mark.parametrize(
    ("date", "expected"), [("08 Dec 2020 00:00:00 GMT", date(2020, 12, 8)), (None, None)]
)
def test_handles_missing_publish_date(date, expected, json_meta):
    json_meta.update(datePublished=date)
    assert Metaguru(json_meta).release_date == expected


def test_digi_only_option(json_track, json_meta, beets_config):
    beets_config["include_digital_only_tracks"] = False
    digi_only_track = deepcopy(json_track)
    digi_only_track["item"]["name"] = "Artist - Di Title (Digital)"
    digi_only_track["position"] = 2
    json_meta["track"]["itemListElement"].append(digi_only_track)

    guru = Metaguru(json_meta, beets_config)
    media_to_album = {a.media: a for a in guru.albums}

    assert len(media_to_album["Digital Media"].tracks) == 2
    assert len(media_to_album["Vinyl"].tracks) == 1
    assert "Digital" not in media_to_album["Vinyl"].tracks[0].title
