"""Data prep / fixtures for tests."""
from dataclasses import dataclass
from datetime import date
from datetime import datetime as dt
from typing import Optional, Tuple

import pytest
from beets.autotag.hooks import AlbumInfo, TrackInfo
from beetsplug.bandcamp._metaguru import DATA_SOURCE, NEW_BEETS, OFFICIAL


@dataclass  # pylint: disable=too-many-instance-attributes
class ReleaseInfo:
    html_release_date = ""
    image: str
    album_id: str
    artist_id: str
    track_count: int
    media: str
    disctitle: Optional[str]
    singleton = None  # type: TrackInfo
    albuminfo = None  # type: AlbumInfo

    def set_html_release_date(self, _date: date):
        self.html_release_date = "released {:0>2d} {} {}".format(
            _date.day, dt.strftime(dt.strptime(str(_date.month), "%m"), "%B"), _date.year
        )

    def track_data(self, **kwargs) -> TrackInfo:
        kget = kwargs.get
        track_url = kget("track_id", f"{self.artist_id}/track/{kget('title_id')}")
        return dict(
            title=kget("title"),
            track_id=track_url,
            artist=kget("artist"),
            artist_id=self.artist_id,
            data_source=DATA_SOURCE,
            data_url=self.album_id,
            index=kget("index"),
            length=kget("length"),
            track_alt=kget("alt"),
            media=self.media,
            medium=1,
            medium_index=kget("index"),
            medium_total=self.track_count,
            disctitle=self.disctitle,
        )

    def set_singleton(self, artist: str, title: str, length: int, **kwargs) -> None:
        data = self.track_data(
            title=title,
            track_id=self.album_id,
            artist=artist,
            length=length,
            index=1,
        )
        if NEW_BEETS:
            data.update(**kwargs)
        self.singleton = TrackInfo(**data)
        self.set_html_release_date(date(kwargs["year"], kwargs["month"], kwargs["day"]))

    def set_albuminfo(self, tracks, **kwargs):
        fields = ["index", "title_id", "artist", "title", "length", "alt"]
        iter_tracks = [zip(fields, (idx, *track)) for idx, track in enumerate(tracks, 1)]
        self.albuminfo = AlbumInfo(
            album=kwargs["album"],
            album_id=self.album_id,
            artist=kwargs["albumartist"],
            artist_id=self.artist_id,
            data_url=self.album_id,
            year=kwargs["release_date"].year,
            month=kwargs["release_date"].month,
            day=kwargs["release_date"].day,
            label=kwargs["label"],
            va=kwargs["va"],
            albumtype=kwargs["albumtype"],
            catalognum=kwargs["catalognum"],
            country=kwargs["country"],
            mediums=kwargs["mediums"],
            albumstatus=OFFICIAL,
            media=self.media,
            data_source=DATA_SOURCE,
            tracks=[TrackInfo(**self.track_data(**dict(t))) for t in iter_tracks],
        )
        self.set_html_release_date(kwargs["release_date"])


@pytest.fixture
def single_track_release() -> ReleaseInfo:
    """Single track as a release on its own."""
    info = ReleaseInfo(
        image="https://f4.bcbits.com/img/a2036476476_10.jpg",
        artist_id="https://mega-tech.bandcamp.com",
        album_id="https://mega-tech.bandcamp.com/track/matriark-arangel",
        track_count=1,
        media="Digital Media",
        disctitle=None,
    )
    info.set_singleton(
        artist="Matriark",
        title="Arangel",
        length=421,
        album="Matriark - Arangel",
        albumartist="Megatech Industries",
        albumstatus="Official",
        label="Megatech Industries",
        albumtype="single",
        catalognum="",
        year=2020,
        month=11,
        day=9,
        country="SE",
    )
    return info


@pytest.fixture
def single_track_album_search() -> Tuple[str, ReleaseInfo]:
    """Single track which is part of an album release."""
    album_artist = "Alpha Tracks"
    track_url = "https://sinensis-ute.bandcamp.com/track/odondo"
    info = ReleaseInfo(
        image="https://f4.bcbits.com/img/a0610664056_10.jpg",
        artist_id="https://sinensis-ute.bandcamp.com",
        album_id="https://sinensis-ute.bandcamp.com/album/sine03",
        track_count=2,
        media="CD",
        disctitle="CD",
    )
    tracks = [
        ("live-at-parken", album_artist, "Live At PARKEN", 3600, None),
        ("odondo", album_artist, "Odondo", 371, None),
    ]
    info.set_albuminfo(
        tracks,
        album="SINE03",
        albumartist=album_artist,
        label="Sinensis",
        albumtype="ep",
        catalognum="SINE03",
        release_date=date(2020, 6, 16),
        va=False,
        country="NO",
        mediums=1,
    )
    return track_url, info


