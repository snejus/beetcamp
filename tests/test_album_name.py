import pytest

from beetsplug.bandcamp.album_name import AlbumName


@pytest.mark.parametrize(
    ("name, expected"),
    [
        # ft
        ("Artist ft. Artist123 - Album", "Album"),
        # catalognum
        ("[CAT123] - Album", "Album"),
        ("CAT123 - Album", "Album"),
        ("Album †CAT123†", "Album"),
        # artist
        ("Artist - Album EP", "Album EP"),
        ('Artist - "Album EP"', "Album EP"),
        ("Artist - CAT123 Album", "Album"),
        ("CAT123 - Artist - Album", "Album"),
        ("Artist'hello", "Artist'hello"),
        ("Artist's stuff and such", "Artist's stuff and such"),
        ("Artist123 [CAT123]", ""),
        ("Artist EP", "Artist EP"),
        ("Artist & Artist123 EP", "Artist & Artist123 EP"),
        ("Album (Artist Remix)", "Album (Artist Remix)"),
        ("Artist Album", "Artist Album"),
        ("Artist Vol. 1", "Artist Vol. 1"),
        ("Artist x Someone Else - Album", "Album"),
        # VA
        ("Album - Various Artists", "Album"),
        ("Various Artists - Album", "Album"),
        ("Various Artists Album", "Various Artists Album"),
        ("Label Various Artists Album", "Label Various Artists Album"),
        ("CAT123 - VARIOUS ARTISTS", ""),
        ("Album - VARIOUS ARTISTS", "Album"),
        ("Album - Various Artist", "Album"),
        ("Album VA", "Album VA"),
        ("VA. Album", "Album"),
        ("VA Album", "VA Album"),
        ("Album VA001", "Album VA001"),
        ("Album VA 03", "Album VA 03"),
        # general cleanup
        ("Album (limited edition)", "Album"),
        ("Album [Vinyl]", "Album"),
        ("Album  [Vinyl]", "Album"),
        ("Album (FREE DL)", "Album"),
        ("Album (Single)", "Album"),
        ("Album", "Album"),
        ("[Album]", "[Album]"),
        ("(Free Download) Album", "Album"),
        ("Free Download Series - Album", "Free Download Series"),
        ("Free Download Series - Some Album", "Free Download Series - Some Album"),
        ("O)))Bow 1", "O)))Bow 1"),
        ("Album Vinylx2+cd", "Album"),
        # label
        ("[Label] Album EP", "Album EP"),
        ("Label | Album", "Album"),
        ("Album (Label Refix)", "Album (Label Refix)"),
        ("Label-Album", "Label-Album"),
        ("Label: Album", "Album"),
        ("Label: Volume 1", "Label: Volume 1"),
        # EP/LP
        ("Album EP", "Album EP"),
        ("Album [EP]", "Album EP"),
        ("Album (EP)", "Album EP"),
        ("Album E.P.", "Album E.P."),
        ("Album LP", "Album LP"),
        ("Album [LP]", "Album LP"),
        ("Album (LP)", "Album LP"),
        ("Album (EP) (Free Download)", "Album EP"),
        # Remixes
        ("Album [CAT123] Incl. Remix", "Album"),
        ("Album (Incl. some sort of Remixes)", "Album"),
        ("Album | FREE DOWNLOAD", "Album"),
    ],
)
def test_clean_name(name, expected):
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
    ("original", "expected"),
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
