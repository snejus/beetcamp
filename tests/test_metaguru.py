"""Module the Metaguru class functionality."""
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
def test_comments(descr, disctitle, creds, expected, json_meta, media_format):
    media_format["description"] = disctitle
    json_meta.update(description=descr, albumRelease=[media_format], creditText=creds)
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
