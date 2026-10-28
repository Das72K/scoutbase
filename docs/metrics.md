# Metrics

Measured numbers only. Each section says when, on what, and how it was measured.

## Raw ingestion: StatsBomb Open Data

Measured 2026-10-29 with `make ingest` on a freshly migrated database (first at 0004, again at
0005 after the changes below), at the pinned
commit `4b73468fc5b0f1950f9f66fada70ad3a4f9327cb` (`config/sources.yaml`).

**Environment:** WSL2 (12 vCPU, 7 GB RAM), PostgreSQL 16.15 (pgvector image) in Docker, Python
3.12.3, psycopg 3.3.6. The "before" numbers read the checkout from the repository on the Windows
drive (`/mnt/d`, a 9p share); the "after" numbers read it from `~/.local/share/scoutbase` on the
WSL ext4 filesystem (`SCOUTBASE_DATA_DIR`, see run times below).

### Volume

| Season                   | Matches |
|--------------------------|--------:|
| FIFA World Cup 2022      |      64 |
| UEFA Euro 2024           |      51 |
| 1. Bundesliga 2023/2024  |      34 |
| **Total**                | **149** |

| Entity       | Files | Raw rows | Note                                              |
|--------------|------:|---------:|---------------------------------------------------|
| competitions |     1 |       80 | every competition/season in the open data         |
| matches      |     3 |      149 | one file per season                               |
| lineups      |   149 |      298 | one row per team per match; 7,184 player entries  |
| events       |   149 |  560,326 | 3,761 per match on average                        |
| **Total**    | **302** | **560,853** |                                               |

Source JSON on disk: 461 MB (`du -sh <sources>/statsbomb/data`, the same in both locations).

Order check: for all 560,326 event rows, `record_index + 1` equals StatsBomb's own
`payload->>'index'`, so the original order of events is preserved.

### Table sizes

`pg_total_relation_size` (heap + TOAST + indexes) after the first run (identical before and
after 0005, except `_ingest_files`: 144 kB → 152 kB with the size/mtime columns):

| Table                        |     Size |
|------------------------------|---------:|
| `raw.statsbomb_events`       |   579 MB |
| `raw.statsbomb_lineups`      |   920 kB |
| `raw.statsbomb_matches`      |   352 kB |
| `raw._ingest_files`          |   152 kB |
| `raw.statsbomb_competitions` |    96 kB |
| `raw._ingest_runs`           |    32 kB |
| **Total `raw`**              | **581 MB** |

### Run times: before and after (2026-10-29)

Two changes: the data moved from `/mnt/d` to the Linux filesystem, and a no-change run skips a
file whose size and mtime match the ledger without reading it (0005); `--verify` still hashes
everything. Times are `finished_at - started_at` from `raw._ingest_runs`; `make ingest` wall
clock (which adds about 2 s of `uv run` start-up) is in brackets. A first run starts from empty
raw tables; repeated runs are listed as min–max of three consecutive runs.

| Run                                       | Before: `/mnt/d`, hash every file | New code, still on `/mnt/d` | After: ext4, new code     |
|-------------------------------------------|----------------------------------:|----------------------------:|--------------------------:|
| First run (302 files, 560,853 rows)       |                   26.0 s (28.2 s) |             24.9 s (27.3 s) |       **19.8 s** (23.4 s) |
| No change (size + mtime only, 0 hashed)   |                                 — |  1.8–3.5 s (3.6–6.5 s)      | **0.6–1.2 s** (2.7–4.4 s) |
| No change, every file hashed              |      5.5 s (8.2 s), the only mode |  6.6–8.4 s (8.6–11.1 s), `--verify` | 1.7–2.2 s (3.8–4.9 s), `--verify` |

So the no-change run went from 5.5 s to 0.6–1.2 s, and the first run from 26.0 s to 19.8 s.
Reading from ext4 instead of `/mnt/d` is what speeds up hashing (all 302 files: 6.6–8.4 s →
1.7–2.2 s); with the size/mtime shortcut a no-change run hashes nothing at all (0 files hashed
in every no-change run above).

**Switching over.** The first run after the move found every mtime different from the ledger
(new files from a fresh fetch), so it hashed all 302 files, found every hash unchanged and
reloaded nothing: 1.4 s (2.9 s), 0 rows loaded. It recorded the new mtimes, so the next run
skipped without hashing.

### Fetch

A partial clone + sparse checkout of the three seasons into `~/.local/share/scoutbase` (ext4)
took 57.2 s wall clock (5.6 s user, 1.5 s sys) and produced 302 files / 461 MB at the pinned
commit. An earlier fresh fetch to the native filesystem took 58.6 s; network transfer from
GitHub dominates.

Before the move, re-running `make fetch-statsbomb` on the existing checkout in
`data/sources/statsbomb` (on `/mnt/d`) took 88.9 s wall clock and left the checkout unchanged.

### Test isolation

`make test` runs in a throwaway `scoutbase_test` database. With the full data loaded, the working
database was identical before and after a `make test` run (47 tests): 560,326 events, 298 lineup
rows, 149 matches, 7 ingest runs, Alembic version 0005. The suite checks this itself and fails
otherwise.