@pytest.fixture
def album() -> ReleaseInfo:
    """An album with a single artist."""
    album_artist = "Mikkel Rev"
    info = ReleaseInfo(
        image="https://f4.bcbits.com/img/a1035657740_10.jpg",
        artist_id="https://ute-rec.bandcamp.com",
        album_id="https://ute-rec.bandcamp.com/album/ute004",
        track_count=4,
        media="Vinyl",
        disctitle='12" Vinyl',
    )
    tracks = [
        (
            "the-human-experience-empathy-mix",
            album_artist,
            "The Human Experience (Empathy Mix)",
            504,
            None,
        ),
        ("parallell", album_artist, "Parallell", 487, None),
        ("formulae", album_artist, "Formulae", 431, None),
        ("biotope", album_artist, "Biotope", 421, None),
    ]
    info.set_albuminfo(
        tracks,
        album="UTE004",
        albumartist=album_artist,
        albumtype="ep",
        catalognum="UTE004",
        label="Ute.Rec",
        release_date=date(2020, 7, 17),
        va=False,
        country="NO",
        mediums=1,
    )
    return info


@pytest.fixture
def album_with_track_alt() -> ReleaseInfo:
    """An album with alternative track indexes."""
    artist_id = "https://foldrecords.bandcamp.com"
    info = ReleaseInfo(
        image="https://f4.bcbits.com/img/a2798384948_10.jpg",
        artist_id=artist_id,
        album_id=f"{artist_id}/album/fld001-gareth-wild-common-assault-ep",
        track_count=6,
        media="Vinyl",
        disctitle="FLD001 - Common Assault EP",
    )
    tracks = [
        (
            "a1-gareth-wild-live-wire",
            "Gareth Wild",
            "Live Wire",
            357,
            "A1",
        ),
        (
            "a2-gareth-wild-live-wire-roll-dann-remix",
            "Gareth Wild",
            "Live Wire ( Roll Dann Remix )",
            351,
            "A2",
        ),
        (
            "a3-gareth-wild-dds-locked-groove",
            "Gareth Wild",
            "DDS [Locked Groove]",
            20,
            "A3",
        ),
        (
            "aa1-gareth-wild-common-assault",
            "Gareth Wild",
            "Common Assault",
            315,
            "AA1",
        ),
        (
            "aa2-gareth-wild-saturn-storm",
            "Gareth Wild",
            "Saturn Storm",
            365,
            "AA2",
        ),
        (
            "aa3-gareth-wild-quadrant-locked-groove",
            "Gareth Wild",
            "Quadrant [Locked Groove]",
            20,
            "AA3",
        ),
    ]
    info.set_albuminfo(
        tracks,
        album="Common Assault",
        albumartist="Gareth Wild",
        albumtype="ep",
        catalognum="FLD001",
        label="FOLD RECORDS",
        release_date=date(2020, 11, 2),
        va=False,
        country="GB",
        mediums=1,
    )
    return info


@pytest.fixture
def compilation() -> ReleaseInfo:
    """An album with various artists."""
    info = ReleaseInfo(
        image="https://f4.bcbits.com/img/a4292881830_10.jpg",
        artist_id="https://ismusberlin.bandcamp.com",
        album_id="https://ismusberlin.bandcamp.com/album/ismva0033",
        track_count=13,
        media="Digital Media",
        disctitle=None,
    )
    tracks = [
        (
            "zebar-zimo-wish-granter-original-mix",
            "Zebar & Zimo",
            "Wish Granter (Original Mix)",
            414,
            None,
        ),
        (
            "alpha-tracks-valimba-original-mix",
            "Alpha Tracks",
            "Valimba (Original Mix)",
            361,
            None,
        ),
    ]
    info.set_albuminfo(
        tracks,
        album="ISMVA003.3",
        albumartist="Various Artists",
        albumtype="compilation",
        catalognum="ISMVA003.3",
        label="Ismus",
        release_date=date(2020, 11, 29),
        va=True,
        country="DE",
        mediums=1,
    )
    return info


