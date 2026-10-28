"""Load a StatsBomb Open Data checkout into the raw schema.

Each file is handled in its own transaction:

  * same size and mtime as in raw._ingest_files -> skip without reading the file
  * otherwise hash it; same SHA-256 -> skip (only the ledger's size/mtime are refreshed)
  * changed hash -> delete the file's old rows, COPY the new ones, update the ledger
  * new file     -> COPY its rows, add it to the ledger

`verify=True` (`--verify`) drops the size/mtime shortcut and hashes every file.

so a crash or a corrupt file never leaves half a file in raw, and files committed before
the failure stay loaded. The run itself is recorded in raw._ingest_runs.

source_path is relative to the sources directory (e.g. statsbomb/data/events/3869685.json),
so moving the data directory (SCOUTBASE_DATA_DIR) does not change any key. The checkout
directory's name is part of the key, so two checkouts never overwrite each other.
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
    files_hashed: int = 0
    rows_loaded: int = 0
    error: str | None = None


def discover(root: Path) -> list[tuple[str, Path]]:
    return [(entity, path) for entity, pattern in ENTITY_GLOBS for path in sorted(root.glob(pattern))]


def _load_file(
    conn: psycopg.Connection, run: RunResult, entity: str, source_path: str, path: Path, verify: bool
) -> None:
    table = sql.Identifier("raw", f"{PROVIDER}_{entity}")

    with conn.transaction():
        # FOR UPDATE: a concurrent run touching the same file waits instead of double-loading.
        previous = conn.execute(
            "SELECT sha256, file_size, file_mtime_ns FROM raw._ingest_files "
            "WHERE provider = %s AND source_path = %s FOR UPDATE",
            (PROVIDER, source_path),
        ).fetchone()
        # stat before reading: if the file changes while it is read, the stat on record is the
        # older one, so the next run sees a difference and hashes the file again.
        stat = path.stat()
        if previous and not verify and previous[1:] == (stat.st_size, stat.st_mtime_ns):
            run.files_skipped += 1
            return

        content = path.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()
        run.files_hashed += 1
        if previous and previous[0] == sha256:
            # Touched, not changed (e.g. copied or re-checked-out): keep the rows and their
            # run_id, and record the new size/mtime so the next run can skip without hashing.
            conn.execute(
                "UPDATE raw._ingest_files SET file_size = %s, file_mtime_ns = %s "
                "WHERE provider = %s AND source_path = %s",
                (stat.st_size, stat.st_mtime_ns, PROVIDER, source_path),
            )
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
            INSERT INTO raw._ingest_files
                   (provider, entity, source_path, sha256, row_count, run_id, file_size, file_mtime_ns)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider, source_path) DO UPDATE
               SET entity = EXCLUDED.entity, sha256 = EXCLUDED.sha256, row_count = EXCLUDED.row_count,
                   run_id = EXCLUDED.run_id, loaded_at = now(),
                   file_size = EXCLUDED.file_size, file_mtime_ns = EXCLUDED.file_mtime_ns
            """,
            (PROVIDER, entity, source_path, sha256, len(records), run.run_id,
             stat.st_size, stat.st_mtime_ns),
        )

    run.rows_loaded += len(records)
    if previous:
        run.files_replaced += 1
    else:
        run.files_loaded += 1


def ingest(
    conn: psycopg.Connection, root: Path, source_version: str | None = None, verify: bool = False
) -> RunResult:
    """Load every StatsBomb file under root. Never raises for a bad file: see the run's status."""
    if not conn.autocommit:
        raise ValueError("ingest needs an autocommit connection; it opens one transaction per file")

    # Committed immediately, so the run is visible (as 'running') while it loads.
    (run_id,) = conn.execute(
        "INSERT INTO raw._ingest_runs (source, source_version, verify) VALUES (%s, %s, %s) "
        "RETURNING run_id",
        (PROVIDER, source_version, verify),
    ).fetchone()
    run = RunResult(run_id=run_id)

    try:
        for entity, path in discover(root):
            run.files_seen += 1
            source_path = f"{root.name}/{path.relative_to(root).as_posix()}"
            try:
                _load_file(conn, run, entity, source_path, path, verify)
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
               files_hashed = %s, rows_loaded = %s
         WHERE run_id = %s
        """,
        (run.status, run.error, run.files_seen, run.files_loaded, run.files_skipped,
         run.files_replaced, run.files_hashed, run.rows_loaded, run.run_id),
    )
    return run
