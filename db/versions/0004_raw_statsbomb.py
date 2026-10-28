"""Create the ingest ledger and the raw StatsBomb tables.

WHY: The raw layer keeps provider JSON exactly as delivered so every later layer can be
rebuilt from it (ADR-2). One row per element of the provider's top-level JSON array,
keyed by (source_path, record_index), so a row can always be traced back to the exact file
and position it came from, and the original order of events survives.

  * raw._ingest_runs   one row per pipeline run: what was seen, loaded, skipped, replaced.
  * raw._ingest_files  the ledger: the SHA-256 of the last loaded version of every file. It is
                       what makes re-runs incremental (same hash -> skip) and idempotent
                       (changed hash -> replace that file's rows, never append duplicates).

Ownership: the tables are owned by scoutbase_pipeline, the role the ingest runs as. It needs
DELETE to replace a changed file, and owning the tables means no separate grants to keep in
sync. Nothing is granted to scoutbase_app or scoutbase_readonly: raw is pipeline-internal and
they will read the modelled layers (core, marts) instead.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

RAW_TABLES = (
    "raw.statsbomb_competitions",
    "raw.statsbomb_matches",
    "raw.statsbomb_lineups",
    "raw.statsbomb_events",
)


def upgrade() -> None:
    # --- 1. Run log --------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE raw._ingest_runs (
            run_id          bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            started_at      timestamptz NOT NULL DEFAULT now(),
            finished_at     timestamptz,
            status          text        NOT NULL DEFAULT 'running'
                            CHECK (status IN ('running', 'succeeded', 'failed')),
            source          text        NOT NULL,
            source_version  text,
            files_seen      integer     NOT NULL DEFAULT 0,
            files_loaded    integer     NOT NULL DEFAULT 0,
            files_skipped   integer     NOT NULL DEFAULT 0,
            files_replaced  integer     NOT NULL DEFAULT 0,
            rows_loaded     bigint      NOT NULL DEFAULT 0,
            error           text,
            -- A finished run always has an end time; a failed one always says why.
            CHECK ((status = 'running') = (finished_at IS NULL)),
            CHECK ((status = 'failed') = (error IS NOT NULL))
        );
        COMMENT ON TABLE raw._ingest_runs IS 'One row per ingest run, with per-run file and row counters.';
    """)

    # --- 2. File ledger ----------------------------------------------------------------------
    op.execute("""
        CREATE TABLE raw._ingest_files (
            provider     text        NOT NULL,
            entity       text        NOT NULL,
            source_path  text        NOT NULL,
            sha256       text        NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            row_count    integer     NOT NULL CHECK (row_count >= 0),
            run_id       bigint      NOT NULL REFERENCES raw._ingest_runs (run_id),
            loaded_at    timestamptz NOT NULL DEFAULT now(),
            -- One ledger entry per file: the version whose rows are currently in raw.
            PRIMARY KEY (provider, source_path)
        );
        COMMENT ON TABLE raw._ingest_files IS 'Hash of the currently loaded version of each source file.';
    """)

    # --- 3. Raw provider tables (identical shape) --------------------------------------------
    for table in RAW_TABLES:
        op.execute(f"""
            CREATE TABLE {table} (
                source_path   text        NOT NULL,
                record_index  integer     NOT NULL CHECK (record_index >= 0),
                payload       jsonb       NOT NULL,
                run_id        bigint      NOT NULL REFERENCES raw._ingest_runs (run_id),
                loaded_at     timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (source_path, record_index)
            );
            COMMENT ON COLUMN {table}.source_path  IS 'File path relative to data/sources/.';
            COMMENT ON COLUMN {table}.record_index IS '0-based position in the file''s top-level JSON array.';
        """)

    # --- 4. Ownership ------------------------------------------------------------------------
    for table in ("raw._ingest_runs", "raw._ingest_files", *RAW_TABLES):
        op.execute(f"ALTER TABLE {table} OWNER TO scoutbase_pipeline;")


def downgrade() -> None:
    op.execute(f"""
        DROP TABLE IF EXISTS {", ".join(reversed(RAW_TABLES))};
        DROP TABLE IF EXISTS raw._ingest_files;
        DROP TABLE IF EXISTS raw._ingest_runs;
    """)
