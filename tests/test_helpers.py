"""Module for the helpers module tests."""
import pytest
from beetsplug.bandcamp._helpers import Helpers

pytestmark = pytest.mark.parsing


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
        ('VINYL 12"', "", "", "", ""),
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
        ("bad gOOD 001", "", "", "bad GOOD", "bad gOOD 001"),
        ("MNQ 049 Void Vision", "", "", "", "MNQ 049"),
        ("P90-003", "", "", "", "P90-003"),
        ("LP. 2", "", "", "", ""),
        ("", "", 'BAD001"', "", ""),
        ("", "", "Modularz 40", "Modularz", "Modularz 40"),
        ("", "", " catalogue number GOOD001 ", "", "GOOD001"),
    ],
)
def test_parse_catalognum(album, disctitle, description, label, expected):
    assert Helpers.parse_catalognum(album, disctitle, description, label) == expected


@pytest.mark.parametrize(
    ("name", "extras", "expected"),
    [
        ("Album - Various Artists", [], "Album"),
        ("Various Artists - Album", [], "Album"),
        ("Various Artists Album", [], "Various Artists Album"),
        ("Label Various Artists Album", [], "Label Various Artists Album"),
        ("Album EP", [], "Album EP"),
        ("Album [EP]", [], "Album EP"),
        ("Album (EP)", [], "Album EP"),
        ("Album E.P.", [], "Album E.P."),
        ("Album LP", [], "Album LP"),
        ("Album [LP]", [], "Album LP"),
        ("Album (LP)", [], "Album LP"),
        ("[Label] Album EP", ["Label"], "Album EP"),
        ("Artist - Album EP", ["Artist"], "Album EP"),
        ("Label | Album", ["Label"], "Album"),
        ("Tweaker-229 [PRH-002]", ["PRH-002", "Tweaker-229"], ""),
        ("Album (limited edition)", [], "Album"),
        ("Album - VARIOUS ARTISTS", [], "Album"),
        ("Drepa Mann", [], "Drepa Mann"),
        ("Some ft. Some ONE - Album", ["Some ft. Some ONE"], "Album"),
        ("Some feat. Some ONE - Album", ["Some feat. Some ONE"], "Album"),
        ("Healing Noise (EP) (Free Download)", [], "Healing Noise EP"),
        ("[MCVA003] - VARIOUS ARTISTS", ["MCVA003"], ""),
        ("Drepa Mann [Vinyl]", [], "Drepa Mann"),
        ("Drepa Mann  [Vinyl]", [], "Drepa Mann"),
        ("The Castle [BLCKLPS009] Incl. Remix", ["BLCKLPS009"], "The Castle"),
        ("The Castle [BLCKLPS009] Incl. Remix", [], "The Castle [BLCKLPS009]"),
        ('Anetha - "Ophiuchus EP"', ["Anetha"], "Ophiuchus EP"),
        ("Album (FREE DL)", [], "Album"),
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
        # only remove VA if album name starts or ends with it
        ("Album VA", [], "Album"),
        ("VA Album", [], "Album"),
        ("Album VA001", [], "Album VA001"),
        ("Album VA 03", [], "Album VA 03"),
        # remove (weird chars too) regardless of its position if explicitly excluded
        ("Album †INVI VA006†", ["INVI VA006"], "Album"),
        ("Album (Label Refix)", [], "Album (Label Refix)"),
    ],
)
def test_clean_name(name, extras, expected):
    assert Helpers.clean_album(name, *extras, label="Label") == expected


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
    assert Helpers.get_vinyl_count(name) == expected


def test_unpack_props(vinyl_format):
    result = Helpers.unpack_props(vinyl_format)
    assert {"some_id", "item_type"} < set(result)


def test_bundles_get_excluded(bundle_format, vinyl_format):
    result = Helpers.get_media_formats([bundle_format, vinyl_format])
    assert len(result) == 1
    assert result[0].name == "Vinyl"


@pytest.mark.parametrize(
    ("artists", "expected"),
    [
        (["Art", "Art"], ["Art"]),
        (["Art", "Art1"], ["Art", "Art1"]),
        (["Art, Art1"], ["Art", "Art1"]),
        (["Art & Art1"], ["Art & Art1"]),
        (["Art", "Art & Art1"], ["Art", "Art1"]),
        (["Art", "Art X Art1"], ["Art", "Art1"]),
        (["1 X 1 X, Wanton"], ["1 X 1 X", "Wanton"]),
        (["1 X 1 X"], ["1 X 1 X"]),
        (["Art, Art X Art1"], ["Art", "Art1"]),
    ],
)
def test_split_artists(artists, expected):
    assert Helpers.split_artists(artists) == expected
