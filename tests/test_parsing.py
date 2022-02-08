"""Module for tests related to parsing."""
from datetime import date
from operator import itemgetter

import pytest
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from beetsplug.bandcamp._metaguru import Metaguru, urlify

pytestmark = pytest.mark.parsing

console = Console(force_terminal=True, force_interactive=True)
_p = pytest.param


def print_result(case, expected, result):
    table = Table("result", *expected.keys(), show_header=True, border_style="black")
    expectedrow = []
    resultrow = []
    for key in expected.keys():
        res_color, exp_color = "dim", "dim"
        expectedval = expected.get(key)
        resultval = result.get(key)
        if resultval != expectedval:
            res_color, exp_color = "bold red", "bold green"
        expectedrow.append(Text(str(expectedval), style=exp_color))
        resultrow.append(Text(str(resultval), style=res_color))

    table.add_row("expected", *expectedrow)
    table.add_row("actual", *resultrow)

    console.print(Panel(table, title=f"[bold]{case}", title_align="left"))


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
def test_comments(descr, disctitle, creds, expected):
    meta = dict(
        description=descr,
        albumRelease=[{"musicReleaseFormat": "VinylFormat", "description": disctitle}],
        creditText=creds,
        dateModified="doesntmatter",
    )
    config = {"preferred_media": "Vinyl", "comments_separator": "\n"}
    guru = Metaguru(meta, config)
    assert guru.comments == expected, vars(guru)


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
    ("inputs", "expected"),
    [
        (("Title",), ("", "", "Title", "Title")),
        (("Artist - Title",), ("", "Artist", "Title", "Title")),
        (("A1. Artist - Title",), ("A1", "Artist", "Title", "Title")),
        (("A1- Artist - Title",), ("A1", "Artist", "Title", "Title")),
        (("A1.- Artist - Title",), ("A1", "Artist", "Title", "Title")),
        (("A1 - Title",), ("A1", "", "Title", "Title")),
        (("B2 - Artist - Title",), ("B2", "Artist", "Title", "Title")),
        (("A2.  Two Spaces",), ("A2", "", "Two Spaces", "Two Spaces")),
        (("D1 No Punct",), ("D1", "", "No Punct", "No Punct")),
        (
            ("DJ BEVERLY HILL$ - Raw Steeze",),
            ("", "DJ BEVERLY HILL$", "Raw Steeze", "Raw Steeze"),
        ),
        (
            ("LI$INGLE010 - cyberflex - LEVEL X", "LI$INGLE010"),
            ("", "cyberflex", "LEVEL X", "LEVEL X"),
        ),
        (
            ("I'll Become Pure N-R-G",),
            ("", "", "I'll Become Pure N-R-G", "I'll Become Pure N-R-G"),
        ),
        (("&$%@#!",), ("", "", "&$%@#!", "&$%@#!")),
        (("24 Hours",), ("", "", "24 Hours", "24 Hours")),
        (
            ("Some tune (Someone's Remix)",),
            ("", "", "Some tune (Someone's Remix)", "Some tune"),
        ),
        (
            ("19.85 - Colapso Inevitable",),
            ("", "19.85", "Colapso Inevitable", "Colapso Inevitable"),
        ),
        (
            ("19.85 - Colapso Inevitable (FREE)",),
            ("", "19.85", "Colapso Inevitable", "Colapso Inevitable"),
        ),
        (("E7-E5",), ("", "", "E7-E5", "E7-E5")),
        (
            ("Lacchesi - UNREALNUMBERS - MK4 (Lacchesi Remix)",),
            ("", "Lacchesi, UNREALNUMBERS", "MK4 (Lacchesi Remix)", "MK4"),
        ),
        (
            ("UNREALNUMBERS -Karaburan",),
            ("", "UNREALNUMBERS", "Karaburan", "Karaburan"),
        ),
        (
            ("Ellie Goulding- Starry Eyed ( ROWDIBOÏ EDIT))",),
            ("", "Ellie Goulding", "Starry Eyed (ROWDIBOÏ EDIT)", "Starry Eyed"),
        ),
        (
            ("Space Jam - (RZVX EDIT)",),
            ("", "", "Space Jam (RZVX EDIT)", "Space Jam"),
        ),
        (("¯\\_(ツ)_/¯",), ("", "", "¯\\_(ツ)_/¯", "¯\\_(ツ)_/¯")),
        (("VIENNA (WARM UP MIX",), ("", "", "VIENNA (WARM UP MIX", "VIENNA")),
        (
            ("MOD-R - ARE YOU RECEIVING ME",),
            ("", "MOD-R", "ARE YOU RECEIVING ME", "ARE YOU RECEIVING ME"),
        ),
        (
            ("K - The Lightning Princess",),
            ("", "K", "The Lightning Princess", "The Lightning Princess"),
        ),
        (
            ("MEAN-E - PLANETARY NEBULAE",),
            ("", "MEAN-E", "PLANETARY NEBULAE", "PLANETARY NEBULAE"),
        ),
        (("f-theme",), ("", "", "f-theme", "f-theme")),
        (
            ("Mr. Free - The 4th Room",),
            ("", "Mr. Free", "The 4th Room", "The 4th Room"),
        ),
        (("O)))Bow 1",), ("", "", "O)))Bow 1", "O)))Bow 1")),
        (("H.E.L.L.O.",), ("", "", "H.E.L.L.O.", "H.E.L.L.O.")),
        (
            (("Erik Burka - A Baby Pigeon [MNRM003]"),),
            ("", "Erik Burka", "A Baby Pigeon", "A Baby Pigeon"),
        ),
        (
            (("Artist - Title [ONE001]"), "TWO001"),
            ("", "Artist", "Title", "Title"),
        ),
    ],
)
def test_parse_track_name(inputs, expected, beets_config):
    inputs = list(inputs)
    name = inputs.pop(0)
    track = {
        "item": {
            "@id": "album_url",
            "additionalProperty": [
                {"@type": "PropertyValue", "name": "duration_secs", "value": 445.217}
            ],
            "name": name,
        },
        "position": 1,
    }
    meta = {
        "track": {"itemListElement": [track]},
        "name": "album",
        "publisher": {"name": "some label"},
        "byArtist": {"name": ""},
    }
    fields = "track_alt", "artist", "title", "main_title"
    expected = dict(zip(fields, expected))

    guru = Metaguru(meta, beets_config)
    if inputs:
        guru.catalognum = inputs[0]
    result_track = guru.tracks[0]
    result = dict(zip(fields, itemgetter(*fields)(result_track)))
    assert result == expected, print_result(name, expected, result)


