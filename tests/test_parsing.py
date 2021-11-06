"""Module for tests related to parsing."""
import json
from datetime import date

import pytest
from beetsplug.bandcamp._metaguru import Helpers, Metaguru, urlify
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

pytestmark = pytest.mark.parsing

console = Console(
    color_system="truecolor", force_terminal=True, force_interactive=True, highlight=True
)


def print_result(case, expected, result):
    console.width = 150

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
        ("", "", "", ""),
        ("hello", "", "", "\n - hello"),
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
    ("inputs", "expected"),
    [
        (("Title",), (None, None, "Title", "Title")),
        (("Artist - Title",), (None, "Artist", "Title", "Title")),
        (("A1. Artist - Title",), ("A1", "Artist", "Title", "Title")),
        (("A1- Artist - Title",), ("A1", "Artist", "Title", "Title")),
        (("A1.- Artist - Title",), ("A1", "Artist", "Title", "Title")),
        (("A1 - Title",), ("A1", None, "Title", "Title")),
        (("B2 - Artist - Title",), ("B2", "Artist", "Title", "Title")),
        (("1. Artist - Title",), (None, "Artist", "Title", "Title")),
        (("1.Artist - Title",), (None, "Artist", "Title", "Title")),
        (
            ("DJ BEVERLY HILL$ - Raw Steeze",),
            (None, "DJ BEVERLY HILL$", "Raw Steeze", "Raw Steeze"),
        ),
        (
            ("LI$INGLE010 - cyberflex - LEVEL X", "LI$INGLE010"),
            (None, "cyberflex", "LEVEL X", "LEVEL X"),
        ),
        (("Fifty-Third ft. SYH",), (None, None, "Fifty-Third ft. SYH", "Fifty-Third")),
        (
            ("I'll Become Pure N-R-G",),
            (None, None, "I'll Become Pure N-R-G", "I'll Become Pure N-R-G"),
        ),
        (("&$%@#!",), (None, None, "&$%@#!", "&$%@#!")),
        (("24 Hours",), (None, None, "24 Hours", "24 Hours")),
        (
            ("Some tune (Someone's Remix)",),
            (None, None, "Some tune (Someone's Remix)", "Some tune"),
        ),
        (
            ("19.85 - Colapso Inevitable",),
            (None, "19.85", "Colapso Inevitable", "Colapso Inevitable"),
        ),
        (
            ("19.85 - Colapso Inevitable (FREE)",),
            (None, "19.85", "Colapso Inevitable", "Colapso Inevitable"),
        ),
        (("E7-E5",), (None, None, "E7-E5", "E7-E5")),
        (
            ("Lacchesi - UNREALNUMBERS - MK4 (Lacchesi Remix)",),
            (None, "Lacchesi, UNREALNUMBERS", "MK4 (Lacchesi Remix)", "MK4"),
        ),
        (
            ("UNREALNUMBERS -Karaburan",),
            (None, "UNREALNUMBERS", "Karaburan", "Karaburan"),
        ),
        (("A2.  Two Spaces",), ("A2", None, "Two Spaces", "Two Spaces")),
        (
            ("Ellie Goulding- Starry Eyed ( ROWDIBOÏ EDIT))",),
            (None, "Ellie Goulding", "Starry Eyed (ROWDIBOÏ EDIT)", "Starry Eyed"),
        ),
        (
            ("Space Jam - (RZVX EDIT)",),
            (None, None, "Space Jam (RZVX EDIT)", "Space Jam"),
        ),
        (("¯\\_(ツ)_/¯",), (None, None, "¯\\_(ツ)_/¯", "¯\\_(ツ)_/¯")),
        (("VIENNA (WARM UP MIX",), (None, None, "VIENNA (WARM UP MIX", "VIENNA")),
        (
            ("MOD-R - ARE YOU RECEIVING ME",),
            (None, "MOD-R", "ARE YOU RECEIVING ME", "ARE YOU RECEIVING ME"),
        ),
        (
            ("K - The Lightning Princess",),
            (None, "K", "The Lightning Princess", "The Lightning Princess"),
        ),
        (
            ("MEAN-E - PLANETARY NEBULAE",),
            (None, "MEAN-E", "PLANETARY NEBULAE", "PLANETARY NEBULAE"),
        ),
        (("f-theme",), (None, None, "f-theme", "f-theme")),
        (
            ("NYH244 04 Chris Angel - Mind Freak", "NYH244"),
            (None, "Chris Angel", "Mind Freak", "Mind Freak"),
        ),
        (
            ("Mr. Free - The 4th Room",),
            (None, "Mr. Free", "The 4th Room", "The 4th Room"),
        ),
        (("O)))Bow 1",), (None, None, "O)))Bow 1", "O)))Bow 1")),
        (("H.E.L.L.O.",), (None, None, "H.E.L.L.O.", "H.E.L.L.O.")),
    ],
)
def test_parse_track_name(inputs, expected):
    expected_track = dict(zip(("track_alt", "artist", "title", "main_title"), expected))
    result = Metaguru.parse_track_name(Metaguru.clean_name(*inputs))
    assert expected_track == result, print_result(inputs[0], expected_track, result)


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
    guru = Metaguru("")
    guru.tracks = [{"artist": a} for a in artists]
    assert guru.track_artists == expected


