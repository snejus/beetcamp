"""Module for tests related to parsing."""
import json
import re

import pytest
from beetsplug.bandcamp._metaguru import NEW_BEETS, Helpers, Metaguru, urlify
from pytest_lazyfixture import lazy_fixture

pytestmark = pytest.mark.parsing


@pytest.mark.parametrize(
    ("descr", "disctitle", "creds", "expected"),
    [
        ("", "", "", ""),
        ("hello", "", "", "\n - hello"),
        ("", "Includes high-quality download", "Thanks", "\n - Credits: Thanks"),
        ("", "sick vinyl", "", "\n - sick vinyl"),
        ("sickest vinyl", "sick vinyl", "", "\n - sickest vinyl\n - sick vinyl"),
    ],
)
def test_description(descr, disctitle, creds, expected):
    meta = dict(
        description=descr,
        albumRelease=[{"musicReleaseFormat": "VinylFormat", "description": disctitle}],
        creditText=creds,
        dateModified="doesntmatter",
    )
    guru = Metaguru(json.dumps(meta), media_prefs="Vinyl")
    assert guru.description == expected, vars(guru)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("2 x Vinyl LP - MTY003", 2),
        ('3 x 12" Vinyl LP - MTY003', 3),
        ("Double Vinyl LP - MTY003", 2),
        ('12" Vinyl - MTY003', 1),
        ('EP 12"Green Vinyl', 1),
        ("2LP Vinyl", 2),
    ],
)
def test_mediums_count(name, expected):
    assert Metaguru.get_vinyl_count(name) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("LI$INGLE010 - cyberflex - LEVEL X", "li-ingle010-cyberflex-level-x"),
        ("LI$INGLE007 - Re:drum - Movin'", "li-ingle007-re-drum-movin"),
        ("X23 & Høbie - Exhibit A", "x23-h-bie-exhibit-a"),
    ],
)
def test_convert_title(title, expected):
    assert urlify(title) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Title", (None, None, "Title", "Title")),
        ("Artist - Title", (None, "Artist", "Title", "Title")),
        ("A1. Artist - Title", ("A1", "Artist", "Title", "Title")),
        ("A1- Artist - Title", ("A1", "Artist", "Title", "Title")),
        ("A1.- Artist - Title", ("A1", "Artist", "Title", "Title")),
        ("1. Artist - Title", ("1", "Artist", "Title", "Title")),
        ("1.Artist - Title", ("1", "Artist", "Title", "Title")),
        (
            "DJ BEVERLY HILL$ - Raw Steeze",
            (None, "DJ BEVERLY HILL$", "Raw Steeze", "Raw Steeze"),
        ),
        ("LI$INGLE010 - cyberflex - LEVEL X", (None, "cyberflex", "LEVEL X", "LEVEL X")),
        ("Fifty-Third ft. SYH", (None, None, "Fifty-Third ft. SYH", "Fifty-Third")),
        (
            "I'll Become Pure N-R-G",
            (None, None, "I'll Become Pure N-R-G", "I'll Become Pure N-R-G"),
        ),
        ("&$%@#!", (None, None, "&$%@#!", "&$%@#!")),
        ("24 Hours", (None, None, "24 Hours", "24 Hours")),
        (
            "Some tune (Someone's Remix)",
            (None, None, "Some tune (Someone's Remix)", "Some tune"),
        ),
        (
            "19.85 - Colapso Inevitable",
            (None, "19.85", "Colapso Inevitable", "Colapso Inevitable"),
        ),
        (
            "19.85 - Colapso Inevitable (FREE)",
            (None, "19.85", "Colapso Inevitable", "Colapso Inevitable"),
        ),
        ("E7-E5", (None, None, "E7-E5", "E7-E5")),
    ],
)
def test_parse_track_name(name, expected):
    parts = ("track_alt", "artist", "title", "main_title")
    assert Metaguru.parse_track_name(name) == dict(zip(parts, expected))


@pytest.mark.parametrize(
    ("name", "expected_digital_only", "expected_name"),
    [
        ("Artist - Track [Digital Bonus]", True, "Artist - Track"),
        ("DIGI 11. Track", True, "Track"),
        ("Digital Life", False, "Digital Life"),
        ("Messier 33 (Bandcamp Digital Exclusive)", True, "Messier 33"),
        ("33 (bandcamp exclusive)", True, "33"),
        ("Tune (Someone's Remix) [Digital Bonus]", True, "Tune (Someone's Remix)"),
        ("Hello - DIGITAL ONLY", True, "Hello"),
    ],
)
def test_check_digital_only(name, expected_digital_only, expected_name):
    actual_name, actual_digi_only = Metaguru.clean_digital_only_track(name)
    assert actual_digi_only == expected_digital_only
    assert actual_name == expected_name


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
        ("No Ones, Land", "XW"),
        ("", "XW"),
        ("Utrecht, The Netherlands", "NL"),
        ("Russia", "RU"),
        ("Montreal, Québec", "CA"),
        ("St. Louis, Missouri", "US"),
    ],
)
def test_parse_country(name, expected):
    guru = Metaguru("")
    guru.meta = {"publisher": {"foundingLocation": {"name": name}}}
    assert guru.country == expected