@pytest.mark.parametrize(
    ("names", "catalognum", "expected"),
    [
        (
            ["1. Artist - Title", "2. Artist - Title"],
            "",
            ["Artist - Title", "Artist - Title"],
        ),
        (
            ["9 Artist - Title", "Artist - Title"],
            "",
            ["9 Artist - Title", "Artist - Title"],
        ),
        (
            ["NYH244 04 Artist - Title", "NYH244 05 Artist - Title"],
            "NYH244",
            ["Artist - Title", "Artist - Title"],
        ),
    ],
)
def test_clean_track_names(names, catalognum, expected):
    assert Metaguru.clean_track_names(names, catalognum) == expected


@pytest.mark.parametrize(
    ("parsed", "official", "albumartist", "expected"),
    [
        (None, "", "AlbumA", "AlbumA"),
        ("", "", "Artist1, Artist2", "Artist1, Artist2"),
        ("Parsed", "", "AlbumA", "Parsed"),
        ("Parsed", "Official", "AlbumA", "Parsed"),
        (None, "Official", "AlbumA", "Official"),
    ],
)
def test_get_track_artist(parsed, official, albumartist, expected):
    item = {"byArtist": {"name": official}} if official else {}
    assert Metaguru.get_track_artist(parsed, item, albumartist) == expected


@pytest.mark.parametrize(
    ("artists", "expected"), [(["4.44.444.8", "4.44.444.8"], {"4.44.444.8"})]
)
def test_track_artists(artists, expected):
    guru = Metaguru({})
    guru.tracks = [{"artist": a} for a in artists]
    assert guru.track_artists == expected


