"""Tests which process a bunch of Bandcamp JSONs and compare results with the specified
reference JSONs. Currently they are only executed locally and are based on
the maintainer's beets library.
"""
import json
import os
from collections import Counter, defaultdict, namedtuple
from functools import partial
from glob import glob
from itertools import groupby, starmap

import pytest
from beetsplug.bandcamp import BandcampPlugin
from beetsplug.bandcamp._metaguru import Metaguru
from rich.console import Group
from rich.traceback import install
from rich_tables.utils import (
    border_panel,
    make_console,
    make_difftext,
    new_table,
    simple_panel,
    wrap,
)

pytestmark = pytest.mark.lib

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
DO_NOT_COMPARE = set()

install(show_locals=True, extra_lines=8, width=int(os.environ.get("COLUMNS", 150)))
console = make_console(stderr=True, record=True)


Oldnew = namedtuple("Oldnew", ["old", "new", "diff"])
oldnew = defaultdict(list)
TRACK_FIELDS = ["track_alt", "artist", "title"]


def album_table(**kwargs):
    table = new_table(*TRACK_FIELDS, show_header=False, expand=False, highlight=False)
    return border_panel(table, **{"expand": True, **kwargs})


albums = defaultdict(album_table)
fixed = defaultdict(lambda: album_table(border_style="green"))
new_fails = defaultdict(lambda: album_table(border_style="red"))


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
def base(base_dir, filename):
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
                " | ".join(starmap(_fmt_old, Counter(d.old for d in all_old).items())),
                wrap(new, "b green"),
            )
        cols.append(simple_panel(tab, title=f"{len(field_diffs)} [magenta]{field}[/]"))

    if cols:
        console.print("")
        console.print(border_panel(Group(*cols)))
    console.print("")
    console.print(Group(*(t for t in albums.values() if t.renderable.rows)))
    console.print("")
    console.print(Group(*(t for t in fixed.values() if t.renderable.rows)))
    console.print("")
    console.print(Group(*(t for t in new_fails.values() if t.renderable.rows)))


def do_key(table, key: str, before, after, cached_value=None, album_name=None):
    if before == after and cached_value is None:
        return None

    key_fixed = False
    if before == after:
        key_fixed = True
        before = cached_value

    parts = []
    if key == "tracks":
        for old_track, new_track in [
            (dict(zip(TRACK_FIELDS, a)), dict(zip(TRACK_FIELDS, b)))
            for a, b in zip(before, after)
        ]:
            diffs = []
            for field in TRACK_FIELDS:
                old, new = old_track[field], new_track[field]
                diff = make_difftext(str(old), str(new))
                diffs.append(diff)
                if old != new:
                    oldnew[field].append(Oldnew(old, new, str(diff)))
            parts.append(diffs)
    else:
        old, new = str(before), str(after)
        difftext = make_difftext(old, new)
        parts = [[wrap(key, "b"), difftext]]
        if not key_fixed:
            oldnew[key].append(Oldnew(before, after, difftext))

    if key_fixed:
        fixed[album_name].renderable.add_rows(parts)
        return None

    table.add_rows(parts)
    if cached_value is None:
        new_fails[album_name].renderable.add_rows(parts)
    else:
        albums[album_name].renderable.add_rows(parts)
    return after


def compare(old, new, cache) -> bool:
    if "/album/" in new["data_url"]:
        old.update(
            albumartist=old.pop("artist", ""),
            tracks=[
                tuple(t.get(f, "") for f in TRACK_FIELDS) for t in old.get("tracks", [])
            ],
        )
        new.update(
            albumartist=new.pop("artist", ""),
            tracks=[
                tuple(t.get(f, "") for f in TRACK_FIELDS) for t in new.get("tracks", [])
            ],
        )
        desc = f"{new.get('albumartist', '')} - {new.get('album', '')}"
        _id = new["album_id"]
    else:
        desc, _id = f"{new['artist']} - {new['title']}", new["track_id"]

    table = new_table(padding=0, expand=False, collapse_padding=True)
    for key in IGNORE_FIELDS:
        new.pop(key, None)
        old.pop(key, None)

    all_fields = set(new).union(set(old))

    compare_key = partial(do_key, table, album_name=desc)

    fail = False
    for key in sorted(all_fields - DO_NOT_COMPARE):
        values = old.get(key), new.get(key)
        if values[0] is None and values[1] is None:
            continue
        cache_key = f"{_id}_{key}"
        out = compare_key(key, *values, cached_value=cache.get(cache_key, None))
        if values[0] != values[1]:
            cache.set(cache_key, out or "")
            fail = True
        else:
            cache.set(cache_key, None)

    albums[desc].title = desc
    fixed[desc].title = desc
    new_fails[desc].title = desc
    if fail:
        subtitle = wrap(f"{_id} - {new['media']}", "dim")
        console.print("")
        console.print(
            border_panel(table, title=wrap(desc, "b"), expand=True, subtitle=subtitle)
        )
        new_fails[desc].title = desc
        return False
    return True


@pytest.mark.usefixtures("_report")
def test_file(base, target_dir, target, filename, guru, cache: pytest.Cache):
    DO_NOT_COMPARE.update({"album_id", "media", "mediums", "disctitle"})
    if "_track_" in filename:
        new = guru.singleton
    else:
        albums = guru.albums
        new = albums[0]
        for album in albums:
            if album.media == "Vinyl":
                new = album
                break

    new.catalognum = " / ".join(x.catalognum for x in guru.albums if x.catalognum)

    if new not in (base, target) or not target:
        with open(os.path.join(target_dir, filename), "w") as f:
            json.dump(new, f, indent=2, sort_keys=True)

    if not compare(base, new, cache):
        pytest.fail(pytrace=False)
