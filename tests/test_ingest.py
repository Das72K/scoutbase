"""StatsBomb ingest tests, run on the small files in tests/fixtures (never the network).

Each test copies the fixtures into a uniquely named directory. The directory name is the
first segment of source_path, so tests never see each other's rows and each one can remove
its own by prefix afterwards.
"""

import json
import shutil
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pipeline.ingest import statsbomb
from pipeline.ingest.statsbomb import RunResult

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "statsbomb"
ENTITIES = ("competitions", "matches", "lineups", "events")
FIXTURE_ROWS = {"competitions": 1, "matches": 2, "lineups": 4, "events": 8}
FIXTURE_FILES = 6


@pytest.fixture
def source(tmp_path, owner) -> Iterator[Path]:
    root = tmp_path / f"sbtest_{uuid.uuid4().hex[:8]}"
    shutil.copytree(FIXTURES, root)
    yield root
    prefix = f"{root.name}/%"
    for entity in ENTITIES:
        owner.execute(f"DELETE FROM raw.statsbomb_{entity} WHERE source_path LIKE %s", (prefix,))
    owner.execute("DELETE FROM raw._ingest_files WHERE source_path LIKE %s", (prefix,))
    owner.execute("DELETE FROM raw._ingest_runs WHERE source_version = %s", (root.name,))


@pytest.fixture
def ingest(login_as, source) -> Callable[[], RunResult]:
    """Run the ingest on the fixture copy, as the pipeline login user (like the CLI)."""
    conn = login_as("scoutbase_pipeline")
    # source_version = the directory name, so the cleanup finds every run the test made.
    return lambda: statsbomb.ingest(conn, source, source_version=source.name)


def counts(owner, root: Path) -> dict[str, int]:
    return {
        entity: owner.execute(
            f"SELECT count(*) FROM raw.statsbomb_{entity} WHERE source_path LIKE %s", (f"{root.name}/%",)
        ).fetchone()[0]
        for entity in ENTITIES
    }


def rows_of(owner, root: Path, rel: str) -> list[tuple]:
    return owner.execute(
        "SELECT record_index, payload, run_id, loaded_at FROM raw.statsbomb_events "
        "WHERE source_path = %s ORDER BY record_index",
        (f"{root.name}/{rel}",),
    ).fetchall()


def logged_run(owner, run_id: int) -> tuple:
    return owner.execute(
        "SELECT status, files_seen, files_loaded, files_skipped, files_replaced, rows_loaded, "
        "error, finished_at IS NOT NULL FROM raw._ingest_runs WHERE run_id = %s",
        (run_id,),
    ).fetchone()


def test_second_run_skips_every_file(owner, source, ingest):
    first = ingest()
    assert first.status == "succeeded"
    assert first.files_loaded == FIXTURE_FILES
    assert counts(owner, source) == FIXTURE_ROWS

    second = ingest()
    assert counts(owner, source) == FIXTURE_ROWS
    assert logged_run(owner, second.run_id) == (
        "succeeded", FIXTURE_FILES, 0, FIXTURE_FILES, 0, 0, None, True
    )


def test_changed_file_is_replaced_not_duplicated(owner, source, ingest):
    first = ingest()
    untouched = rows_of(owner, source, "data/events/1001.json")

    changed = source / "data" / "events" / "1002.json"
    events = json.loads(changed.read_text(encoding="utf-8"))
    events.append({"id": "e1002-4", "index": 4, "period": 1, "minute": 0, "second": 5,
                   "type": {"id": 30, "name": "Pass"}})
    changed.write_text(json.dumps(events), encoding="utf-8")

    second = ingest()
    assert logged_run(owner, second.run_id) == (
        "succeeded", FIXTURE_FILES, 0, FIXTURE_FILES - 1, 1, 4, None, True
    )
    replaced = rows_of(owner, source, "data/events/1002.json")
    assert [r[0] for r in replaced] == [0, 1, 2, 3]
    assert {r[2] for r in replaced} == {second.run_id}
    assert counts(owner, source) == {**FIXTURE_ROWS, "events": FIXTURE_ROWS["events"] + 1}
    # The other file keeps its rows from the first run, down to the load timestamp.
    assert rows_of(owner, source, "data/events/1001.json") == untouched
    assert untouched[0][2] == first.run_id

    ledger = owner.execute(
        "SELECT row_count, run_id FROM raw._ingest_files WHERE source_path = %s",
        (f"{source.name}/data/events/1002.json",),
    ).fetchone()
    assert ledger == (4, second.run_id)


def test_corrupt_file_fails_run_and_keeps_committed_files(owner, source, ingest):
    ingest()
    before = counts(owner, source)
    (source / "data" / "events" / "1003.json").write_text('[{"id": "e1003-1", "index": ', encoding="utf-8")

    run = ingest()
    assert run.status == "failed"
    status, *_, error, finished = logged_run(owner, run.run_id)
    assert (status, finished) == ("failed", True)
    assert "events/1003.json" in error and "JSONDecodeError" in error

    assert rows_of(owner, source, "data/events/1003.json") == []
    assert owner.execute(
        "SELECT count(*) FROM raw._ingest_files WHERE source_path = %s",
        (f"{source.name}/data/events/1003.json",),
    ).fetchone()[0] == 0
    assert counts(owner, source) == before


def test_corrupt_new_version_keeps_previous_version(owner, source, ingest):
    ingest()
    previous = rows_of(owner, source, "data/events/1001.json")
    (source / "data" / "events" / "1001.json").write_text("[{", encoding="utf-8")

    assert ingest().status == "failed"
    # The DELETE of the old rows is rolled back together with the failed load.
    assert rows_of(owner, source, "data/events/1001.json") == previous


def test_record_index_preserves_file_order(owner, source, ingest):
    ingest()
    in_file = [e["id"] for e in json.loads((source / "data/events/1001.json").read_text(encoding="utf-8"))]
    loaded = rows_of(owner, source, "data/events/1001.json")
    assert [r[0] for r in loaded] == list(range(len(in_file)))
    assert [r[1]["id"] for r in loaded] == in_file