@pytest.mark.parametrize(
    ("name", "expected_digi_only", "expected_name"),
    [
        ("Artist - Track [Digital Bonus]", True, "Artist - Track"),
        ("DIGI 11. Track", True, "Track"),
        ("Digital Life", False, "Digital Life"),
        ("Messier 33 (Bandcamp Digital Exclusive)", True, "Messier 33"),
        ("33 (bandcamp exclusive)", True, "33"),
        ("Tune (Someone's Remix) [Digital Bonus]", True, "Tune (Someone's Remix)"),
        ("Hello - DIGITAL ONLY", True, "Hello"),
        ("Hello *digital bonus*", True, "Hello"),
        ("Only a Goodbye", False, "Only a Goodbye"),
        ("Track *digital-only", True, "Track"),
        ("DIGITAL 2. Track", True, "Track"),
        ("Track (digital)", True, "Track"),
        ("Bonus : Track", True, "Track"),
        ("Bonus Rave Tool", False, "Bonus Rave Tool"),
        ("TROPICOFRIO - DIGITAL DRIVER", False, "TROPICOFRIO - DIGITAL DRIVER"),
    ],
)
def test_check_digi_only(name, expected_digi_only, expected_name):
    actual_name = Metaguru.clear_digi_only(name)
    assert actual_name == expected_name
    assert (actual_name != name) == expected_digi_only


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
        ("Washington, D.C.", "US"),
        ("Seoul, South Korea", "KR"),
    ],
)
def test_parse_country(name, expected):
    guru = Metaguru({"publisher": {"foundingLocation": {"name": name}}})
    assert guru.country == expected


@pytest.mark.parametrize(
    ("album", "disctitle", "description", "label", "expected"),
    [
        ("Tracker-229 [PRH-002]", "", "", "", "PRH-002"),
        ("[PRH-002] Tracker-229", "", "", "", "PRH-002"),
        ("ISMVA003.2", "", "", "", "ISMVA003.2"),
        ("UTC003-CD", "", "", "", "UTC003-CD"),
        ("UTC-003", "", "", "", "UTC-003"),
        ("EP [SINDEX008]", "", "", "", "SINDEX008"),
        ("2 x Vinyl LP - MTY003", "", "", "", "MTY003"),
        ("Kulør 001", "", "", "Kulør", "Kulør 001"),
        ("00M", "", "", "", ""),
        ("X-Coast - Dance Trax Vol.30", "", "", "", ""),
        ("Christmas 2020", "", "", "", ""),
        ("Various Artists 001", "", "", "", ""),
        ("C30 Cassette", "", "", "", ""),
        ("BC30 Hello", "", "", "", "BC30"),
        ("Blood 1/4", "", "", "", ""),
        ("Emotion 1 - Kulør 008", "Emotion 1 Vinyl", "", "Kulør", "Kulør 008"),
        ("zz333HZ with remixes from Le Chocolat Noir", "", "", "", ""),
        ("UTC-003", "", "Catalogue Number: TE0029", "", "TE0029"),
        ("", "LP | ostgutlp31", "", "", "ostgutlp31"),
        ("Album VA001", "", "", "", ""),
        ("Album MVA001", "", "", "", "MVA001"),
        ("Need For Lead (ISM001)", "", "", "", "ISM001"),
        ("OBS.CUR 2 Depths", "", "", "", "OBS.CUR 2"),
        ("VINYL 12", "", "", "", ""),
        ("Triple 12", "", "", "", ""),
        ("IBM001V", "", "", "", "IBM001V"),
        ("fa010", "", "", "", "fa010"),
        ("", 'EP 12"', "", "", ""),
        ("Hope Works 003", "", "", "Hope Works", "Hope Works 003"),
        ("Counterspell [HMX005]", "", "", "", "HMX005"),
        ("3: Flight Of The Behemoth", "", "", "SUNN O)))", ""),
        ("[CAT001]", "", "", "\\m/ records", "CAT001"),
        ("", "", "On INS004, ", "", "INS004"),
        ("Addax EP - WU55", "", "", "", "WU55"),
        ("BAD001", "Life Without Friction (SSPB008)", "", "", "SSPB008"),
        ("", "TS G5000 hello hello t-shirt.", "", "", ""),
        ("GOOD GOOD001", "", "", "", "GOOD GOOD001"),
        ("BAd GOOD001", "", "", "", "GOOD001"),
        ("bad GOOD001", "", "", "bad GOOD", "bad GOOD001"),
        ("MNQ 049 Void Vision - Sour (2019 repress)", "", "", "", "MNQ 049"),
        ("P90-003", "", "", "", "P90-003"),
    ],
)
def test_parse_catalognum(album, disctitle, description, label, expected, beets_config):
    meta = {
        "name": album,
        "description": description,
        "publisher": {"name": label},
        "byArtist": {"name": ""},
        "albumRelease": [
            {
                "name": disctitle,
                "musicReleaseFormat": "VinylFormat",
                "description": "",
            },
        ],
    }

    assert Metaguru(meta, beets_config).catalognum == expected