@pytest.mark.parametrize(
    ("album", "disctitle", "description", "expected"),
    [
        ("Tracker-229 [PRH-002]", "", "", "PRH-002"),
        ("[PRH-002] Tracker-229", "", "", "PRH-002"),
        ("Tracker-229 PRH-002", "", "", "Tracker-229"),
        ("ISMVA003.2", "", "", "ISMVA003.2"),
        ("UTC003-CD", "", "", "UTC003"),
        ("UTC-003", "", "", "UTC-003"),
        ("EP [SINDEX008]", "", "", "SINDEX008"),
        ("2 x Vinyl LP - MTY003", "", "", "MTY003"),
        ("Kulør 001", "", "", "Kulør 001"),
        ("00M", "", "", ""),
        ("X-Coast - Dance Trax Vol.30", "", "", ""),
        ("Christmas 2020", "", "", ""),
        ("Various Artists 001", "", "", ""),
        ("C30 Cassette", "", "", ""),
        ("BC30 Hello", "", "", "BC30"),
        ("Blood 1/4", "", "", ""),
        ("Emotion 1 - Kulør 008", "", "", "Kulør 008"),
        ("zz333HZ with remixes from Le Chocolat Noir", "", "", ""),
        ("UTC-003", "", "Catalogue Number: TE0029", "TE0029"),
        ("UTC-003", "", "Catalogue Nr: TE0029", "TE0029"),
        ("UTC-003", "", "Catalogue No.: TE0029", "TE0029"),
        ("UTC-003", "", "Catalogue: CTU-300", "CTU-300"),
        ("UTC-003", "", "Cat No: TE0029", "TE0029"),
        ("UTC-003", "", "Cat Nr.: TE0029", "TE0029"),
        ("UTC-003", "", "Catalogue:CTU-300", "CTU-300"),
        ("", "LP | ostgutlp31", "", "OSTGUTLP31"),
    ],
)
def test_parse_catalognum(album, disctitle, description, expected):
    assert Metaguru.parse_catalognum(album, disctitle, description) == expected


@pytest.mark.parametrize(
    ("album", "extras", "expected"),
    [
        ("Album - Various Artists", [], "Album"),
        ("Various Artists - Album", [], "Album"),
        ("Various Artists Album", [], "Various Artists Album"),
        ("Album EP", [], "Album"),
        ("Album [EP]", [], "Album"),
        ("Album (EP)", [], "Album"),
        ("Album E.P.", [], "Album"),
        ("Album LP", [], "Album"),
        ("Album [LP]", [], "Album"),
        ("Album (LP)", [], "Album"),
        ("[Label] Album EP", ["Label"], "Album"),
        ("Artist - Album EP", ["Artist"], "Album"),
        ("Label | Album", ["Label"], "Album"),
        (
            "Tweaker-229 - Tweaker-229 [PRH-002]",
            ["PRH-002", "Tweaker-229"],
            "Tweaker-229",
        ),
        ("Album (limited edition)", [], "Album"),
        ("Album - VARIOUS ARTISTS", [], "Album"),
        ("Drepa Mann", [], "Drepa Mann"),
        ("Some ft. Some ONE - Album", ["Some ft. Some ONE"], "Album"),
        ("Some feat. Some ONE - Album", ["Some feat. Some ONE"], "Album"),
        ("Healing Noise (EP) (Free Download)", [], "Healing Noise"),
        ("[MCVA003] - VARIOUS ARTISTS", ["MCVA003"], "MCVA003"),
        ("Drepa Mann [Vinyl]", [], "Drepa Mann"),
    ],
)
def test_clean_up_album_name(album, extras, expected):
    assert Metaguru.clean_up_album_name(album, *extras) == expected


def test_bundles_get_excluded():
    meta = {
        "albumRelease": [
            {"name": "Vinyl Bundle", "musicReleaseFormat": "VinylFormat"},
            {"name": "Vinyl", "musicReleaseFormat": "VinylFormat"},
        ]
    }
    assert set(Helpers._get_media_index(meta)) == {"Vinyl"}


@pytest.fixture(name="release")
def _release(request):
    """Read the json data and make it span a single line - same like it's found in htmls.
    Fixture names map to the testfiles (minus the extension).
    """
    info = request.param
    fixturename = next(iter(request._parent_request._fixture_defs.keys()))
    filename = "tests/json/{}.json".format(fixturename)
    with open(filename) as file:
        return re.sub(r"\n *", "", file.read()), info


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
def test_parse_single_track_release(release):
    html, expected = release
    guru = Metaguru(html)

    check(guru.singleton, expected.singleton)


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
        ],
    ),
    indirect=["release"],
)
def test_parse_various_types(release):
    html, expected_release = release
    guru = Metaguru(html, expected_release.media)

    actual_album = guru.album
    expected_album = expected_release.albuminfo

    assert hasattr(actual_album, "tracks")
    assert len(actual_album.tracks) == len(expected_album.tracks)

    expected_album.tracks.sort(key=lambda t: t.index)
    actual_album.tracks.sort(key=lambda t: t.index)

    for actual_track, expected_track in zip(actual_album.tracks, expected_album.tracks):
        check(actual_track, expected_track)

    actual_album.tracks = None
    expected_album.tracks = None
    check(actual_album, expected_album)
