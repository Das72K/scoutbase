"""Load a StatsBomb Open Data checkout into the raw schema.

Each file is handled in its own transaction:

  * same SHA-256 as in raw._ingest_files -> skip (nothing is read or written)
  * changed hash -> delete the file's old rows, COPY the new ones, update the ledger
  * new file     -> COPY its rows, add it to the ledger

so a crash or a corrupt file never leaves half a file in raw, and files committed before
the failure stay loaded. The run itself is recorded in raw._ingest_runs.

source_path is relative to data/sources/ (e.g. statsbomb/data/events/3869685.json): the
checkout directory's name is part of the key, so two checkouts never overwrite each other.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

PROVIDER = "statsbomb"

# Load order: reference data first, so a failed run leaves the most useful prefix behind.
ENTITY_GLOBS = (
    ("competitions", "data/competitions.json"),
    ("matches", "data/matches/*/*.json"),
    ("lineups", "data/lineups/*.json"),
    ("events", "data/events/*.json"),
)


@dataclass
class RunResult:
    run_id: int
    status: str = "running"
    files_seen: int = 0
    files_loaded: int = 0
    files_skipped: int = 0
    files_replaced: int = 0
    rows_loaded: int = 0
    error: str | None = None


def discover(root: Path) -> list[tuple[str, Path]]:
    return [(entity, path) for entity, pattern in ENTITY_GLOBS for path in sorted(root.glob(pattern))]


def _load_file(
    conn: psycopg.Connection, run: RunResult, entity: str, source_path: str, path: Path
) -> None:
    content = path.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    table = sql.Identifier("raw", f"{PROVIDER}_{entity}")

    with conn.transaction():
        # FOR UPDATE: a concurrent run touching the same file waits instead of double-loading.
        previous = conn.execute(
            "SELECT sha256 FROM raw._ingest_files WHERE provider = %s AND source_path = %s FOR UPDATE",
            (PROVIDER, source_path),
        ).fetchone()
        if previous and previous[0] == sha256:
            run.files_skipped += 1
            return

        records = json.loads(content)
        if not isinstance(records, list):
            raise ValueError(f"expected a top-level JSON array, got {type(records).__name__}")

        if previous:
            # The only time raw rows are removed: the provider re-published the file, and
            # keeping both versions would duplicate every record.
            conn.execute(sql.SQL("DELETE FROM {} WHERE source_path = %s").format(table), (source_path,))

        copy_sql = sql.SQL(
            "COPY {} (source_path, record_index, payload, run_id) FROM STDIN"
        ).format(table)
        with conn.cursor().copy(copy_sql) as copy:
            for index, record in enumerate(records):
                copy.write_row((source_path, index, json.dumps(record, ensure_ascii=False), run.run_id))

        conn.execute(
            """
            INSERT INTO raw._ingest_files (provider, entity, source_path, sha256, row_count, run_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider, source_path) DO UPDATE
               SET entity = EXCLUDED.entity, sha256 = EXCLUDED.sha256, row_count = EXCLUDED.row_count,
                   run_id = EXCLUDED.run_id, loaded_at = now()
            """,
            (PROVIDER, entity, source_path, sha256, len(records), run.run_id),
        )

    run.rows_loaded += len(records)
    if previous:
        run.files_replaced += 1
    else:
        run.files_loaded += 1


def ingest(conn: psycopg.Connection, root: Path, source_version: str | None = None) -> RunResult:
    """Load every StatsBomb file under root. Never raises for a bad file: see the run's status."""
    if not conn.autocommit:
        raise ValueError("ingest needs an autocommit connection; it opens one transaction per file")

    # Committed immediately, so the run is visible (as 'running') while it loads.
    (run_id,) = conn.execute(
        "INSERT INTO raw._ingest_runs (source, source_version) VALUES (%s, %s) RETURNING run_id",
        (PROVIDER, source_version),
    ).fetchone()
    run = RunResult(run_id=run_id)

    try:
        for entity, path in discover(root):
            run.files_seen += 1
            source_path = f"{root.name}/{path.relative_to(root).as_posix()}"
            try:
                _load_file(conn, run, entity, source_path, path)
            except Exception as exc:
                raise RuntimeError(f"{source_path}: {type(exc).__name__}: {exc}") from exc
        run.status = "succeeded"
    except Exception as exc:
        run.status, run.error = "failed", str(exc)

    conn.execute(
        """
        UPDATE raw._ingest_runs
           SET finished_at = clock_timestamp(), status = %s, error = %s,
               files_seen = %s, files_loaded = %s, files_skipped = %s, files_replaced = %s,
               rows_loaded = %s
         WHERE run_id = %s
        """,
        (run.status, run.error, run.files_seen, run.files_loaded, run.files_skipped,
         run.files_replaced, run.rows_loaded, run.run_id),
    )
    return run
