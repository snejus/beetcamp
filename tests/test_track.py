"""Module for track parsing tests."""

from operator import attrgetter

import pytest

from beetsplug.bandcamp.track import Track

pytestmark = pytest.mark.parsing


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Title", ("", "", "", "Title", "Title")),
        ("Artist - Title", ("", "Artist", "", "Title", "Title")),
        ("A1. Artist - Title", ("A1", "Artist", "", "Title", "Title")),
        ("A1- Artist - Title", ("A1", "Artist", "", "Title", "Title")),
        ("A1.- Artist - Title", ("A1", "Artist", "", "Title", "Title")),
        ("A1 - Title", ("A1", "", "", "Title", "Title")),
        ("B2 - Artist - Title", ("B2", "Artist", "", "Title", "Title")),
        ("A2.  Two Spaces", ("A2", "", "", "Two Spaces", "Two Spaces")),
        ("D1 No Punct", ("D1", "", "", "No Punct", "No Punct")),
        (
            "DJ BEVERLY HILL$ - Raw Steeze",
            ("", "DJ BEVERLY HILL$", "", "Raw Steeze", "Raw Steeze"),
        ),
        ("&$%@#!", ("", "", "", "&$%@#!", "&$%@#!")),
        ("24 Hours", ("", "", "", "24 Hours", "24 Hours")),
        (
            "Some tune (Someone's Remix)",
            ("", "", "", "Some tune (Someone's Remix)", "Some tune"),
        ),
        ("19.85 - Colapso (FREE)", ("", "19.85", "", "Colapso", "Colapso")),
        (
            "Lacchesi - UNREALNUMBERS - MK4 (Lacchesi Remix)",
            ("", "UNREALNUMBERS", "", "MK4 (Lacchesi Remix)", "MK4"),
        ),
        (
            "UNREALNUMBERS -Karaburan",
            ("", "UNREALNUMBERS", "", "Karaburan", "Karaburan"),
        ),
        (
            "Ellie Goulding- Eyed ( ROWDIBOÏ EDIT))",
            ("", "Ellie Goulding", "", "Eyed (ROWDIBOÏ EDIT)", "Eyed"),
        ),
        ("Space Jam - (RZVX EDIT)", ("", "", "", "Space Jam (RZVX EDIT)", "Space Jam")),
        ("¯\\_(ツ)_/¯", ("", "", "", "¯\\_(ツ)_/¯", "¯\\_(ツ)_/¯")),
        (
            "VIENNA (WARM UP MIX",
            ("", "", "", "VIENNA (WARM UP MIX)", "VIENNA"),
        ),
        ("MOD-R - ARE YOU", ("", "MOD-R", "", "ARE YOU", "ARE YOU")),
        ("K - The Lightning", ("", "K", "", "The Lightning", "The Lightning")),
        ("MEAN-E - PLANETARY", ("", "MEAN-E", "", "PLANETARY", "PLANETARY")),
        ("f-theme", ("", "", "", "f-theme", "f-theme")),
        (
            "Mr. Free - The 4th Room",
            ("", "Mr. Free", "", "The 4th Room", "The 4th Room"),
        ),
        ("O)))Bow 1", ("", "", "", "O)))Bow 1", "O)))Bow 1")),
        ("H.E.L.L.O.", ("", "", "", "H.E.L.L.O.", "H.E.L.L.O.")),
        ("Erik Burka - Pigeon [MNRM003]", ("", "Erik Burka", "", "Pigeon", "Pigeon")),
        ("Artist - Title [ONE001]", ("", "Artist", "", "Title", "Title")),
        ("Artist + Other - Title", ("", "Artist + Other", "", "Title", "Title")),
        (
            "Artist (feat. Other) - Title",
            ("", "Artist", "feat. Other", "Title", "Title"),
        ),
        (
            "Artist (some remix) - Title",
            ("", "Artist", "", "Title (some remix)", "Title"),
        ),
        ("Artist - Title feat.Other", ("", "Artist", "feat.Other", "Title", "Title")),
        (
            "Artist - Title (some - remix)",
            ("", "Artist", "", "Title (some - remix)", "Title"),
        ),
        ("Artist - Title - -", ("", "Artist", "", "Title - -", "Title - -")),
        ("A8 - Artist - Title", ("A8", "Artist", "", "Title", "Title")),
        ("A40 - Artist - Title", ("", "A40 - Artist", "", "Title", "Title")),
        ("A8_Title", ("A8", "", "", "Title", "Title")),
        ("A Title", ("", "", "", "A Title", "A Title")),
        ("A. Title", ("A", "", "", "Title", "Title")),
        ("BB. Title", ("BB", "", "", "Title", "Title")),
        ("Artist - ;) (Original Mix)", ("", "Artist", "", ";) (Original Mix)", ";)")),
        ("Artist - Title [Presented by Other]", ("", "Artist", "", "Title", "Title")),
    ],
)
def test_parse_track_name(name, expected, json_track):
    fields = "track_alt", "artist", "ft", "title", "title_without_remix"
    expected = dict(zip(fields, expected))
    if not expected["track_alt"]:
        expected["track_alt"] = None

    result_track = Track.make({**json_track["item"], "name": name})
    result = dict(zip(fields, attrgetter(*fields)(result_track)))
    assert result == expected


@pytest.mark.parametrize(
    ("name", "expected_title", "expected_catalognum"),
    [
        ("Artist - Title CAT001", "Title CAT001", None),
        ("Artist - Title [CAT001]", "Title", "CAT001"),
    ],
)
def test_parse_catalognum_from_track_name(
    name, expected_title, expected_catalognum, json_track
):
    json_track = {
        **json_track["item"],
        "position": json_track["position"],
        "name": name,
    }

    track = Track.make(json_track)

    assert track.title == expected_title, track
    assert track.catalognum == expected_catalognum, track


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
    assert Track.clean_digi_name(name) == (expected_name, expected_digi_only)
