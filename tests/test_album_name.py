import pytest

from beetcamp.album_name import AlbumName


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Artist ft. Artist123 - Album Name", "Album Name"),
        ("[CAT123] - Album Name", "Album Name"),
        ("CAT123 - Album Name", "Album Name"),
        ("Album Name †CAT123†", "Album Name"),
        ("Artist - Album Name EP", "Album Name EP"),
        ('Artist - "Album Name EP"', "Album Name EP"),
        ("Artist - CAT123 Album Name", "Album Name"),
        ("CAT123 - Artist - Album Name", "Album Name"),
        ("Artist'hello", "Artist'hello"),
        ("Artist's stuff and such", "Artist's stuff and such"),
        ("Artist123 [CAT123]", ""),
        ("Artist EP", "Artist EP"),
        ("Artist & Artist123 EP", "Artist & Artist123 EP"),
        ("Album Name (Artist Remix)", "Album Name (Artist Remix)"),
        ("Artist Album Name", "Artist Album Name"),
        ("Artist Vol. 1", "Artist Vol. 1"),
        ("Artist x Someone Else - Album Name", "Album Name"),
        ("[Label] Album Name EP", "Album Name EP"),
        ("Label | Album Name", "Album Name"),
        ("Album Name (Label Refix)", "Album Name (Label Refix)"),
        ("Label-Album Name", "Label-Album Name"),
        ("Label: Album Name", "Album Name"),
        ("Label: Volume 1", "Label: Volume 1"),
        ("CAT123 - VARIOUS ARTISTS", ""),
        ("Album Name [CAT123] Incl. Remix", "Album Name"),
        ("I 🫀 Artist (2025)", "I 🫀 Artist (2025)"),
    ],
)
def test_clean_name_removes_contextual_parts(name, expected):
    assert (
        AlbumName.clean(
            name,
            artists=["Artist ft. Artist123", "Artist123", "Artist"],
            catalognum="CAT123",
            label="Label",
        )
        == expected
    )


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Album Name - Various Artists", "Album Name"),
        ("Various Artists - Album Name", "Album Name"),
        ("Various Artists Album Name", "Various Artists Album Name"),
        ("Label Various Artists Album Name", "Label Various Artists Album Name"),
        ("Album Name - VARIOUS ARTISTS", "Album Name"),
        ("Album Name - Various Artist", "Album Name"),
        ("Album Name VA", "Album Name VA"),
        ("VA. Album Name", "Album Name"),
        ("VA Album Name", "VA Album Name"),
        ("Album Name VA001", "Album Name VA001"),
        ("Album Name VA 03", "Album Name VA 03"),
        ("Album Name EP", "Album Name EP"),
        ("Album Name [EP]", "Album Name EP"),
        ("Album Name (EP)", "Album Name EP"),
        ("Album Name E.P.", "Album Name E.P."),
        ("Album Name LP", "Album Name LP"),
        ("Album Name [LP]", "Album Name LP"),
        ("Album Name (LP)", "Album Name LP"),
        ("Album Name (EP) (Free Download)", "Album Name EP"),
        ("Album Name' EP", "Album Name' EP"),
        ("A good EP Album Name", "A good EP Album Name"),
        ("Album Name (LP, 2019)", "Album Name LP"),
        ("Album Name (Incl. some sort of Remixes)", "Album Name"),
        ("Album Name A vs. Artist", "Album Name A vs. Artist"),
        ("Album Name presents Artist", "Album Name presents Artist"),
        ("Title 1 + Title 2 Remixed", "Title 1 + Title 2 Remixed"),
    ],
)
def test_clean_name_normalizes_album_markers(name, expected):
    assert AlbumName.clean(name) == expected


@pytest.mark.parametrize(
    "original, expected",
    [
        ("Self-Medicating LP - WU87d", "Self-Medicating LP"),
        ("Stone Techno Series - Tetragonal EP", "Tetragonal EP"),
    ],
)
def test_parse_title(original, expected):
    assert AlbumName(original, "", "").from_title == expected


@pytest.mark.parametrize(
    "original, comments, catalognum, artists, expected",
    [
        ("CAT001 - Artist", "this Album EP", "CAT001", ["Artist"], "Album EP"),
        ("CAT001 - Artist", "other Album EP something", "CAT001", ["Artist"], "CAT001"),
        ("CAT001 - Album", "this Album LP", "CAT001", ["Artist"], "Album LP"),
    ],
)
def test_check_eplp(original, comments, catalognum, artists, expected):
    assert (
        AlbumName(original, comments, None).get(catalognum, artists, [], "") == expected
    )


@pytest.mark.parametrize(
    "original,in_desc,expected",
    [
        ("Album Vol 1", "", "Album, Vol. 1"),
        ("Album Volume 1", "", "Album, Volume 1"),
        ("Album Pt 1", "", "Album, Pt. 1"),
        ("Album Part 1", "", "Album, Part 1"),
        ("Album Vol 01", "", "Album, Vol. 1"),
        ("Vol 1 Album", "", "Album, Vol. 1"),
        ("album Vol 1", "", "album, Vol. 1"),
        ("ALBUM vol 1", "", "ALBUM, Vol. 1"),
        ("Album (vol 1)", "", "Album (Vol. 1)"),
        ("Volume 1", "Album", "Album, Volume 1"),
    ],
)
def test_standardize_series(original, in_desc, expected):
    album_name = AlbumName(
        original=original,
        description=f"Album: {in_desc}" if in_desc else "",
        from_track_titles=None,
    )
    assert album_name.standardize_series(album_name.name) == expected


@pytest.mark.parametrize(
    "original, expected",
    [
        ("Satie: Complete Piano Works - Volume 10", None),
        ("Neon White OST 2 - The Burn That Cures", None),
        ('Spencer Parker - "Remember"', "Spencer Parker"),
    ],
)
def test_find_artist(original, expected):
    album_name = AlbumName(original=original, description="", from_track_titles=None)
    assert album_name.find_artist(catalognum="") == expected
