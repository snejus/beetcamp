"""Tests which read a bunch of Bandcamp JSONs and compare results with previous runs.

Currently they are only executed locally using around ~5000 release JSON files.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from functools import cached_property
from itertools import groupby, zip_longest
from operator import itemgetter
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import pytest
from filelock import FileLock
from rich import box
from rich.console import Group
from rich.markup import escape
from rich_tables.diff import make_difftext
from rich_tables.utils import (
    NewTable,
    border_panel,
    list_table,
    make_console,
    new_table,
    simple_panel,
    wrap,
)
from typing_extensions import TypedDict

from beetsplug.bandcamp import BandcampPlugin
from beetsplug.bandcamp.metaguru import Metaguru

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest.config import Config
    from _pytest.fixtures import FixtureRequest
    from beets.autotag.hooks import AttrDict
    from rich.panel import Panel

pytestmark = pytest.mark.lib

JSONDict = dict[str, Any]

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
    "artists_credit",
    "artists_ids",
    "artists_sort",
}
DO_NOT_COMPARE = {"album_id", "media", "mediums", "disctitle"}
TRACK_FIELDS = ["track_alt", "artist", "title"]

FIRST_ITEM = itemgetter(0)

console = make_console(stderr=True, record=True, highlighter=None)


def get_diff(*args: str) -> str:
    return make_difftext(*map(escape, args))


class FieldDiff(NamedTuple):
    """Represents a difference between field values.

    Handles both simple values and collections, providing string representation
    of differences with appropriate formatting.
    """

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
            for old_track, new_track in zip_longest(self.old, self.new, fillvalue=[]):  # type: ignore[var-annotated]
                yield FieldDiff("album_track", old_track, new_track)
        elif self.field == "album_track":
            for field, (old, new) in zip_longest(
                TRACK_FIELDS, zip_longest(self.old, self.new, fillvalue="")
            ):
                yield FieldDiff(field, old, new)
        else:
            yield FieldDiff(self.field, self.old or "", self.new or "")


class FieldDiffDecoder(json.JSONDecoder):
    """Custom JSON decoder that converts serialized field diff data back to FieldDiff objects.

    Used when loading saved test results to reconstruct diff information.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, object_pairs_hook=self.object_pairs_hook, **kwargs)

    def object_pairs_hook(self, pairs: list[tuple[str, Any]]) -> dict[str, Any]:
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
    """Represents a field with its old, new and cached values.

    Tracks changes between test runs and determines if a field has been fixed
    or has newly failed.
    """

    field: str
    old: Any
    new: Any
    cached: Any

    @classmethod
    def make(cls, field: str, old: Any, new: Any, *args: Any) -> Field:
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


FieldChanges = list[tuple[str, FieldDiff]]
AlbumFieldChanges = list[FieldDiff]  # (FieldDiff)
FieldOutcome = tuple[str, FieldDiff]  # (url, FieldDiff)
Results = list[FieldOutcome]


class Summary(TypedDict):
    worker_count: int
    failed: Results
    fixed: Results


@pytest.fixture(scope="session")
def base_commit(pytestconfig: Config) -> str:
    base_commit: str = pytestconfig.getoption("base")
    return base_commit


@pytest.fixture(scope="session")
def retesting(base_commit: str, pytestconfig: Config) -> bool:
    return bool(base_commit == pytestconfig.cache.get("previous_base", ""))


@pytest.fixture(scope="session", autouse=True)
def cache_base_commit(pytestconfig: Config, base_commit: str):
    yield
    pytestconfig.cache.set("previous_base", base_commit)


@pytest.fixture(scope="session", autouse=True)
def _ensure_results_dir() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)


@pytest.fixture(scope="session")
def fixed() -> Results:
    return []


@pytest.fixture(scope="session")
def failed() -> Results:
    return []


@pytest.fixture(scope="session")
def summary_file(tmp_path_factory: pytest.TempPathFactory, worker_id: str) -> Path:
    root_tmp_dir = tmp_path_factory.getbasetemp()
    if worker_id != "master":
        root_tmp_dir = root_tmp_dir.parent

    return Path(root_tmp_dir / "test_summary.json")


