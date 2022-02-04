import json
import os
import re
from collections import defaultdict
from functools import partial

import pytest
from rich.columns import Columns
from rich.traceback import install
from rich_tables.utils import border_panel, make_console, make_difftext, new_table, wrap

from beetsplug.bandcamp import BandcampPlugin
from beetsplug.bandcamp._metaguru import Metaguru

pytestmark = pytest.mark.lib

target_dir = "dev"
compare_against = "59da33d"
if not os.path.exists(target_dir):
    os.makedirs(target_dir)
install(show_locals=True, extra_lines=8, width=int(os.environ.get("COLUMNS", 150)))
console = make_console()

testfiles = os.listdir("tests/jsons")


@pytest.fixture(scope="session")
def config(request):
    return BandcampPlugin().config.flatten()


@pytest.fixture(params=testfiles)
def file(request):
    return request.param


diffs = defaultdict(set)
stats_map = defaultdict(lambda: 0)


def do_key(table, key: str, before, after) -> None:
    before = re.sub(r"^\s|\s$", "", str(before or ""))
    after = re.sub(r"^\s|\s$", "", str(after or ""))

    if (before or after) and (before != after):
        difftext = ""
        stats_map[key] += 1
        if key == "genre":
            before, after = set(before.split(", ")), set(after.split(", "))
            common, gone, added_new = (
                before & after,
                before - after,
                after - before,
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
            diffs[key].add(difftext)
            table.add_row(wrap(key, "b"), difftext)


def compare(old, new) -> bool:
    new["albumartist"] = new.pop("artist", "")
    every_new = [new, *(new.get("tracks") or [])]
    old["albumartist"] = old.pop("artist", "")
    every_old = [old, *(old.get("tracks") or [])]
    album_name = new.get("album")
    album_id = wrap(new.get("album_id"), "dim")
    keys_excl = {"bandcamp_artist_id", "bandcamp_album_id", "art_url_id", "art_url"}
    keys_excl.update(("tracks", "comments", "length"))
    table = new_table()
    for new, old in zip(every_new, every_old):
        title = " - ".join([new.get("artist") or "", new.get("title") or ""])
        title = wrap(album_name or title, "b")
        for key in sorted(set(new.keys()).union(set(old.keys())) - keys_excl):
            do_key(table, key, str(old.get(key)), str(new.get(key)))

    if table.rows:
        console.print(border_panel(table, title=title, subtitle=album_id))
        pytest.fail(pytrace=False)


def test_file(file, config):
    with open(os.path.join("tests/jsons", file)) as f:
        guru = Metaguru(f.read(), config)

    if "_track_" in file:
        new = guru.singleton
    else:
        new = guru.album

    target = os.path.join(target_dir, file)
    json.dump(new, open(target, "w"), indent=2)

    old = json.load(open(os.path.join(compare_against, file)))
    compare(old, new)


def test_all():
    config = BandcampPlugin().config.flatten()
    for testfile in sorted(testfiles):
        guru = Metaguru(open(os.path.join("tests/jsons", testfile)).read(), config)
        if "_track_" in testfile:
            new = guru.singleton
        else:
            new = guru.album

        target = os.path.join(target_dir, testfile)
        json.dump(new, open(target, "w"), indent=2)
        old = json.load(open(os.path.join(compare_against, testfile)))
        try:
            compare(old, new)
        except:  # noqa
            pass

    cols = []
    for field in set(diffs.keys()) - {"comments"}:
        if diffs[field]:
            cols.append(border_panel(Columns(diffs[field], expand=True), title=field))

    console.print(Columns(cols, expand=True))

    stats_table = new_table("field", "#", border_style="white")
    for field, count in sorted(stats_map.items(), key=lambda x: x[1], reverse=True):
        stats_table.add_row(field, str(count))
    if stats_table.rows:
        stats_table.add_row("total", str(len(testfiles)))
        console.print(stats_table)
        pytest.fail()
