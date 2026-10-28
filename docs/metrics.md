# Metrics

Measured numbers only. Each section says when, on what, and how it was measured.

## Raw ingestion: StatsBomb Open Data

Measured 2026-10-29 with `make ingest` on a freshly migrated database (0004), at the pinned
commit `4b73468fc5b0f1950f9f66fada70ad3a4f9327cb` (`config/sources.yaml`).

**Environment:** WSL2 (12 vCPU, 7 GB RAM), PostgreSQL 16.15 (pgvector image) in Docker, Python
3.12.3, psycopg 3.3.6. The checkout lives in `data/sources/statsbomb` on the Windows drive
(`/mnt/d`, 9p), so file reads go through the WSL file share.

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

Source JSON on disk: 461 MB (`du -sh data/sources/statsbomb/data`).

Order check: for all 560,326 event rows, `record_index + 1` equals StatsBomb's own
`payload->>'index'`, so the original order of events is preserved.

### Table sizes

`pg_total_relation_size` (heap + TOAST + indexes) after the first run:

| Table                        |     Size |
|------------------------------|---------:|
| `raw.statsbomb_events`       |   579 MB |
| `raw.statsbomb_lineups`      |   920 kB |
| `raw.statsbomb_matches`      |   352 kB |
| `raw._ingest_files`          |   144 kB |
| `raw.statsbomb_competitions` |    96 kB |
| `raw._ingest_runs`           |    32 kB |
| **Total `raw`**              | **581 MB** |

### Run times

| Run                       | Files loaded / skipped | Rows loaded | Run log (`finished_at - started_at`) | `scoutbase` CLI | `make ingest` wall clock |
|---------------------------|-----------------------:|------------:|-------------------------------------:|----------------:|-------------------------:|
| First (empty `raw`)       |              302 / 0   |     560,853 |                               26.0 s |          26.1 s |                   28.2 s |
| Second (nothing changed)  |              0 / 302   |           0 |                                5.5 s |           5.6 s |                    8.2 s |

The second run still reads and hashes all 461 MB to compare against `raw._ingest_files`; it
writes nothing to the raw tables. The wall-clock column adds `uv run` start-up.

### Fetch

A partial clone + sparse checkout of the same three seasons into a directory on the native
Linux filesystem (not `/mnt/d`) took 58.6 s wall clock (5.4 s user, 1.3 s sys) and produced
the same 302 files / 461 MB. It's dominated by network transfer from GitHub.

Re-running `make fetch-statsbomb` on the existing checkout in `data/sources/statsbomb` (on
`/mnt/d`) took 88.9 s wall clock and left the checkout unchanged (same commit, same 302 files).
