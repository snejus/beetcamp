"""Tests which process a bunch of Bandcamp JSONs and compare results with the specified
reference JSONs. Currently they are only executed locally and are based on
the maintainer's beets library.
"""

import json
import os
from collections import Counter, defaultdict
from functools import partial
from itertools import groupby, starmap
from operator import itemgetter
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

import pytest
from _pytest.config import Config
from _pytest.fixtures import FixtureRequest
from beets import IncludeLazyConfig
from beets.autotag.hooks import AttrDict
from beetsplug.bandcamp import BandcampPlugin
from beetsplug.bandcamp.metaguru import Metaguru
from rich.console import Group
from rich.panel import Panel
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
}
DO_NOT_COMPARE = {"album_id", "media", "mediums", "disctitle"}
TRACK_FIELDS = ["track_alt", "artist", "title"]

install(show_locals=True, extra_lines=8, width=int(os.environ.get("COLUMNS", 150)))
console = make_console(stderr=True, record=True)


class FieldDiff(NamedTuple):
    old: Any
    new: Any

    @property
    def diff(self) -> str:
        return str(make_difftext(str(self.old), str(self.new)))


albums: List[Tuple[str, str]] = []
fixed: List[Tuple[str, str]] = []
new_fails: List[Tuple[str, str]] = []


@pytest.fixture(scope="module")
def base_dir(pytestconfig: Config) -> Path:
    return LIB_TESTS_DIR / pytestconfig.getoption("base")


@pytest.fixture(scope="module")
def target_dir(pytestconfig: Config) -> Path:
    target_dir = LIB_TESTS_DIR / pytestconfig.getoption("target")
    target_dir.mkdir(exist_ok=True)

    return target_dir


@pytest.fixture(scope="module")
def config() -> IncludeLazyConfig:
    return BandcampPlugin().config.flatten()


@pytest.fixture(scope="module")
def oldnew() -> Dict[str, List[FieldDiff]]:
    return defaultdict(list)


@pytest.fixture(params=sorted(JSONS_DIR.glob("*.json")), ids=str)
def test_filepath(request: FixtureRequest) -> Path:
    return request.param


@pytest.fixture
def target_filepath(target_dir: Path, test_filepath: Path) -> Path:
    return target_dir / test_filepath.name


def album_table(**kwargs: JSONDict) -> Panel:
    table = new_table(*TRACK_FIELDS, show_header=False, expand=False, highlight=False)
    return simple_panel(table, **{"expand": True, "border_style": "dim cyan", **kwargs})


def _fmt_old(s: str, times: int) -> str:
    return (f"{times} x " if times > 1 else "") + wrap(s, "b s red")


@pytest.fixture
def base(base_dir: Path, test_filepath: Path) -> AttrDict:
    try:
        with (base_dir / test_filepath.name).open() as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


@pytest.fixture
def target(target_filepath: Path) -> AttrDict:
    try:
        with target_filepath.open() as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


@pytest.fixture
def guru(config: IncludeLazyConfig, test_filepath: Path) -> Metaguru:
    with test_filepath.open() as f:
        test_data = f.read()

    return Metaguru.from_html(test_data, config)


def escape(string: str) -> str:
    return str(string).replace("[", r"\[")


@pytest.fixture(scope="module")
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

    fails = [(wrap(x[0], "red"), x[1]) for x in new_fails if x]
    fix = [(wrap(x[0], "green"), x[1]) for x in fixed if x]
    tables = [("Fixed", fix), ("Failed", fails)]
    if albums:
        tables.insert(0, ("Albums", albums))

    console.print("")
    console.print(
        new_table(
            rows=[
                [
                    border_panel(new_table(rows=rows), title=t)
                    for t, rows in tables
                    if rows
                ]
            ]
        )
    )


@pytest.fixture
def old(base: JSONDict) -> AttrDict:
    for key in IGNORE_FIELDS:
        base.pop(key, None)

    return base


@pytest.fixture
def new(
    guru: Metaguru, base: AttrDict, target: AttrDict, target_filepath: Path
) -> AttrDict:
    new = (
        guru.singleton
        if "_track_" in target_filepath.name
        else next((a for a in guru.albums if a.media == "Vinyl"), guru.albums[0])
    )

    new.catalognum = " / ".join(
        sorted({x.catalognum for x in guru.albums if x.catalognum})
    )

    if not target or new not in (base, target):
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

    return f"{artist} - {guru.meta['name']}"


@pytest.fixture
def entity_id(new: AttrDict) -> str:
    return new["album_id"] if "/album/" in new["data_url"] else new["track_id"]


@pytest.fixture(scope="module")
def do_field(oldnew):
    def do(
        table: NewTable,
        field: str,
        before: Any,
        after: Any,
        cached_value: Optional[Any] = None,
    ) -> None:
        if before == after and cached_value is None:
            return None

        key_fixed = False
        if before == after:
            key_fixed = True
            before = cached_value

        parts: List[Tuple[str, str]] = []
        if field == "tracks":
            for old_track, new_track in [
                (dict(zip(TRACK_FIELDS, a)), dict(zip(TRACK_FIELDS, b)))
                for a, b in zip(before, after)
            ]:
                field_diffs: List[str] = []
                for tfield in TRACK_FIELDS:
                    old, new = old_track[tfield], new_track[tfield]
                    diff = FieldDiff(str(old), str(new))
                    field_diffs.append(diff.diff)
                    if old != new:
                        oldnew[tfield].append(diff)
                if field_diffs:
                    parts.append(("tracks", " | ".join(field_diffs)))
        else:
            diff = FieldDiff(str(before), str(after))
            parts = [(wrap(field, "b"), diff.diff)]
            if diff.old != diff.new:
                oldnew[field].append(diff)

        if key_fixed:
            fixed.extend(parts)
            return

        table.add_rows(parts)
        if cached_value is None:
            new_fails.extend(parts)
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
        compare_field(field, old_val, new_val, cached_value=cache.get(cache_key, None))
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
