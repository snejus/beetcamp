import pytest
from beetsplug.bandcamp.catalognum import Catalognum


@pytest.mark.parametrize(
    ("text, expected"),
    [
        ("[PRH-002] Tracker-229", "PRH-002"),
        ("ISMVA003.2", "ISMVA003.2"),
        ("UTC003-CD", "UTC003-CD"),
        ("UTC-003", "UTC-003"),
        ("EP [SINDEX008]", "SINDEX008"),
        ("2 x Vinyl LP - MTY003", "MTY003"),
        ("00M", ""),
        ("X-Coast - Dance Trax Vol.30", ""),
        ("Christmas 2020", ""),
        ("Various Artists 001", ""),
        ("C30 Cassette", ""),
        ("BC30 Hello", ""),
        ("Blood 1/4", ""),
        ("zz333HZ with remixes from Le Chocolat Noir", ""),
        ("LP | ostgutlp31", "ostgutlp31"),
        ("Album VA001", ""),
        ("Album MVA001", "MVA001"),
        ("Need For Lead (ISM001)", "ISM001"),
        ("OBS.CUR 2 Depths", ""),
        ('VINYL 12"', ""),
        ("Triple 12", ""),
        ("IBM001V", "IBM001V"),
        ("fa010", "fa010"),
        ('EP 12"', ""),
        ("Counterspell [HMX005]", "HMX005"),
        ("3: Flight Of The Behemoth", ""),
        ("[CAT001]", "CAT001"),
        ("On INS004, ", ""),
        ("TS G5000 hello hello t-shirt.", "TS G5000"),
        ("GOOD GOOD001", "GOOD001"),
        ("BAd GOOD001", "GOOD001"),
        ("MNQ 049 Void Vision", "MNQ 049"),
        ("P90-003", "P90-003"),
        ("LP. 2", ""),
        ('BAD001"', ""),
        (" catalogue number GOOD001 ", "GOOD001"),
        ("RD-9", ""),
        ("The Untold Way (Dystopian LP01)", "Dystopian LP01"),
        ("a+w lp029", "a+w lp029"),
        ("SOP 023-1322", "SOP 023-1322"),
        ("UVB76-023", "UVB76-023"),
        ("-GEN-RES-23", ""),
    ],
)
def test_anywhere_catalognum(text, expected):
    m = Catalognum.anywhere.search(text)

    assert (m.group(1) if m else "") == expected
