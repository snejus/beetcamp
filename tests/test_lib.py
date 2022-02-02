import itertools as it
import json
import os
import re
from collections import defaultdict
from functools import partial

import pytest
from beetsplug.bandcamp import BandcampPlugin
from beetsplug.bandcamp._metaguru import Metaguru
from rich.columns import Columns
from rich.traceback import install
from rich_tables.utils import (
    border_panel,
    box,
    make_console,
    make_difftext,
    new_table,
    simple_panel,
    wrap,
)

target_dir = "dev"
compare_against = "v0.11.0"
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
            diffs[key].add(difftext)
        table.add_row(wrap(key, "b"), difftext)


def test_file(file, config):
    with open(os.path.join("tests/jsons", file)) as f:
        guru = Metaguru(f.read(), config)

    try:
        if "_track_" in file:
            album = guru.singleton
        else:
            album = guru.album
    except Exception:
        console.print_exception(max_frames=2, show_locals=True)
        pytest.fail()

    target = os.path.join(target_dir, file)
    json.dump(album, open(target, "w"), indent=2)

    every_new = [album, *(album.get("tracks") or [])]
    old_album = json.load(open(os.path.join(compare_against, file)))
    every_old = [old_album, *(old_album.get("tracks") or [])]

    album_name = album.get("album")
    album_id = album.get("album_id")
    old_album["albumartist"] = old_album.pop("artist", "")
    album["albumartist"] = album.pop("artist", "")

    keys_excl = {"bandcamp_artist_id", "bandcamp_album_id", "art_url_id", "art_url"}
    for new, old in zip(every_new, every_old):
        title = album_name or " - ".join(
            [new.get("artist") or "", new.get("title") or ""]
        )
        table = new_table()
        for key in sorted(
            filter(lambda x: x not in {"tracks", "comments"}, set(new.keys()) - keys_excl)
        ):
            do_key(table, key, old.get(key), new.get(key))

        if len(table.rows):
            console.log(border_panel(table, title=wrap(title, "b"), subtitle=album_id))
            pytest.fail(pytrace=False)


# @pytest.mark.skip
def test_all():
    failed = []
    config = BandcampPlugin().config.flatten()
    for testfile in testfiles:
        print(testfile)
        json_in = open(os.path.join("tests/jsons", testfile)).read()
        guru = Metaguru(json_in, config)
        try:
            if "_track_" in testfile:
                album = guru.singleton
            else:
                album = guru.album
        except Exception:
            console.print_exception(show_locals=True)
            break
            # failed.append(str(exc))

        target = os.path.join(target_dir, testfile)
        json.dump(album, open(target, "w"), indent=2)

        album["albumartist"] = album.pop("artist", "")
        every_new = [album, *(album.get("tracks") or [])]
        try:
            old_album = json.load(open(os.path.join(compare_against, testfile)))
        except OSError as exc:
            failed.append(str(exc))
            continue

        old_album["albumartist"] = old_album.pop("artist", "")
        every_old = [old_album, *(old_album.get("tracks") or [])]

        album_name = album.get("album")
        album_id = wrap(album.get("album_id"), "dim")
        for new, old in zip(every_new, every_old):
            title = wrap(
                album_name
                or " - ".join([new.get("artist") or "", new.get("title") or ""]),
                "b",
            )
            table = new_table()
            for key in sorted(set(new.keys()) - {"length", "tracks", "comments"}):
                do_key(table, key, old.get(key), new.get(key))

            if len(table.rows):
                console.print(
                    simple_panel(table, title=title, subtitle=album_id, box=box.ROUNDED)
                )
    btable = partial(new_table, border_style="white")

    cols = []
    for field in set(diffs.keys()) - {"comments"}:
        if diffs[field]:
            cols.append(border_panel(Columns(diffs[field], expand=True), title=field))

    console.print(Columns(cols, expand=True))

    stats_table = btable("field", "#")
    for field, count in sorted(stats_map.items(), key=lambda x: x[1], reverse=True):
        stats_table.add_row(field, str(count))
    stats_table.add_row("total", str(len(testfiles)))
    console.print(stats_table)
    # console.print(failed)
    pytest.fail()

    # for item, track_info in pairs:
    #     track_info["artist"] = track_info.get("artist") or cur_artist
    #     tracks_table.add_row(*_make_track_diff(item, track_info))
    # console.print(border_panel(tracks_table))

    if failed:
        pytest.fail("The following files have failed: {}".format(str(failed)))
