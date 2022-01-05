import itertools as it
import json
import logging
import os
import re
from collections import Counter, defaultdict
from functools import partial

import pytest
from beetsplug.bandcamp import BandcampPlugin
from beetsplug.bandcamp._metaguru import Metaguru
from rich.logging import RichHandler
from rich.traceback import install
from table import border_panel, box, make_console, make_difftext, new_table, wrap

target_dir = "last_test"
compare_against = "better_test"
install(show_locals=True, extra_lines=8, width=int(os.environ.get("COLUMNS", 150)))
console = make_console()

log = logging.getLogger("beets")
if not log.handlers:
    handler = RichHandler(console=console)
    handler.setFormatter(
        logging.Formatter(fmt="{name}\t{message}", datefmt="[%X]", style="{")
    )
    log.addHandler(handler)
testfiles = os.listdir("tests/jsons")




@pytest.fixture(scope="session")
def config(request):
    return BandcampPlugin().config.flatten()


@pytest.fixture(params=testfiles)
def file(request):
    return request.param


def test_file(file, config):
    with open(os.path.join("tests/jsons", file)) as f:
        guru = Metaguru(f.read(), config)

    album = guru.album or guru.singleton
    target = os.path.join(target_dir, file)
    json.dump(album, open(target, "w"), indent=2)

    every_new = [album, *album["tracks"]]
    old_album = json.load(open(os.path.join(compare_against, file)))
    every_old = [old_album, *old_album["tracks"]]

    album_name = album.get("album")
    album_id = album.get("album_id")
    # album_id = album.get("album_id")
    for new, old in zip(every_new, every_old):
        title = album_name or " - ".join(
            [new.get("artist") or "", new.get("title") or ""]
        )
        table = new_table()
        for key in sorted(filter(lambda x: x not in {"tracks", "comments"}, new.keys())):
            before = re.sub(r"^\s|\s$", "", str(old.get(key) or ""))
            after = re.sub(r"^\s|\s$", "", str(new.get(key) or ""))

            if (before or after) and (before != after):
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

                table.add_row(wrap(key, "b"), difftext)

        if len(table.rows):
            console.log(
                border_panel(
                    table, title=wrap(title, "b"), subtitle=album_id, box=box.ROUNDED
                )
            )
            pytest.fail(pytrace=False)


# @pytest.mark.skip
def test_lib():
    # compare_against = "desc_ep"
    # os.makedirs(target_dir)

    failed = []
    stats_map = defaultdict(lambda: 0)
    config = BandcampPlugin().config.flatten()
    removed = defaultdict(list)
    added = defaultdict(list)
    for testfile in testfiles:
        json_in = open(os.path.join("tests/jsons", testfile)).read()
        guru = Metaguru(json_in, config)
        try:
            album = guru.album
            if not album:
                album = guru.singleton
        except Exception:
            failed.append(testfile)
            continue

        target = os.path.join(target_dir, testfile)
        json.dump(album, open(target, "w"), indent=2)
        # albums.append(album)

        every_new = [album, *album["tracks"]]
        old_album = json.load(open(os.path.join(compare_against, testfile)))
        every_old = [old_album, *old_album["tracks"]]

        album_name = album.get("album")
        album_id = album.get("album_id")
        # album_id = album.get("album_id")
        for new, old in zip(every_new, every_old):
            title = album_name or " - ".join(
                [new.get("artist") or "", new.get("title") or ""]
            )
            table = new_table()
            for key in sorted(
                filter(lambda x: x not in {"length", "tracks", "comments"}, new.keys())
            ):
                before = re.sub(r"^\s|\s$", "", str(old.get(key) or ""))
                after = re.sub(r"^\s|\s$", "", str(new.get(key) or ""))

                if (before or after) and (before != after):
                    stats_map[key] += 1
                    if key == "genre":
                        before, after = set(before.split(", ")), set(after.split(", "))
                        common, gone, added_new = (
                            before & after,
                            before - after,
                            after - before,
                        )
                        diffparts = list(
                            map(partial(wrap, tag="b #111111"), sorted(common))
                        )
                        if gone:
                            gone = list(map(partial(wrap, tag="b strike red"), gone))
                            removed[key].extend(gone)
                            diffparts.extend(gone)
                        if added_new:
                            added_new = list(map(partial(wrap, tag="b green"), added_new))
                            added[key].extend(added_new)
                            diffparts.extend(added_new)
                        if diffparts:
                            difftext = " | ".join(diffparts)
                    else:
                        removed[key].append(wrap(before, "b strike red"))
                        added[key].append(wrap(after, "b green"))
                        difftext = make_difftext(before, after)

                    table.add_row(wrap(key, "b"), difftext)

            if len(table.rows):
                console.print(
                    border_panel(
                        table, title=wrap(title, "b"), subtitle=album_id, box=box.ROUNDED
                    )
                )
    btable = partial(new_table, border_style="white")

    for field in set(it.chain(added.keys(), removed.keys())) - {"comments"}:
        added_and_removed = [*added[field], *removed[field]]
        if added_and_removed:
            field_table = btable(field, "# of times")
            for field_val, count in Counter(added_and_removed).most_common():
                field_table.add_row(field_val, str(count))
            console.print(
                border_panel(
                    field_table, title=wrap(f"{field} diff", "b"), box=box.ROUNDED
                )
            )

    stats_table = btable("field", "#")
    for field, count in sorted(stats_map.items(), key=lambda x: x[1], reverse=True):
        stats_table.add_row(field, str(count))
    stats_table.add_row("total", str(len(testfiles)))
    console.print(stats_table)
    pytest.fail()

    # for item, track_info in pairs:
    #     track_info["artist"] = track_info.get("artist") or cur_artist
    #     tracks_table.add_row(*_make_track_diff(item, track_info))
    # console.print(border_panel(tracks_table))

    if failed:
        pytest.fail("The following files have failed: {}".format(str(failed)))
