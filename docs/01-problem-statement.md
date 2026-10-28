# 01 — Problem Statement

## The problem

Elite clubs run recruitment on data: dedicated analysts, licensed event and tracking feeds
(StatsBomb, Wyscout, SkillCorner, Second Spectrum) and in-house data platforms.

Clubs below that level (Romanian Liga 2 / Liga 3, academies, small clubs across Europe) usually
recruit through:

- agent tips and highlight clips sent over messaging apps,
- spreadsheets that one person maintains and nobody else trusts,
- memory and gut feeling during a short transfer window.

The result: expensive signings that don't fit, cheap talent that gets missed, and a wage bill
that nobody models before committing to it.

## Who uses SCOUTBASE

| User | Needs |
|---|---|
| **Head of recruitment** | Find candidates for a role, compare them fairly, keep a shortlist, decide |
| **Scout** | Write reports, follow assigned players, see only what their club allows |
| **Sporting director** | Squad plan, contract expiries, budget and wage impact of a transfer |
| **Coach** (read-only) | See the shortlist and the data behind it |
| **Platform admin** | Manage clubs (tenants), users, data pipelines |

## What SCOUTBASE does

1. **Ingests match data** from several providers and unifies it into one trusted model.
2. **Measures players fairly**: per-90 stats, position-based percentiles, xG/xA, form over time.
3. **Finds alternatives**: "players statistically similar to X, but younger / cheaper / contract ending".
4. **Runs the recruitment workflow**: shortlists, scout reports, status pipeline, audit trail.
5. **Plans the squad and budget**: contracts, wages, expiry timeline, "what-if" transfers.
6. **Keeps each club's data private**: multi-tenant platform with row-level security.
7. **(Extension)** Turns a club's own match video into tracking data (distance, sprints, heatmaps).

## What SCOUTBASE does NOT do (scope guard)

- No betting, no fantasy football, no live scores.
- No scraping of commercial sites (Transfermarkt, FBref, ...).
- No "AI predicts the next superstar". Every number must be explainable.

## Data strategy

| Use | Sources |
|---|---|
| Course + portfolio | StatsBomb Open Data (non-commercial, attribution + logo), Wyscout public dataset (non-commercial use only per the SoBigData catalogue; cite both Pappalardo et al. 2019 papers, see below), Metrica / SkillCorner samples for tracking |
| Business data that isn't public | Synthetic generator: contracts, wages, market values, scout reports |
| Commercial product | Client's own video (our tracking pipeline), client uploads (CSV), client's own licensed provider API ("bring your own data") |

**Licensing.** Both event sources are **non-commercial only**: StatsBomb Open Data by its own
terms (credit StatsBomb + show its logo), and the Wyscout public dataset as listed in the
SoBigData catalogue. They are fine for the course and the portfolio, but a commercial SCOUTBASE
must run on client-owned or client-licensed data (third row above).

Wyscout citations (both are required):

- Pappalardo, L. et al. (2019). *A public data set of spatio-temporal match events in soccer
  competitions.* Scientific Data, 6, 236. https://doi.org/10.1038/s41597-019-0247-7
- Pappalardo, L. et al. (2019). *PlayeRank: Data-driven Performance Evaluation and Player Ranking
  in Soccer via a Machine Learning Approach.* ACM TIST, 10(5), Article 59.
  https://doi.org/10.1145/3343172

## Success criteria (measurable)

- Two event providers unified into one canonical model, with cross-provider validation on overlapping matches.
- Full pipeline reproducible with one command (`docker compose up` + one pipeline run).
- Incremental runs load only new data; re-running never duplicates rows.
- Data-quality tests run in CI and block bad data.
- Every club sees only its own operational data (proved with tests, not promised).
- Numbers for the README measured, not guessed: rows, pipeline runtime, test count, query latency.