@pytest.fixture(scope="session", autouse=True)
def _write_results(
    summary_file: Path, failed: Results, fixed: Results
) -> Iterator[None]:
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
    include_fields: set[str], summary_file: Path, retesting: bool
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
        if retesting and summary["fixed"]:
            sections.append(("Fixed", summary["fixed"], "green"))

        columns = []
        for name, all_changes, color in sections:
            if include_fields:
                changes = [(u, d) for u, d in all_changes if d.field in include_fields]
            else:
                changes = all_changes
            changes.sort(key=FIRST_ITEM)
            if album_panels := [
                border_panel(
                    new_table(
                        rows=[
                            (f"[b dim]{diff.field}[/]", str(diff)) for _, diff in diffs
                        ]
                    ),
                    title=f"[dim]{url}[/]",
                    title_align="right",
                    subtitle_align="right",
                    border_style="dim",
                    box=box.DOUBLE,
                )
                for url, diffs in groupby(changes, FIRST_ITEM)
            ]:
                columns.append(
                    border_panel(
                        list_table(album_panels),
                        title=name,
                        border_style=f"bold {color}",
                    )
                )

        if failed := summary["failed"]:
            columns.append(get_field_changes(failed, include_fields))

        console.print("\n")
        if columns:
            headers = [""] * len(columns)
            console.print(new_table(*headers, vertical="bottom", rows=[columns]))


def get_field_changes(results: Results, include_fields: set[str]) -> Panel:
    """Generate a report panel showing field changes across all test results.

    Organizes changes by field name and groups identical changes with counts.
    """
    diffs = [d for _, diff in results for d in diff.expand() if d.old != d.new]
    if include_fields:
        diffs = [d for d in diffs if d.field in include_fields]
    diffs.sort(key=lambda x: tuple(map(str, x)))

    cols = []
    for field, field_diffs in groupby(diffs, lambda d: d.field):
        changes = [d.diff for d in field_diffs]

        change_counts = Counter(changes).most_common()
        tab = new_table()
        for change, count in change_counts:
            tab.add_row((f"[b cyan]({count})[/] " if count > 1 else "") + str(change))
        cols.append(simple_panel(tab, title=f"{len(changes)} [magenta]{field}[/]"))

    return border_panel(Group(*cols), title="Field changes")


@pytest.fixture(scope="module")
def base_dir(base_commit: str) -> Path:
    return LIB_TESTS_DIR / base_commit


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


def prepare_release(release: JSONDict) -> JSONDict:
    """Normalize release data for consistent comparison.

    Handles album-specific transformations and extracts track information
    in a consistent format.
    """
    get_values = itemgetter(*TRACK_FIELDS)

    def get_tracks(data: JSONDict) -> list[tuple[str, ...]]:
        return [tuple(get_values(t)) for t in data.get("tracks", [])]

    if "/album/" in release.get("data_url", ""):
        release.update(
            albumartist=release.pop("artist", ""), tracks=get_tracks(release)
        )

    return release


@pytest.fixture
def old(base: JSONDict) -> JSONDict:
    return prepare_release({k: v for k, v in base.items() if k not in IGNORE_FIELDS})


def write_results(data: JSONDict, name: str) -> Path:
    """Write test results to a file with content-based naming.

    Creates a deterministic filename based on content hash to avoid
    duplicating identical results.
    """
    contents = json.dumps(data, indent=2, sort_keys=True).encode()
    id_ = hashlib.md5(contents).hexdigest()
    name = name[: 255 - len(id_) - 6]
    results_filepath = RESULTS_DIR / f"{name}-{id_}.json"
    if not results_filepath.exists():
        results_filepath.write_bytes(contents)

    return results_filepath


