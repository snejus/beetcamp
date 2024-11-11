import pytest

from beetsplug.bandcamp.metaguru import Metaguru


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
        ("BC30 Hello", "", "", "", ""),
        ("Blood 1/4", "", "", "", ""),
        ("Emotion 1 - Kulør 008", "Emotion 1 Vinyl", "", "Kulør", "Kulør 008"),
        ("zz333HZ with remixes from Le Chocolat Noir", "", "", "", ""),
        ("UTC-003", "Catalogue Number: TE0029", "", "", "TE0029"),
        ("", "LP | ostgutlp31", "", "", "ostgutlp31"),
        ("Album VA001", "", "", "", ""),
        ("Album MVA001", "", "", "", "MVA001"),
        ("Need For Lead (ISM001)", "", "", "", "ISM001"),
        ("OBS.CUR 2 Depths", "", "", "", ""),
        ('VINYL 12"', "", "", "", ""),
        ("Triple 12", "", "", "", ""),
        ("IBM001V", "", "", "", "IBM001V"),
        ("fa010", "", "", "", "fa010"),
        ("", 'EP 12"', "", "", ""),
        ("Hope Works 003", "", "", "Hope Works", "Hope Works 003"),
        ("Counterspell [HMX005]", "", "", "", "HMX005"),
        ("3: Flight Of The Behemoth", "", "", "SUNN O)))", ""),
        ("[CAT001]", "", "", "\\m/ records", "CAT001"),
        ("", "", "On INS004, ", "", ""),
        ("WU55", "", "", "", ""),
        (" - WU55", "", "", "", "WU55"),
        ("BAD001", "Life Without Friction (SSPB008)", "", "", "SSPB008"),
        ("", "TS G5000 hello hello t-shirt.", "", "", "TS G5000"),
        ("GOOD GOOD001", "", "", "", "GOOD001"),
        ("BAd GOOD001", "", "", "", "GOOD001"),
        ("bad gOOD 001", "", "", "bad GOOD", "bad gOOD 001"),
        ("MNQ 049 Void Vision", "", "", "", "MNQ 049"),
        ("P90-003", "", "", "", "P90-003"),
        ("LP. 2", "", "", "", ""),
        ("", "", 'BAD001"', "", ""),
        ("", "", "Modularz 40", "Modularz", "Modularz 40"),
        ("", "", " catalogue number GOOD001 ", "", "GOOD001"),
        ("", "", "RD-9", "", ""),
        ("The Untold Way (Dystopian LP01)", "", "", "", "Dystopian LP01"),
        ("", "a+w lp029", "", "", "a+w lp029"),
        ("SOP 023-1322", "", "", "", "SOP 023-1322"),
        ("", "UVB76-023", "", "", "UVB76-023"),
        ("", "-GEN-RES-23", "", "", ""),
        ("Global Amnesia 1.1", "", "", "Global Amnesia", "Global Amnesia 1.1"),
        ("", "", "Hardcore Classic 014", "", ""),
        ("", "", "Cat.VIX016", "", "VIX016"),
        ("CAT123 EP", "", "", "", ""),
        ("CAT123 ep", "", "", "", ""),
        ("CAT VA1", "", "", "", ""),
        ("CAT va12", "", "", "", ""),
        ("CATVA1", "", "", "", "CATVA1"),
        ("Label 1234", "", "", "Label", "Label 1234"),
        ("Label 2020", "", "", "Label", ""),
    ],
)
def test_parse_catalognum(
    json_meta,
    vinyl_format,
    album,
    disctitle,
    description,
    label,
    expected,
    beets_config,
):
    json_meta["name"] = album
    json_meta["publisher"]["name"] = label or "Label"
    json_meta["description"] = description
    json_meta["albumRelease"] = [{**vinyl_format, "name": disctitle}]

    guru = Metaguru(json_meta, beets_config)

    assert guru.catalognum == expected