@pytest.mark.parametrize(
    ("name", "extras", "expected"),
    [
        ("Album - Various Artists", [], "Album"),
        ("Various Artists - Album", [], "Album"),
        ("Various Artists Album", [], "Album"),
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
        ("Tweaker-229 [PRH-002]", ["PRH-002", "Tweaker-229"], ""),
        ("Album (limited edition)", [], "Album"),
        ("Album - VARIOUS ARTISTS", [], "Album"),
        ("Drepa Mann", [], "Drepa Mann"),
        ("Some ft. Some ONE - Album", ["Some ft. Some ONE"], "Album"),
        ("Some feat. Some ONE - Album", ["Some feat. Some ONE"], "Album"),
        ("Healing Noise (EP) (Free Download)", [], "Healing Noise"),
        ("[MCVA003] - VARIOUS ARTISTS", ["MCVA003"], ""),
        ("Drepa Mann [Vinyl]", [], "Drepa Mann"),
        ("Drepa Mann  [Vinyl]", [], "Drepa Mann"),
        ("The Castle [BLCKLPS009] Incl. Remix", ["BLCKLPS009"], "The Castle"),
        ("The Castle [BLCKLPS009] Incl. Remix", [], "The Castle"),
        ('Anetha - "Ophiuchus EP"', ["Anetha"], "Ophiuchus"),
        ("Album (FREE DL)", [], "Album"),
        ("Devils Kiss VA", [], "Devils Kiss"),
        ("Devils Kiss VA001", [], "Devils Kiss VA001"),
        (
            "Dax J - EDLX.051 Illusions Of Power",
            ["EDLX.051", "Dax J"],
            "Illusions Of Power",
        ),
        ("WEAPONS 001 - VARIOUS ARTISTS", ["WEAPONS 001"], ""),
        ("Diva Hello", [], "Diva Hello"),
        ("RR009 - Various Artist", ["RR009"], ""),
        ("Diva (Incl. some sort of Remixes)", [], "Diva"),
        ("HWEP010 - MEZZ - COLOR OF WAR", ["HWEP010", "MEZZ"], "COLOR OF WAR"),
        ("O)))Bow 1", [], "O)))Bow 1"),
        ("hi'Hello", ["hi"], "'Hello"),
        ("Blood Moon †INVI VA006†", ["INVI VA006"], "Blood Moon"),
    ],
)
def test_clean_name(name, extras, expected):
    assert Metaguru.clean_name(name, *extras, remove_extra=True) == expected


def test_bundles_get_excluded():
    meta = {
        "albumRelease": [
            {"name": "Vinyl Bundle", "musicReleaseFormat": "VinylFormat"},
            {"name": "Vinyl", "musicReleaseFormat": "VinylFormat"},
        ]
    }
    assert set(Metaguru._get_media_reference(meta)) == {"Vinyl"}


@pytest.mark.parametrize(
    ("date", "expected"), [("08 Dec 2020 00:00:00 GMT", date(2020, 12, 8)), (None, None)]
)
def test_handles_missing_publish_date(date, expected):
    guru = Metaguru({"datePublished": date})
    assert guru.release_date == expected