@pytest.fixture
def new(guru: Metaguru, original_name: str, original_artist: str) -> JSONDict:
    new_: AttrDict[Any]
    if "/track/" in guru.meta["@id"]:
        new_ = guru.singleton
    else:
        new_ = next((a for a in guru.albums if a.media == "Vinyl"), guru.albums[0])
        new_.album = " / ".join(dict.fromkeys(x["album"] for x in guru.albums))

    return {
        **new_,
        "original_name": original_name,
        "original_artist": original_artist,
        "catalognum": " / ".join(
            sorted({x.catalognum for x in guru.albums if x.catalognum})
        ),
    }


@pytest.fixture
def result(
    base: JSONDict, base_filepath: Path, target_filepath: Path, new: JSONDict
) -> JSONDict:
    results_filepath = base_filepath.resolve()
    if base and results_filepath.parent != RESULTS_DIR:
        results_filepath = write_results(base, base_filepath.stem)
        base_filepath.unlink()
        symlink_path = os.path.relpath(results_filepath, base_filepath.parent)
        base_filepath.symlink_to(symlink_path)

    if new != base:
        results_filepath = write_results(new, target_filepath.stem)

    if (target_filepath.is_symlink() and not target_filepath.exists()) or (
        target_filepath.exists()
        and (
            target_filepath != results_filepath
            or not target_filepath.samefile(results_filepath)
        )
    ):
        target_filepath.unlink()

    for path in (p for p in (base_filepath, target_filepath) if not p.exists()):
        path.symlink_to(os.path.relpath(results_filepath, path.parent))

    return prepare_release({k: v for k, v in new.items() if k not in IGNORE_FIELDS})


@pytest.fixture
def desc(result: JSONDict, guru: Metaguru) -> str:
    if "/album/" in result["data_url"]:
        artist, name = result["albumartist"], result["album"]
    else:
        artist, name = result["artist"], result["title"]

    return (
        f"{get_diff(guru.original_albumartist, artist)} - "
        f"{get_diff(guru.original_album, name)}"
    )


@pytest.fixture
def entity_id(result: JSONDict) -> str:
    return str(
        result["album_id"] if "/album/" in result["data_url"] else result["track_id"]
    )


@dataclass
class AlbumChange:
    entity_id: str
    old: JSONDict
    new: JSONDict
    cache: pytest.Cache

    @cached_property
    def fields(self) -> list[Field]:
        compare_fields = (self.old.keys() | self.new.keys()) - DO_NOT_COMPARE
        return list(map(self.get_field, sorted(compare_fields)))

    def get_field(self, name: str) -> Field:
        return Field.make(
            name,
            self.old.get(name),
            self.new.get(name),
            self.cache.get(f"{self.entity_id}_{name}", None),
        )

    # @snoop
    def compare_field(
        self, field: Field, table: NewTable, failed: Results, fixed: Results
    ) -> None:
        if field.fixed:
            fixed.extend((self.entity_id, d) for d in field.fixed_diff.expand())
            self.cache.set(f"{self.entity_id}_{field.field}", None)
        elif field.failed:
            self.cache.set(f"{self.entity_id}_{field.field}", field.old)
            diffs = list(field.diff.expand())
            table.add_rows([(d.field, str(d)) for d in diffs])
            if field.failed:
                failed.extend((self.entity_id, d) for d in diffs)

    def compare(self, *args) -> None:
        if any(f.changed or f.fixed for f in self.fields):
            for f in self.fields:
                self.compare_field(f, *args)


@pytest.fixture
def diff_table(
    failed: Results,
    fixed: Results,
    old: JSONDict,
    result: JSONDict,
    cache: pytest.Cache,
    entity_id: str,
) -> NewTable:
    table = new_table(padding=0, expand=False, collapse_padding=True)
    if not old:  # new test case, no need to report diffs
        return table

    album_change = AlbumChange(entity_id, old, result, cache)
    album_change.compare(table, failed, fixed)

    return table


def test_file(
    diff_table: NewTable, desc: str, entity_id: str, result: JSONDict
) -> None:
    if diff_table.row_count:
        console.print("\n")
        console.print(
            border_panel(
                diff_table,
                title=desc,
                expand=True,
                subtitle=wrap(f"{entity_id} - {result['media']}", "dim"),
            )
        )
        pytest.fail(pytrace=False)
