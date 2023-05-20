"""Tests which process a bunch of Bandcamp JSONs and compare results with the specified
reference JSONs. Currently they are only executed locally and are based on
the maintainer's beets library.
"""
import json
import os
import re
from collections import Counter, defaultdict, namedtuple
from functools import partial
from glob import glob
from itertools import groupby, starmap
from operator import itemgetter
from typing import Any, Dict, Iterable, List, Tuple

import pytest
from beetsplug.bandcamp import BandcampPlugin
from beetsplug.bandcamp._metaguru import Metaguru
from rich import print
from rich.console import Group
from rich.traceback import install
from rich_tables.utils import (
    border_panel,
    list_table,
    make_console,
    make_difftext,
    new_table,
    simple_panel,
    wrap,
)

pytestmark = pytest.mark.lib

JSONDict = Dict[str, Any]

LIB_TESTS_DIR = "lib_tests"
JSONS_DIR = "jsons"

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

install(show_locals=True, extra_lines=8, width=int(os.environ.get("COLUMNS", 150)))
console = make_console(stderr=True, record=True)


Oldnew = namedtuple("Oldnew", ["old", "new", "diff"])
oldnew = defaultdict(list)
TRACK_FIELDS = ["track_alt", "artist", "title"]


def album_table(**kwargs):
    table = new_table(*TRACK_FIELDS, show_header=False, expand=False, highlight=False)
    return simple_panel(table, **{"expand": True, "border_style": "dim cyan", **kwargs})


albums: List[Tuple[str, str]] = []
fixed: List[Tuple[str, str]] = []
new_fails: List[Tuple[str, str]] = []


open = partial(open, encoding="utf-8")  # pylint: disable=redefined-builtin


def _fmt_old(s: str, times: int) -> str:
    return (f"{times} x " if times > 1 else "") + wrap(s, "b s red")


@pytest.fixture(scope="module")
def base_dir(pytestconfig):
    return os.path.join(LIB_TESTS_DIR, pytestconfig.getoption("base"))


@pytest.fixture(scope="module")
def target_dir(pytestconfig):
    target = os.path.join(LIB_TESTS_DIR, pytestconfig.getoption("target"))
    if not os.path.exists(target):
        os.makedirs(target)
    return target


@pytest.fixture(scope="module")
def config():
    yield BandcampPlugin().config.flatten()


@pytest.fixture(params=sorted(glob(os.path.join(JSONS_DIR, "*.json"))))
def filename(request):
    return os.path.basename(request.param)


@pytest.fixture
def base(base_dir, filename) -> JSONDict:
    try:
        with open(os.path.join(base_dir, filename)) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


@pytest.fixture
def target(target_dir, filename):
    try:
        with open(os.path.join(target_dir, filename)) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


@pytest.fixture
def guru(config, filename):
    with open(os.path.join(JSONS_DIR, filename)) as f:
        test_data = f.read()

    return Metaguru.from_html(test_data, config)


def escape(string: str) -> str:
    return string.replace("[", r"\[")


@pytest.fixture(scope="session")
def _report():
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
        console.print(border_panel(Group(*cols)))

    fails = [(wrap(x[0], "red"), x[1]) for x in new_fails if x]
    fix = [(wrap(x[0], "green"), x[1]) for x in fixed if x]
    if albums:
        _tables = [albums, fix + [""] + [""] + fails]
    else:
        _tables = [fix, fails]

    _tables = list(filter(None, _tables))

    console.print("")
    console.print(new_table(rows=[[border_panel(new_table(rows=t)) for t in _tables]]))


@pytest.fixture
def new(guru, filename, base, target_dir, target):
    if "_track_" in filename:
        new = guru.singleton
    else:
        new = next((a for a in guru.albums if a.media == "Vinyl"), guru.albums[0])

    new.catalognum = " / ".join(x.catalognum for x in guru.albums if x.catalognum)

    if new not in (base, target) or not target:
        with open(os.path.join(target_dir, filename), "w") as f:
            json.dump(new, f, indent=2, sort_keys=True)

    for key in IGNORE_FIELDS:
        new.pop(key, None)
    return new


@pytest.fixture
def old(base: JSONDict) -> JSONDict:
    for key in IGNORE_FIELDS:
        base.pop(key, None)

    return base


@pytest.fixture
def desc(old, new):
    get_values = itemgetter(*TRACK_FIELDS)

    def get_tracks(data: JSONDict) -> List[Tuple[str, str, str]]:
        return [tuple(get_values(t)) for t in data.get("tracks", [])]

    if "/album/" in new["data_url"]:
        old.update(albumartist=old.pop("artist", ""), tracks=get_tracks(old))
        new.update(albumartist=new.pop("artist", ""), tracks=get_tracks(new))
        return new.get("albumartist", "") + " - " + new.get("album", "")
    else:
        return new["artist"] + " - " + new["title"]


@pytest.fixture
def entity_id(new: JSONDict) -> str:
    return new["album_id"] if "/album/" in new["data_url"] else new["track_id"]


def do_field(table, key: str, before, after, cached_value=None, album_name=None):
    if before == after and cached_value is None:
        return None

    key_fixed = False
    if before == after:
        key_fixed = True
        before = cached_value

    parts: List[Tuple[str, str]] = []
    if key == "tracks":
        for old_track, new_track in [
            (dict(zip(TRACK_FIELDS, a)), dict(zip(TRACK_FIELDS, b)))
            for a, b in zip(before, after)
        ]:
            field_diffs: List[str] = []
            for field in TRACK_FIELDS:
                old, new = old_track[field], new_track[field]
                diff = str(make_difftext(str(old), str(new)))
                field_diffs.append(diff)
                if old != new:
                    oldnew[field].append(Oldnew(old, new, diff))
            parts.append(("tracks", " | ".join(field_diffs)))
    else:
        old, new = str(before), str(after)
        difftext = make_difftext(old, new)
        parts = [(wrap(key, "b"), difftext)]
        if old != new:
            oldnew[key].append(Oldnew(before, after, difftext))

    if key_fixed:
        fixed.extend(parts)
        return None

    table.add_rows( parts)
    if cached_value is None:
        new_fails.extend(parts)
    else:
        albums.extend(parts)


@pytest.fixture
def difference(old, new, guru, cache: pytest.Cache, desc, entity_id) -> bool:
    table = new_table(padding=0, expand=False, collapse_padding=True)
    # if "album" in new and old["album"] != new["album"]:
    #     new["original_album"] = new["album"]
    #     old["original_album"] = guru.original_album

    compare_fields = (new.keys() | old.keys()) - DO_NOT_COMPARE

    compare_field = partial(do_field, table, album_name=desc)

    fail = False
    for field in sorted(compare_fields):
        old_val, new_val = old.get(field), new.get(field)
        if old_val is None and new_val is None:
            continue
        cache_key = f"{entity_id}_{field}"
        compare_field(field, old_val, new_val, cached_value=cache.get(cache_key, None))
        if old_val != new_val:
            cache.set(cache_key, new_val or "")
            fail = True
        else:
            cache.set(cache_key, None)

    for lst in albums, fixed, new_fails:
        if lst and lst[-1]:
            lst.append([])

    if fail:
        console.print("")
        console.print(
            border_panel(
                table,
                title=escape(wrap(desc, "b")),
                expand=True,
                subtitle=wrap(f"{entity_id} - {new['media']}", "dim"),
            )
        )
        return True

    return False


@pytest.mark.usefixtures("_report")
def test_file(difference):
    if difference:
        pytest.fail(pytrace=False)
