"""Record file size and mtime in the ingest ledger, so unchanged files skip without hashing.

WHY: a no-change run used to read and hash every file (461 MB for three StatsBomb seasons) just
to find out nothing had changed. With the size and mtime of the version that was hashed last,
the ingest can skip a file whose size and mtime both match without opening it, the same
trade-off git makes for its index. Any difference in size or mtime still goes through the hash,
so a touched but unchanged file is hashed and skipped, never reloaded. `--verify` ignores the
shortcut and hashes everything, for the rare rewrite that keeps both size and mtime.

  * raw._ingest_files.file_size / file_mtime_ns   os.stat() of the last hashed version. mtime is
    kept in integer nanoseconds (st_mtime_ns): a timestamptz would round it to microseconds and
    a rounded value would never compare equal. NULL for files loaded before this migration,
    which are therefore hashed once on the next run.
  * raw._ingest_runs.files_hashed / verify        how many files the run had to read, and
    whether it was a --verify run, so the run log shows whether the shortcut worked.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE raw._ingest_files
            ADD COLUMN file_size     bigint CHECK (file_size >= 0),
            ADD COLUMN file_mtime_ns bigint;
        COMMENT ON COLUMN raw._ingest_files.file_size     IS 'Size in bytes when last hashed.';
        COMMENT ON COLUMN raw._ingest_files.file_mtime_ns IS 'st_mtime_ns when last hashed.';

        ALTER TABLE raw._ingest_runs
            ADD COLUMN files_hashed integer NOT NULL DEFAULT 0,
            ADD COLUMN verify       boolean NOT NULL DEFAULT false;
    """)

    # The data directory is configurable now (SCOUTBASE_DATA_DIR), so data/sources/ was wrong.
    for table in ("statsbomb_competitions", "statsbomb_matches", "statsbomb_lineups", "statsbomb_events"):
        op.execute(f"""
            COMMENT ON COLUMN raw.{table}.source_path IS 'File path relative to the sources directory.';
        """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE raw._ingest_runs  DROP COLUMN verify, DROP COLUMN files_hashed;
        ALTER TABLE raw._ingest_files DROP COLUMN file_mtime_ns, DROP COLUMN file_size;
    """)
    for table in ("statsbomb_competitions", "statsbomb_matches", "statsbomb_lineups", "statsbomb_events"):
        op.execute(f"""
            COMMENT ON COLUMN raw.{table}.source_path IS 'File path relative to data/sources/.';
        """)