@pytest.mark.parametrize(
    ("artists", "expected"), [(["4.44.444.8", "4.44.444.8"], {"4.44.444.8"})]
)
def test_track_artists(artists, expected):
    guru = Metaguru("")
    guru.tracks = [{"artist": a} for a in artists]
    assert guru.track_artists == expected


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
        ("Hello *digital bonus*", True, "Hello"),
        ("Only a Goodbye", False, "Only a Goodbye"),
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
        ("Washington, D.C.", "US"),
        ("Seoul, South Korea", "KR"),
    ],
)
def test_parse_country(name, expected):
    guru = Metaguru("")
    guru.meta = {"publisher": {"foundingLocation": {"name": name}}}
    assert guru.country == expected


@pytest.mark.parametrize(
    ("album", "disctitle", "description", "label", "expected"),
    [
        ("Tracker-229 [PRH-002]", "", "", "", "PRH-002"),
        ("[PRH-002] Tracker-229", "", "", "", "PRH-002"),
        ("Tracker-229 PRH-002", "", "", "", "Tracker-229"),
        ("ISMVA003.2", "", "", "", "ISMVA003.2"),
        ("UTC003-CD", "", "", "", "UTC003"),
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
        ("UTC-003", "", "Catalogue Nr: TE0029", "", "TE0029"),
        ("UTC-003", "", "Catalogue No.: TE0029", "", "TE0029"),
        ("UTC-003", "", "Catalogue: CTU-300", "", "CTU-300"),
        ("UTC-003", "", "Cat No: TE0029", "", "TE0029"),
        ("UTC-003", "", "Cat Nr.: TE0029", "", "TE0029"),
        ("UTC-003", "", "Catalogue:CTU-300", "", "CTU-300"),
        ("Emotional Shutdown", "", "Catalog: SCTR007", "", "SCTR007"),
        ("", "LP | ostgutlp31", "", "", "ostgutlp31"),
        ("Album VA001", "", "", "", ""),
        ("Album MVA001", "", "", "", "MVA001"),
        ("Album [ROAD4]", "", "", "", "ROAD4"),
        ("Need For Lead (ISM001)", "", "", "", "ISM001"),
        ("OBS.CUR 2 Depths", "", "", "", "OBS.CUR 2"),
        ("VINYL 12", "", "", "", ""),
        ("Triple 12", "", "", "", ""),
        ("", "o-ton 113", "", "", "o-ton 113"),
        ("IBM001V", "", "", "", "IBM001V"),
        ("fa010", "", "", "", "fa010"),
        ("", 'EP 12"', "", "", ""),
        ("Hope Works 003", "", "", "Hope Works", "Hope Works 003"),
        ("Counterspell [HMX005]", "", "", "", "HMX005"),
        ("3: Flight Of The Behemoth", "", "", "SUNN O)))", ""),
        ("[CAT001]", "", "", "\\m/ records", "CAT001"),
    ],
)
def test_parse_catalognum(album, disctitle, description, label, expected):
    assert Metaguru.parse_catalognum(album, disctitle, description, label) == expected


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
        ("Tweaker-229 [PRH-002]", ["PRH-002", "Tweaker-229"], "PRH-002"),
        ("Album (limited edition)", [], "Album"),
        ("Album - VARIOUS ARTISTS", [], "Album"),
        ("Drepa Mann", [], "Drepa Mann"),
        ("Some ft. Some ONE - Album", ["Some ft. Some ONE"], "Album"),
        ("Some feat. Some ONE - Album", ["Some feat. Some ONE"], "Album"),
        ("Healing Noise (EP) (Free Download)", [], "Healing Noise"),
        ("[MCVA003] - VARIOUS ARTISTS", ["MCVA003"], "MCVA003"),
        ("Drepa Mann [Vinyl]", [], "Drepa Mann"),
        ("Drepa Mann  [Vinyl]", [], "Drepa Mann"),
        ("The Castle [BLCKLPS009] Incl. Remix", ["BLCKLPS009"], "The Castle"),
        ("The Castle [BLCKLPS009] Incl. Remix", [], "The Castle [BLCKLPS009]"),
        ('Anetha - "Ophiuchus EP"', ["Anetha"], "Ophiuchus"),
        ("Album (FREE DL)", [], "Album"),
        ("Devils Kiss VA", [], "Devils Kiss"),
        ("Devils Kiss VA001", [], "Devils Kiss VA001"),
        (
            "Dax J - EDLX.051 Illusions Of Power",
            ["EDLX.051", "Dax J"],
            "Illusions Of Power",
        ),
        ("WEAPONS 001 - VARIOUS ARTISTS", ["WEAPONS 001"], "WEAPONS 001"),
        ("Diva Hello", [], "Diva Hello"),
        ("RR009 - Various Artist", ["RR009"], "RR009"),
        ("Diva (Incl. some sort of Remixes)", [], "Diva"),
        ("HWEP010 - MEZZ - COLOR OF WAR", ["HWEP010", "MEZZ"], "COLOR OF WAR"),
        ("O)))Bow 1", [], "O)))Bow 1"),
        ("hi'Hello", ["hi"], "hi'Hello"),
        ("hi]Hello", ["hi"], "]Hello"),
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
    assert set(Helpers._get_media_index(meta)) == {"Vinyl"}


@pytest.mark.parametrize(
    ("date", "expected"), [("08 Dec 2020 00:00:00 GMT", date(2020, 12, 8)), (None, None)]
)
def test_handles_missing_publish_date(date, expected):
    guru = Metaguru("")
    guru.meta = {"datePublished": date}
    assert guru.release_date == expected
