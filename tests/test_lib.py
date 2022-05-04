"""Tests which process a bunch of Bandcamp JSONs and compare results with the specified
reference JSONs. Currently they are only executed locally and are based on
the maintainer's beets library.
"""
import json
import os
import re
from collections import Counter, defaultdict, namedtuple
from functools import partial
from itertools import groupby
from operator import truth

import pytest
from beetsplug.bandcamp import BandcampPlugin
from beetsplug.bandcamp._metaguru import Metaguru
from rich.columns import Columns
from rich.traceback import install
from rich_tables.utils import border_panel, make_console, make_difftext, new_table, wrap

pytestmark = pytest.mark.lib

BASE_DIR = "lib_tests"
TEST_DIR = "dev"
REFERENCE_DIR = "54c0979"
JSONS_DIR = "jsons"

IGNORE_FIELDS = {
    "bandcamp_artist_id",
    "bandcamp_album_id",
    "art_url_id",
    "art_url",
    "tracks",
    "comments",
    "length",
    "price",
    "mastering",
    "artwork",
    "city",
}

target_dir = os.path.join(BASE_DIR, TEST_DIR)
compare_against = os.path.join(BASE_DIR, REFERENCE_DIR)
if not os.path.exists(target_dir):
    os.makedirs(target_dir)
install(show_locals=True, extra_lines=8, width=int(os.environ.get("COLUMNS", 150)))
console = make_console(stderr=True, record=True)

testfiles = sorted(filter(lambda x: x.endswith("json"), os.listdir(JSONS_DIR)))


Oldnew = namedtuple("Oldnew", ["old", "new", "diff"])
oldnew = defaultdict(list)

open = partial(open, encoding="utf-8")  # pylint: disable=redefined-builtin


@pytest.fixture(scope="session")
def _report():
    yield
    cols = []
    for field in set(oldnew.keys()) - {"comments", "genre"}:
        field_diffs = sorted(oldnew[field], key=lambda x: x.new)
        if not field_diffs:
            continue
        tab = new_table()
        for new, all_old in groupby(field_diffs, lambda x: x.new):
            tab.add_row(
                " | ".join(
                    map(
                        lambda x: (f"{x[1]} x " if x[1] > 1 else "")
                        + wrap(re.sub(r"\\?\[", r"\\[", x[0]), "b s red"),
                        Counter(map(lambda x: x.old, all_old)).items(),
                    )
                ),
                wrap(re.sub(r"\\?\[", r"\\[", new), "b green"),
            )
        cols.append(border_panel(tab, title=field))

    console.print("")
    console.print(Columns(cols, expand=True))

    stats_table = new_table("field", "#", border_style="white")
    for field, count in sorted(stats_map.items(), key=lambda x: x[1], reverse=True):
        stats_table.add_row(field, str(count))
    if stats_table.rows:
        stats_table.add_row("total", str(len(testfiles)))
        console.print(stats_table)
    console.save_html("results.html")


stats_map = defaultdict(lambda: 0)


@pytest.fixture(scope="module")
def config():
    yield BandcampPlugin().config.flatten()


def do_key(table, key: str, before, after) -> None:
    before = re.sub(r"^\s|\s$", "", str(before or ""))
    after = re.sub(r"^\s|\s$", "", str(after or ""))

    if (before or after) and (before != after):
        difftext = ""
        stats_map[key] += 1
        if key == "genre":
            before_set, after_set = set(before.split(", ")), set(after.split(", "))
            common, gone, added_new = (
                before_set & after_set,
                before_set - after_set,
                after_set - before_set,
            )
            diffparts = list(map(partial(wrap, tag="b #111111"), sorted(common)))
            if gone:
                gone = list(map(partial(wrap, tag="b strike red"), gone))
                diffparts.extend(gone)
            if added_new:
                added_new = list(map(partial(wrap, tag="b green"), added_new))
                diffparts.extend(added_new)
            if diffparts:
                difftext = " | ".join(diffparts)
        else:
            difftext = make_difftext(before, after)
        if difftext:
            oldnew[key].append(Oldnew(before, after, difftext))
            table.add_row(wrap(key, "b"), difftext)


def compare(old, new):
    every_new = [new]
    every_old = [old]
    if "/album/" in new["data_url"]:
        for entity in old, new:
            entity["albumartist"] = entity.pop("artist", "")
            if "tracks" in entity:
                for track in entity["tracks"]:
                    entity["disctitle"] = track.pop("disctitle", "")
                    # track.pop("media")

        every_new.extend(new.get("tracks") or [])
        every_old.extend(old.get("tracks") or [])
        desc = new.get("album")
        _id = new.get("album_id")
    else:
        desc = " - ".join([new.get("artist") or "", new.get("title") or ""])
        _id = new.get("track_id")

    table = new_table()
    for new, old in zip(every_new, every_old):
        for key in sorted(set(new.keys()).union(set(old.keys())) - IGNORE_FIELDS):
            do_key(table, key, str(old.get(key, "")), str(new.get(key, "")))

    if table.rows:
        subtitle = wrap(_id + "-" + (new.get("media") or ""), "dim")
        console.print("")
        console.print(border_panel(table, title=wrap(desc, "b"), subtitle=subtitle))
        return False
    return True


@pytest.fixture(params=testfiles)
def file(request):
    return request.param


@pytest.fixture
def guru(file, config):
    meta_file = os.path.join(JSONS_DIR, file)

    with open(meta_file) as f:
        meta = f.read()

    return Metaguru.from_html(meta, config)


@pytest.mark.usefixtures("_report")
def test_file(file, guru):
    IGNORE_FIELDS.update({"album_id", "media", "mediums", "disctitle"})

    target_file = os.path.join(target_dir, file)
    if "_track_" in file:
        new = guru.singleton
    else:
        for album in guru.albums:
            if album.media == "Vinyl":
                new = album
                break
        else:
            new = guru.albums[0]

    new.catalognum = " / ".join(filter(truth, map(lambda x: x.catalognum, guru.albums)))
    with open(target_file, "w") as f:
        json.dump(new, f, indent=2)

    try:
        with open(os.path.join(compare_against, file)) as f:
            old = json.load(f)
    except FileNotFoundError:
        old = {}

    if not compare(old, new):
        pytest.fail(pytrace=False)


@pytest.mark.usefixtures("_report")
def test_media(file, guru):
    if "_track_" in file:
        entities = [guru.singleton]
    else:
        entities = guru.albums

    same = False
    for new in entities:
        file = (new.get("album_id") or new.track_id).replace("/", "_") + ".json"
        target_file = os.path.join(target_dir, file)
        with open(target_file, "w") as f:
            json.dump(new, f, indent=2)

        try:
            with open(os.path.join(compare_against, file)) as f:
                old = json.load(f)
        except FileNotFoundError:
            old = {}
        same = compare(old, new)

    if not same:
        pytest.fail(pytrace=False)
