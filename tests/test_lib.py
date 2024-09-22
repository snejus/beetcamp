"""Tests which process a bunch of Bandcamp JSONs and compare results with the specified
reference JSONs. Currently they are only executed locally and are based on
the maintainer's beets library.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cached_property, partial
from itertools import groupby, starmap
from operator import itemgetter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, NamedTuple, Tuple

import pytest
from rich.console import Group
from rich.traceback import install
from rich_tables.utils import (
    NewTable,
    border_panel,
    make_console,
    make_difftext,
    new_table,
    simple_panel,
    wrap,
)

from beetsplug.bandcamp import BandcampPlugin
from beetsplug.bandcamp.metaguru import Metaguru

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.fixtures import FixtureRequest
    from beets import IncludeLazyConfig
    from beets.autotag.hooks import AttrDict
    from rich.panel import Panel

pytestmark = pytest.mark.lib

JSONDict = Dict[str, Any]

LIB_TESTS_DIR = Path("lib_tests")
JSONS_DIR = Path("jsons")

IGNORE_FIELDS = {
    "bandcamp_artist_id",
    "bandcamp_album_id",
    "art_url_id",
    "art_url",
    "comments",
    "length",
    "price",
    "mastering",
    "artwork",
    "city",
    "disctitle",
    "times_bought",
    "original_name",
}
DO_NOT_COMPARE = {"album_id", "media", "mediums", "disctitle"}
TRACK_FIELDS = ["track_alt", "artist", "title"]

install(show_locals=True, extra_lines=8, width=int(os.environ.get("COLUMNS", 150)))
console = make_console(stderr=True, record=True, highlighter=None)


class FieldDiff(NamedTuple):
    field: str
    old: Any
    new: Any

    @property
    def diff(self) -> str:
        return str(make_difftext(str(self.old), str(self.new)))


@dataclass
class Field:
    field: str
    old: Any
    new: Any
    cached: Any

    @cached_property
    def fixed(self) -> bool:
        return self.old == self.new

    @property
    def failed_new(self) -> bool:
        return not self.fixed and self.cached is None

    @cached_property
    def all_diffs(self) -> List[List[FieldDiff]]:
        old = self.cached if self.fixed else self.old

        if self.field != "tracks":
            return [[FieldDiff(self.field, str(old), str(self.new))]]

        tracks_diff = []
        for old_track, new_track in zip(old, self.new):
            track_diff = []
            for field, (old_val, new_val) in zip(
                TRACK_FIELDS, zip(old_track, new_track)
            ):
                track_diff.append(FieldDiff(field, str(old_val), str(new_val)))
            tracks_diff.append(track_diff)

        return tracks_diff

    @property
    def diffs(self) -> Iterable[FieldDiff]:
        for diff_list in self.all_diffs:
            for diff in diff_list:
                if diff.old != diff.new:
                    yield diff

    @property
    def parts(self) -> List[Tuple[str, str]]:
        color = "green" if self.fixed else "red" if self.failed_new else ""
        field = wrap(self.field, f"b {color}")

        return [
            (field, " | ".join(d.diff for d in d_list)) for d_list in self.all_diffs
        ]


albums: List[Tuple[str, str]] = []
fixed: List[Tuple[str, str, str]] = []
new_fails: List[Tuple[str, str, str]] = []


@pytest.fixture(scope="module")
def base_dir(pytestconfig: Config) -> Path:
    base: str = pytestconfig.getoption("base")
    return LIB_TESTS_DIR / base


@pytest.fixture(scope="module")
def target_dir(pytestconfig: Config) -> Path:
    target: str = pytestconfig.getoption("target")
    target_dir = LIB_TESTS_DIR / target
    target_dir.mkdir(exist_ok=True)

    return target_dir


@pytest.fixture(scope="module")
def config() -> IncludeLazyConfig:
    return BandcampPlugin().config.flatten()


@pytest.fixture(scope="session")
def oldnew() -> Dict[str, List[FieldDiff]]:
    return defaultdict(list)


@pytest.fixture(params=sorted(JSONS_DIR.glob("*.json")), ids=str)
def test_filepath(request: FixtureRequest) -> Path:
    path: Path = request.param

    return path


@pytest.fixture
def target_filepath(target_dir: Path, test_filepath: Path) -> Path:
    return target_dir / test_filepath.name


def album_table(**kwargs: JSONDict) -> Panel:
    table = new_table(*TRACK_FIELDS, show_header=False, expand=False, highlight=False)
    return simple_panel(table, **{"expand": True, "border_style": "dim cyan", **kwargs})


def _fmt_old(s: str, times: int) -> str:
    return (f"{times} x " if times > 1 else "") + wrap(s, "b s red")


@pytest.fixture
def base(base_dir: Path, test_filepath: Path) -> JSONDict:
    try:
        with (base_dir / test_filepath.name).open() as f:
            data: JSONDict = json.load(f)
            return data
    except FileNotFoundError:
        return {}


@pytest.fixture
def target(target_filepath: Path) -> JSONDict:
    try:
        with target_filepath.open() as f:
            data: JSONDict = json.load(f)
            return data
    except FileNotFoundError:
        return {}


@pytest.fixture
def guru(config: IncludeLazyConfig, test_filepath: Path) -> Metaguru:
    with test_filepath.open() as f:
        test_data = f.read()

    return Metaguru.from_html(test_data, config)


@pytest.fixture
def original_name(guru: Metaguru) -> str:
    return guru.meta["name"]


def escape(string: str) -> str:
    return str(string).replace("[", r"\[")


@pytest.fixture(scope="session")
def _report(oldnew) -> None:
    yield
    cols = []
    for field in set(oldnew.keys()) - {"comments", "genre", "track_fields"}:
        if field not in oldnew:
            continue
        field_diffs = sorted(oldnew[field], key=lambda x: x.new)
        tab = new_table()
        for new, all_old in groupby(field_diffs, lambda x: x.new):
            tab.add_row(
                " | ".join(
                    starmap(_fmt_old, Counter(escape(d.old) for d in all_old).items())
                ),
                wrap(escape(new), "b green"),
            )
        cols.append(
            simple_panel(tab, title=f"{len(field_diffs)} [magenta]{escape(field)}[/]")
        )

    if cols:
        console.print("")
        console.print(border_panel(Group(*cols), title="Field diffs"))

    fails = [x for x in new_fails if x]
    fix = [x for x in fixed if x]
    result_rows = [
        border_panel(new_table(rows=rows), title=t)
        for t, rows in [("Fixed", fix), ("Failed", fails)]
        if rows
    ]
    if albums:
        console.print(border_panel(new_table(rows=albums), title="Albums"))
    console.print("")
    if result_rows:
        console.print(new_table(rows=[result_rows]))


@pytest.fixture
def old(base: JSONDict) -> JSONDict:
    for key in IGNORE_FIELDS:
        base.pop(key, None)

    return base


@pytest.fixture
def new(
    guru: Metaguru,
    base: JSONDict,
    target: JSONDict,
    target_filepath: Path,
    original_name: str,
) -> AttrDict:
    new: AttrDict
    if "_track_" in target_filepath.name:
        new = guru.singleton
    else:
        new = next((a for a in guru.albums if a.media == "Vinyl"), guru.albums[0])
        new.album = " / ".join(dict.fromkeys(x.album for x in guru.albums))

    new.catalognum = " / ".join(
        sorted({x.catalognum for x in guru.albums if x.catalognum})
    )
    new.original_name = original_name

    if not target or new != target:
        with target_filepath.open("w") as f:
            json.dump(new, f, indent=2, sort_keys=True)

    for key in IGNORE_FIELDS:
        new.pop(key, None)
    return new


@pytest.fixture
def desc(old: AttrDict, new: AttrDict, guru: Metaguru) -> str:
    get_values = itemgetter(*TRACK_FIELDS)

    def get_tracks(data: JSONDict) -> List[Tuple[str, ...]]:
        return [tuple(get_values(t)) for t in data.get("tracks", [])]

    if "/album/" in new["data_url"]:
        old.update(albumartist=old.pop("artist", ""), tracks=get_tracks(old))
        new.update(albumartist=new.pop("artist", ""), tracks=get_tracks(new))
        artist, title = new.get("albumartist", ""), new.get("album", "")
    else:
        artist, title = new["artist"], new["title"]

    return (
        f"{make_difftext(guru.original_albumartist, artist)} - "
        f"{make_difftext(guru.original_album, title)}"
    )


@pytest.fixture
def entity_id(new: AttrDict) -> str:
    return new["album_id"] if "/album/" in new["data_url"] else new["track_id"]


@pytest.fixture
def do_field(oldnew: Dict[str, List[FieldDiff]], entity_id: str):
    url = wrap(entity_id, "dim")

    def do(table: NewTable, field: Field) -> None:
        if not field.fixed:
            for diff in field.diffs:
                oldnew[diff.field].append(diff)

        parts = field.parts
        if field.fixed:
            fixed.extend((*p, url) for p in parts)
        else:
            table.add_rows(parts)
            if field.failed_new:
                new_fails.extend((*p, url) for p in parts)
            else:
                albums.extend(parts)

    return do


@pytest.fixture
def difference(
    do_field: Callable,
    old: AttrDict,
    new: AttrDict,
    cache: pytest.Cache,
    desc: str,
    entity_id: str,
) -> bool:
    table = new_table(padding=0, expand=False, collapse_padding=True)
    compare_fields = (new.keys() | old.keys()) - DO_NOT_COMPARE
    compare_field = partial(do_field, table)

    fail = False
    for field in sorted(compare_fields):
        old_val, new_val = old.get(field), new.get(field)
        if old_val is None and new_val is None:
            continue

        cache_key = f"{entity_id}_{field}"
        cached_value = cache.get(cache_key, None)
        if old_val == new_val and cached_value is None:
            continue

        compare_field(Field(field, old_val, new_val, cached_value))
        if old_val != new_val:
            backup = new_val or ""
            fail = True
        else:
            backup = None

        cache.set(cache_key, backup)

    for lst in albums, fixed, new_fails:
        if lst and lst[-1]:
            lst.append([])

    if fail:
        console.print("")
        console.print(
            border_panel(
                table,
                title=desc,
                expand=True,
                subtitle=wrap(f"{entity_id} - {new['media']}", "dim"),
            )
        )
        return True

    return False


@pytest.mark.usefixtures("_report")
def test_file(difference: bool) -> None:
    if difference:
        pytest.fail(pytrace=False)
