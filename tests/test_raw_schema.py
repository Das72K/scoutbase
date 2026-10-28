"""Raw layer tests (0004): ownership and grants of the ingest ledger and raw StatsBomb tables.

As in test_foundation, every refusal is paired with the allowed action on the same table, so a
test cannot pass just because the table is missing.
"""

import pytest
from psycopg.errors import InsufficientPrivilege

RAW_TABLES = [
    "raw._ingest_runs",
    "raw._ingest_files",
    "raw.statsbomb_competitions",
    "raw.statsbomb_matches",
    "raw.statsbomb_lineups",
    "raw.statsbomb_events",
]


def test_raw_tables_owned_by_pipeline(owner):
    rows = owner.execute(
        "SELECT schemaname || '.' || tablename, tableowner FROM pg_tables WHERE schemaname = 'raw'"
    ).fetchall()
    owners = dict(rows)
    assert {t: owners.get(t) for t in RAW_TABLES} == {t: "scoutbase_pipeline" for t in RAW_TABLES}


def test_pipeline_can_load_and_replace_raw_rows(login_as):
    pipeline = login_as("scoutbase_pipeline")
    # force_rollback: prove the privileges without leaving a fake run behind.
    with pipeline.transaction(force_rollback=True):
        (run_id,) = pipeline.execute(
            "INSERT INTO raw._ingest_runs (source) VALUES ('test') RETURNING run_id"
        ).fetchone()
        pipeline.execute(
            "INSERT INTO raw.statsbomb_events (source_path, record_index, payload, run_id) "
            "VALUES ('test/e.json', 0, '{}', %s)",
            (run_id,),
        )
        pipeline.execute(
            "INSERT INTO raw._ingest_files (provider, entity, source_path, sha256, row_count, run_id) "
            "VALUES ('test', 'events', 'test/e.json', repeat('0', 64), 1, %s)",
            (run_id,),
        )
        pipeline.execute("DELETE FROM raw.statsbomb_events WHERE source_path = 'test/e.json'")
        pipeline.execute("UPDATE raw._ingest_files SET row_count = 0 WHERE source_path = 'test/e.json'")
        pipeline.execute(
            "UPDATE raw._ingest_runs SET status = 'succeeded', finished_at = now() WHERE run_id = %s",
            (run_id,),
        )


@pytest.mark.parametrize("group", ["scoutbase_app", "scoutbase_readonly"])
@pytest.mark.parametrize("table", RAW_TABLES)
def test_app_and_readonly_cannot_read_raw(login_as, group, table):
    login_as("scoutbase_pipeline").execute(f"SELECT count(*) FROM {table}")
    with pytest.raises(InsufficientPrivilege):
        login_as(group).execute(f"SELECT count(*) FROM {table}")


@pytest.mark.parametrize("group", ["scoutbase_app", "scoutbase_readonly"])
def test_app_and_readonly_cannot_write_raw(login_as, group):
    with pytest.raises(InsufficientPrivilege):
        login_as(group).execute("INSERT INTO raw._ingest_runs (source) VALUES ('sneaky')")
