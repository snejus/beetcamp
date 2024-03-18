"""Module for track parsing tests."""

from operator import attrgetter

import pytest
from beetsplug.bandcamp.track import Track
from beetsplug.bandcamp.tracks import Tracks
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

pytestmark = pytest.mark.parsing
_p = pytest.param


def print_result(console, case, expected, result):
    table = Table("result", *expected.keys(), show_header=True, border_style="black")
    expectedrow = []
    resultrow = []
    for key in expected:
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
        ("a2.non caps - Title", ("A2", "non caps", "", "Title", "Title")),
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
        ("E7-E5", ("", "", "", "E7-E5", "E7-E5")),
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
        ("Artist - Title - Label", ("", "Artist", "", "Title", "Title")),
        ("Title - Label", ("", "", "", "Title", "Title")),
        ("Artist - Title [Presented by Other]", ("", "Artist", "", "Title", "Title")),
    ],
)
def test_parse_track_name(name, expected, json_track, json_meta, console):
    json_track["item"].update(name=name)
    json_meta.update(track={"itemListElement": [json_track]})

    fields = "track_alt", "artist", "ft", "title", "title_without_remix"
    expected = dict(zip(fields, expected))
    if not expected["track_alt"]:
        expected["track_alt"] = None

    tracks = Tracks.from_json(json_meta)
    result_track = list(tracks)[0]
    result = dict(zip(fields, attrgetter(*fields)(result_track)))
    assert result == expected, print_result(console, name, expected, result)
