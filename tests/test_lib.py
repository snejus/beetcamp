"""Tests which process a bunch of Bandcamp JSONs and compare results with the specified
reference JSONs. Currently they are only executed locally and are based on
the maintainer's beets library.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass
from functools import cached_property, partial
from itertools import groupby, starmap, zip_longest
from operator import itemgetter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterator, List, NamedTuple, Tuple

import pytest
from filelock import FileLock
from git import Repo
from rich import box
from rich.console import Group
from rich.markup import escape
from rich_tables.utils import (
    NewTable,
    border_panel,
    list_table,
    make_console,
    make_difftext,
    new_table,
    simple_panel,
    wrap,
)
from typing_extensions import TypeAlias, TypedDict

from beetsplug.bandcamp import BandcampPlugin
from beetsplug.bandcamp.metaguru import Metaguru

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.fixtures import FixtureRequest
    from beets.autotag.hooks import AttrDict
    from rich.panel import Panel

pytestmark = pytest.mark.lib

JSONDict = Dict[str, Any]

LIB_TESTS_DIR = Path("lib_tests")
RESULTS_DIR = LIB_TESTS_DIR / "results"
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
    "original_artist",
    "original_name",
    "artists",
    "artists_credit",
    "artists_ids",
    "artists_sort",
}
DO_NOT_COMPARE = {"album_id", "media", "mediums", "disctitle"}
TRACK_FIELDS = ["track_alt", "artist", "title"]

FIRST_ITEM = itemgetter(0)

console = make_console(stderr=True, record=True, highlighter=None)


def get_diff(*args) -> str:
    return make_difftext(*map(escape, args))


class FieldDiff(NamedTuple):
    field: str
    old: Any
    new: Any

    def __str__(self) -> str:
        if not isinstance(self.old, (list, tuple)):
            return get_diff(str(self.old), str(self.new))
        return " | ".join(
            get_diff(a or "", b or "") for a, b in zip_longest(self.old, self.new)
        )

    @property
    def diff(self) -> str:
        return str(get_diff(str(self.old), str(self.new)))

    def expand(self) -> Iterator[FieldDiff]:
        if self.field == "tracks":
            for old_track, new_track in zip_longest(self.old, self.new, fillvalue=[]):  # type: ignore[var-annotated]  # noqa: E501
                yield FieldDiff("album_track", old_track, new_track)
        elif self.field == "album_track":
            for field, (old, new) in zip_longest(
                TRACK_FIELDS, zip_longest(self.old, self.new, fillvalue="")
            ):
                yield FieldDiff(field, old, new)
        else:
            yield FieldDiff(self.field, self.old or "", self.new or "")


class FieldDiffDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, object_pairs_hook=self.object_pairs_hook, **kwargs)

    def object_pairs_hook(self, pairs):
        return {
            k: (
                [(u, FieldDiff(*item)) for u, item in v]
                if k in {"failed", "fixed"}
                else v
            )
            for k, v in pairs
        }


@dataclass
class Field:
    field: str
    old: Any
    new: Any
    cached: Any

    @classmethod
    def make(cls, field: str, old: Any, new: Any, *args) -> Field:
        if field == "albumtypes":
            if isinstance(old, list):
                old = "; ".join(old)
            if isinstance(new, list):
                new = "; ".join(new)
        return cls(field, old, new, *args)

    @cached_property
    def changed(self) -> bool:
        return bool(self.new != self.old)

    @cached_property
    def diff(self) -> FieldDiff:
        return FieldDiff(self.field, self.old, self.new)

    @cached_property
    def fixed(self) -> bool:
        return not self.changed and self.cached is not None

    @cached_property
    def fixed_diff(self) -> FieldDiff:
        return FieldDiff(self.field, self.cached, self.new)

    @cached_property
    def failed(self) -> bool:
        return self.changed


FieldChanges: TypeAlias = "list[tuple[str, FieldDiff]]"
AlbumFieldChanges: TypeAlias = "list[FieldDiff]"  # (FieldDiff)
FieldOutcome: TypeAlias = "tuple[str, FieldDiff]"  # (url, FieldDiff)
Results: TypeAlias = "list[FieldOutcome]"


class Summary(TypedDict):
    worker_count: int
    failed: Results
    fixed: Results


@pytest.fixture(scope="session", autouse=True)
def _ensure_results_dir():
    RESULTS_DIR.mkdir(exist_ok=True)


@pytest.fixture(scope="session")
def fixed() -> Results:
    return []


@pytest.fixture(scope="session")
def failed() -> Results:
    return []


@pytest.fixture(scope="session")
def summary_file(tmp_path_factory, worker_id) -> Path:
    root_tmp_dir = tmp_path_factory.getbasetemp()
    if worker_id != "master":
        root_tmp_dir = root_tmp_dir.parent

    return Path(root_tmp_dir / "test_summary.json")


@pytest.fixture(scope="session", autouse=True)
def _write_results(summary_file, failed: Results, fixed: Results) -> Iterator[None]:
    yield

    lock_file = f"{summary_file}.lock"
    with FileLock(lock_file):
        summary: Summary
        if summary_file.is_file():
            summary = json.loads(summary_file.read_text())
        else:
            summary = {"worker_count": 0, "failed": [], "fixed": []}

        summary["failed"].extend(failed)
        summary["fixed"].extend(fixed)
        summary["worker_count"] += 1

        summary_file.write_text(json.dumps(summary, indent=2))


@pytest.fixture(scope="session")
def include_fields(pytestconfig: Config) -> set[str]:
    include_fields: set[str] = set()
    if (fields := pytestconfig.getoption("fields")) != "*":
        include_fields |= set(fields.split(","))
        if include_fields & set(TRACK_FIELDS):
            include_fields.add("album_track")

    return include_fields


@pytest.fixture(scope="session", autouse=True)
def _report(
    pytestconfig: Config, include_fields: set[str], summary_file
) -> Iterator[None]:
    yield

    if not summary_file.is_file():
        return

    lock_file = f"{summary_file}.lock"
    with FileLock(lock_file):
        summary: Summary = json.loads(summary_file.read_text(), cls=FieldDiffDecoder)

        if summary["worker_count"] == int(
            os.environ.get("PYTEST_XDIST_WORKER_COUNT", 1)
        ):
            summary_file.unlink()
        else:
            return

        sections = [("Failed", summary["failed"], "red")]
        with suppress(TypeError):
            if Repo(pytestconfig.rootpath).active_branch.name == "dev":
                sections.append(("Fixed", summary["fixed"], "green"))

        columns = []
        for name, all_changes, color in sections:
            album_panels = []
            if include_fields:
                changes = [(u, d) for u, d in all_changes if d.field in include_fields]
            else:
                changes = all_changes
            changes.sort(key=FIRST_ITEM)
            for url, diffs in groupby(changes, FIRST_ITEM):
                album_panels.append(
                    border_panel(
                        new_table(
                            rows=[
                                (f"[b dim]{diff.field}[/]", str(diff))
                                for _, diff in diffs
                            ]
                        ),
                        title=f"[dim]{url}[/]",
                        title_align="right",
                        subtitle_align="right",
                        border_style="dim",
                        box=box.DOUBLE,
                    )
                )

            if album_panels:
                columns.append(
                    border_panel(
                        list_table(album_panels),
                        title=name,
                        border_style=f"bold {color}",
                    )
                )

        if field_changes := get_field_changes(summary["failed"], include_fields):
            columns.append(field_changes)

        console.print("\n")
        if columns:
            headers = [""] * len(columns)
            console.print(new_table(*headers, vertical="bottom", rows=[columns]))


def get_field_changes(results: Results, include_fields: set[str]) -> Panel:
    diffs = [d for _, diff in results for d in diff.expand() if d.old != d.new]
    if include_fields:
        diffs = [d for d in diffs if d.field in include_fields]
    diffs.sort(key=lambda d: (d.field, str(d.new)))

    cols = []
    for field, field_diffs in groupby(diffs, lambda d: d.field):
        tab = new_table()
        changes = [(str(d.new or ""), str(d.old or "")) for d in field_diffs]
        for new, old in (
            (n, [o for _, o in c]) for n, c in groupby(changes, FIRST_ITEM)
        ):
            tab.add_row(
                " | ".join(starmap(_fmt_old, Counter(map(escape, old)).items())),
                wrap(escape(new), "b green"),
            )
        cols.append(simple_panel(tab, title=f"{len(changes)} [magenta]{field}[/]"))

    return border_panel(Group(*cols), title="Field changes")


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
def config() -> JSONDict:
    return dict(BandcampPlugin().config.flatten())


@pytest.fixture(params=sorted(JSONS_DIR.glob("*.json")), ids=str)
def test_filepath(request: FixtureRequest) -> Path:
    path: Path = request.param

    return path


@pytest.fixture
def target_filepath(target_dir: Path, test_filepath: Path) -> Path:
    return target_dir / test_filepath.name


def _fmt_old(s: str, times: int) -> str:
    return (f"{times} x " if times > 1 else "") + wrap(s, "b s red")


@pytest.fixture
def guru(config: JSONDict, test_filepath: Path) -> Metaguru:
    test_data = test_filepath.read_text()

    return Metaguru.from_html(test_data.replace("\n", ""), config)


@pytest.fixture
def original_name(guru: Metaguru) -> str:
    return str(guru.meta["name"])


@pytest.fixture
def original_artist(guru: Metaguru) -> str:
    return str(guru.meta["byArtist"]["name"])


@pytest.fixture
def base_filepath(base_dir: Path, test_filepath: Path) -> Path:
    return base_dir / test_filepath.name


@pytest.fixture
def base(base_filepath: Path) -> JSONDict:
    try:
        data: JSONDict = json.loads(base_filepath.read_text())
    except FileNotFoundError:
        if base_filepath.is_symlink() and not base_filepath.exists():
            base_filepath.unlink()
        return {}

    return data


@pytest.fixture
def old(base: JSONDict) -> JSONDict:
    return {k: v for k, v in base.items() if k not in IGNORE_FIELDS}


def write_results(data: JSONDict, name: str) -> Path:
    contents = json.dumps(data, indent=2, sort_keys=True).encode()
    _id = hashlib.md5(contents).hexdigest()
    results_filepath = RESULTS_DIR / f"{name}-{_id}.json"
    if not results_filepath.exists():
        results_filepath.write_bytes(contents)

    return results_filepath


@pytest.fixture
def new(
    base: JSONDict,
    base_filepath: Path,
    guru: Metaguru,
    original_name: str,
    original_artist: str,
    target_filepath: Path,
) -> JSONDict:
    _new: AttrDict
    if "_track_" in target_filepath.name:
        _new = guru.singleton
    else:
        _new = next((a for a in guru.albums if a.media == "Vinyl"), guru.albums[0])
        _new.album = " / ".join(dict.fromkeys(x.album for x in guru.albums))

    _new.catalognum = " / ".join(
        sorted({x.catalognum for x in guru.albums if x.catalognum})
    )
    _new.original_name = original_name
    _new.original_artist = original_artist
    new = dict(_new)

    results_filepath = base_filepath.resolve()
    if base and results_filepath.parent != RESULTS_DIR:
        results_filepath = write_results(base, base_filepath.stem)
        base_filepath.unlink()
        symlink_path = os.path.relpath(results_filepath, base_filepath.parent)
        base_filepath.symlink_to(symlink_path)

    if new == base:
        results_filepath = base_filepath
    else:
        results_filepath = write_results(new, target_filepath.stem)

    if (target_filepath.is_symlink() and not target_filepath.exists()) or (
        target_filepath.exists()
        and (
            target_filepath != results_filepath
            or not target_filepath.samefile(results_filepath)
        )
    ):
        target_filepath.unlink()

    if not target_filepath.exists():
        symlink_path = os.path.relpath(results_filepath, target_filepath.parent)
        target_filepath.symlink_to(symlink_path)

    return {k: v for k, v in new.items() if k not in IGNORE_FIELDS}


@pytest.fixture
def desc(old: JSONDict, new: JSONDict, guru: Metaguru) -> str:
    get_values = itemgetter(*TRACK_FIELDS)

    def get_tracks(data: JSONDict) -> List[Tuple[str, ...]]:
        return [tuple(get_values(t)) for t in data.get("tracks", [])]

    if "/album/" in new["data_url"]:
        if "artist" in old and "tracks" in old:
            old.update(albumartist=old.pop("artist", ""), tracks=get_tracks(old))
        new.update(albumartist=new.pop("artist", ""), tracks=get_tracks(new))
        artist, title = new.get("albumartist", ""), new.get("album", "")
    else:
        artist, title = new["artist"], new["title"]

    return (
        f"{get_diff(guru.original_albumartist, artist)} - "
        f"{get_diff(guru.original_album, title)}"
    )


@pytest.fixture
def entity_id(new: JSONDict) -> str:
    return str(new["album_id"] if "/album/" in new["data_url"] else new["track_id"])


@pytest.fixture
def check_field(
    failed: Results,
    fixed: Results,
    entity_id: str,
):
    def do(table: NewTable, field: Field) -> None:
        if field.fixed and field.new != field.cached:
            fixed.extend((entity_id, d) for d in field.fixed_diff.expand())
        else:
            diffs = list(field.diff.expand())
            table.add_rows([(d.field, str(d)) for d in diffs])
            if field.failed:
                failed.extend((entity_id, d) for d in diffs)

    return do


@pytest.fixture
def difference(
    check_field: Callable[[NewTable, Field], None],
    old: JSONDict,
    new: JSONDict,
    cache: pytest.Cache,
    desc: str,
    entity_id: str,
) -> bool:
    if not old:  # new test case, no need to report diffs
        return False

    table = new_table(padding=0, expand=False, collapse_padding=True)
    compare_fields = (new.keys() | old.keys()) - DO_NOT_COMPARE
    compare_field = partial(check_field, table)

    fail = False
    for fname in sorted(compare_fields):
        old_val, new_val = old.get(fname), new.get(fname)
        if old_val is None and new_val is None:
            continue

        cache_key = f"{entity_id}_{fname}"
        field = Field.make(fname, old_val, new_val, cache.get(cache_key, None))
        if not field.changed and not field.fixed:
            continue

        compare_field(field)
        if field.changed:
            backup = field.new or ""
            fail = True
        else:
            backup = None

        cache.set(cache_key, backup)

    if fail:
        console.print("\n")
        console.print(
            border_panel(
                table,
                title=desc,
                expand=True,
                subtitle=wrap(f"{entity_id} - {new['media']}", "dim"),
            )
        )

    return fail


def test_file(difference: bool) -> None:
    if difference:
        pytest.fail(pytrace=False)
