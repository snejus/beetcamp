import pytest
from beetsplug.bandcamp.track import Track


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
    json_track = {**json_track["item"], "position": json_track["position"]}

    track = Track.make(json_track, name)
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
