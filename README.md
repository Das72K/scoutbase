# SCOUTBASE

[![CI](https://github.com/Das72K/scoutbase/actions/workflows/ci.yml/badge.svg)](https://github.com/Das72K/scoutbase/actions/workflows/ci.yml)

Elite clubs recruit with dedicated analysts, licensed event feeds and in-house data platforms;
clubs below that level — Romanian Liga 2 / Liga 3, academies, small clubs across Europe — still
recruit through agent tips, highlight clips and a spreadsheet nobody trusts. **SCOUTBASE** is a
football recruitment data platform for them: it ingests match data from several providers into
one trusted canonical model, measures players fairly (per-90, position percentiles, xG/xA),
finds statistically similar alternatives, and runs the recruitment workflow — shortlists, scout
reports, contracts and squad budget — with each club's data isolated at the database level.
Every number must be explainable.

> Built as a Databases course project and a data engineering portfolio piece.
> Scope and data model: [`docs/01-problem-statement.md`](docs/01-problem-statement.md),
> [`docs/02-data-model.md`](docs/02-data-model.md).

## Architecture

One PostgreSQL 16 database (with pgvector), one schema per layer:

```
raw  ──►  staging  ──►  core  ──►  marts
(as delivered)  (cleaned,     (canonical,       (star schema,
                 typed)        provider-free)    analytics-ready)

app    operational, multi-tenant data (shortlists, reports, contracts) — protected by RLS
audit  append-only change log
```

| Schema    | Holds                                              | Written by     |
|-----------|----------------------------------------------------|----------------|
| `raw`     | Provider JSON exactly as received (`JSONB`)        | Ingestion jobs |
| `staging` | One typed table per provider entity                | dbt            |
| `core`    | Canonical, provider-independent model              | dbt            |
| `marts`   | Star schema + aggregates for the app and ML        | dbt            |
| `app`     | Shortlists, scout reports, contracts, scenarios    | FastAPI (RLS)  |
| `audit`   | Who changed what, when, old/new values             | Triggers       |

### Database roles

| Group role           | Login user                | Access                                                    |
|----------------------|---------------------------|-----------------------------------------------------------|
| `scoutbase_pipeline` | `scoutbase_pipeline_user` | `USAGE` + `CREATE` on `raw`, `staging`, `core`, `marts`   |
| `scoutbase_app`      | `scoutbase_app_user`      | read `core` + `marts`, read/write `app`, `INSERT` only on `audit` |
| `scoutbase_readonly` | `scoutbase_readonly_user` | `SELECT` on `marts` only                                  |

Grants are applied with `ALTER DEFAULT PRIVILEGES`, so future tables inherit them. The tests
prove each restriction by attempting the forbidden action and expecting PostgreSQL to refuse.

## Repository layout

```
db/         Alembic migrations (explicit SQL via op.execute)
pipeline/   ingestion jobs (raw layer)            — not started
dbt/        staging → core → marts models         — not started
api/        FastAPI backend                       — not started
web/        frontend                              — not started
tests/      pytest suite
scripts/    helper scripts
docs/       problem statement, data model, ADRs
data/       local provider data (gitignored)
```

## Quickstart

Requirements: Docker, [uv](https://docs.astral.sh/uv/), GNU Make.

```bash
cp .env.example .env    # then change the passwords
make up                 # Postgres 16 + pgvector on localhost:5433
make migrate            # extensions, schemas, roles
make test               # foundation tests
```

Other targets: `make psql`, `make downgrade` (one step; `REV=base` for all), `make down`,
`make reset` (drop the volume and rebuild from scratch).

## Project status

- [x] Repository scaffold, Docker Compose, CI
- [x] Database foundation: extensions, layer schemas, roles and grants
- [ ] Raw ingestion: StatsBomb Open Data
- [ ] Raw ingestion: Wyscout public dataset
- [ ] dbt staging models
- [ ] Canonical core model + crosswalks (entity resolution)
- [ ] Marts: star schema, per-90, percentiles, SCD2 `dim_player`
- [ ] Player similarity (pgvector embeddings)
- [ ] `app` schema with row-level security per club + audit triggers
- [ ] FastAPI backend
- [ ] Web frontend
- [ ] Synthetic contracts / wages / scout reports generator
- [ ] (Extension) Video → tracking data

## Data attribution

**StatsBomb Open Data.** Event data provided by [StatsBomb](https://statsbomb.com/) via the
[StatsBomb Open Data](https://github.com/statsbomb/open-data) repository, used under its terms
for non-commercial purposes. Any published work using this data must credit StatsBomb as the
data source and display the StatsBomb logo.

<!-- TODO: add the official StatsBomb logo from the open-data repository, e.g.
     <img src="docs/assets/statsbomb-logo.png" alt="StatsBomb" width="200"> -->

**Wyscout public dataset.** Soccer event data released by Wyscout. The dataset is listed in
the SoBigData catalogue for **non-commercial use only** — the same restriction as StatsBomb Open
Data. Any work using it must cite both papers:

> Pappalardo, L., Cintia, P., Rossi, A., Massucco, E., Ferragina, P., Pedreschi, D., & Giannotti, F. (2019).
> *A public data set of spatio-temporal match events in soccer competitions.*
> Scientific Data, 6, 236. https://doi.org/10.1038/s41597-019-0247-7

> Pappalardo, L., Cintia, P., Ferragina, P., Massucco, E., Pedreschi, D., & Giannotti, F. (2019).
> *PlayeRank: Data-driven Performance Evaluation and Player Ranking in Soccer via a Machine
> Learning Approach.* ACM Transactions on Intelligent Systems and Technology, 10(5), Article 59.
> https://doi.org/10.1145/3343172

## License

Code: [MIT](LICENSE) © Dorin Dascălu. The data sources above have their own terms.