@pytest.fixture
def artist_mess() -> ReleaseInfo:
    """An unusual album for testing some edge cases."""
    info = ReleaseInfo(
        image="https://f4.bcbits.com/img/0021724693_10.jpg",
        artist_id="https://psykovsky.bandcamp.com",
        album_id="https://psykovsky.bandcamp.com/album/ksolntsu",
        track_count=15,
        media="Digital Media",
        disctitle=None,
    )
    # fmt: off
    tracks = [
        ("ela-na-pame", "Psykovsky & Orestis", "Ela Na Pame", 518, None),
        ("stone-sea", "Psykovsky & Luuli", "Stone Sea", 673, None),
        ("so-we-sailed-till-we-found", "Psykovsky & Spiral", "So We Sailed Till We Found", 454, None),  # noqa
        ("doors-of-perception", "Psykovsky & Kasatka", "Doors Of Perception", 473, None),  # noqa
        ("variant-on-the-right", "Psykovsky & Spiral & Seeasound", "Variant On The Right", 736, None),  # noqa
        ("call-of-beauty", "Psykovsky & Friends", "Call Of Beauty", 769, None),
        ("many-many-krishnas", "Psykovsky & Orestis & Jobaba", "Many Many Krishnas", 729, None),  # noqa
        ("prem-i-um", "Psykovsky & Kashyyyk & Arcek", "Prem I Um", 409, None),
        ("now-here-nowhere", "Psykovsky & Arcek", "Now Here Nowhere", 557, None),
        ("holy-black-little-lark", "Psykovsky & Maleficium & Seeasound", "Holy Black / Little Lark", 1087, None),  # noqa
        ("worlds-of-wisdom", "Psykovsky & Friends", "Worlds Of Wisdom", 408, None),
        ("pc-transmission", "Psykovsky & Friends", "PC Transmission", 561, None),
        ("rs-lightmusic", "Psykovsky & Friends", "RS Lightmusic", 411, None),
        ("ksolntsu", "Psykovsky & Quip Tone Beatz & Flish", "Ksolntsu", 555, None),
        ("dadme-albricios-hijos-deva", "Birds Of Praise", "Dadme albricios hijos d'Eva", 623, None),  # noqa
    ]
    # fmt: on
    info.set_albuminfo(
        tracks,
        album="Ksolntsu",
        albumartist="Psykovsky & Friends",
        albumtype="album",
        catalognum="",
        label="Psykovsky",
        release_date=date(2015, 2, 12),
        va=False,
        country="NU",
        mediums=1,
    )
    return info


@pytest.fixture
def ep() -> ReleaseInfo:
    info = ReleaseInfo(
        image="https://f4.bcbits.com/img/a4292881830_10.jpg",
        artist_id="https://fallingapart.bandcamp.com",
        album_id="https://fallingapart.bandcamp.com/album/fa010-kickdown-vienna",
        track_count=4,
        media="Vinyl",
        disctitle='12" Vinyl',
    )
    tracks = [
        (
            "je-nne-the-devils-not-s-bl-ck-s-he-is-p-inted-h-rd-mix",
            "jeånne",
            "the devil's not ås blåck ås he is påinted (hård mix)",
            385,
            None,
        ),
        (
            "je-nne-the-p-th-to-p-r-dise-begins-in-hell",
            "jeånne",
            "the påth to pårådise begins in hell",
            333,
            None,
        ),
        (
            "dj-disrespect-vienna-warm-up-mix",
            "DJ DISRESPECT",
            "VIENNA (WARM UP MIX",
            315,
            None,
        ),
        (
            "dj-disrespect-transition-athletic-mix",
            "DJ DISRESPECT",
            "TRANSITION (ATHLETIC MIX)",
            333,
            None,
        ),
    ]
    info.set_albuminfo(
        tracks,
        album="fa010 | Kickdown Vienna",
        albumartist="jeånne, DJ DISRESPECT",
        albumtype="ep",
        catalognum="",
        label="falling apart",
        release_date=date(2020, 10, 9),
        va=False,
        country="DE",
        mediums=1,
    )
    return info
