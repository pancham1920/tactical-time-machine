# Football Agent Folder Analysis

Generated on 2026-06-12.

> Historical snapshot taken before implementation. The application-readiness
> statements below no longer describe the current project. See [README.md](README.md)
> for current capabilities and [DATA_SOURCES.md](DATA_SOURCES.md) for data provenance.
> Dataset counts and findings below describe that local snapshot, not every release.

## Executive Summary

This folder is currently a raw football data workspace, not an implemented application or agent. It contains 12 CSV datasets under `data/`, totaling about 7.24 million data rows and roughly 684 MB on disk. The code scaffolding is effectively empty: `requirements.txt`, `.env`, and `scripts/seed_db.py` are zero-byte files, and `src/` contains no files.

The dataset is rich enough to support a football analytics or query agent, but the folder needs project structure, a database loading path, schema validation, and documentation before it can be treated as a maintainable repo.

## Current Folder Contents

| Path | Status |
| --- | --- |
| `data/*.csv` | Main asset: football entities, matches, events, lineups, appearances, valuations, and transfers |
| `scripts/seed_db.py` | Empty placeholder |
| `requirements.txt` | Empty placeholder |
| `.env` | Empty placeholder |
| `src/` | Empty directory |
| `.git` | Not present; this folder is not currently a git repository |

## Data Inventory

| File | Rows | Columns | Approx size | Notes |
| --- | ---: | ---: | ---: | --- |
| `appearances.csv` | 1,862,208 | 13 | 139.8 MB | Player match appearances from 2012-07-03 to 2026-03-22 |
| `club_games.csv` | 173,966 | 11 | 10.3 MB | One row per club per game; composite key `game_id + club_id` is unique |
| `clubs.csv` | 796 | 17 | 0.2 MB | Club dimension, but `total_market_value` is entirely empty |
| `competitions.csv` | 67 | 11 | <0.1 MB | Competition dimension |
| `countries.csv` | 118 | 8 | <0.1 MB | Country dimension |
| `game_events.csv` | 1,242,945 | 11 | 145.8 MB | Match events from 2006-06-09 to 2026-03-25 |
| `game_lineups.csv` | 3,049,833 | 10 | 322.3 MB | Largest table; mostly complete |
| `games.csv` | 86,983 | 23 | 24.5 MB | Match facts from 2006-06-09 to 2026-03-25 |
| `national_teams.csv` | 118 | 17 | <0.1 MB | National team dimension; `coach_name` is entirely empty |
| `player_valuations.csv` | 616,377 | 6 | 28.6 MB | Time series from 2000-01-20 to 2026-03-30 |
| `players.csv` | 47,702 | 26 | 16.0 MB | Player dimension |
| `transfers.csv` | 157,186 | 10 | 12.7 MB | Transfer history from 1993-07-01 to 2030-06-30 |

## Data Model

The natural core entities are:

- `players`, keyed by `player_id`
- `clubs`, keyed by `club_id`
- `competitions`, keyed by `competition_id`
- `countries`, keyed by `country_id`
- `games`, keyed by `game_id`
- `national_teams`, keyed by `national_team_id`

Fact and event-style tables are:

- `appearances`, keyed by `appearance_id`
- `game_events`, keyed by `game_event_id`
- `game_lineups`, keyed by `game_lineups_id`
- `club_games`, keyed naturally by `game_id + club_id`
- `player_valuations`, keyed naturally by `player_id + date`
- `transfers`, keyed naturally by `player_id + transfer_date + from_club_id + to_club_id`

All explicit primary-key-style columns checked above are unique. The only duplicate composite check found was in `game_lineups`, where `game_id + player_id + club_id + type` has 12 duplicate combinations across 3,049,833 rows. The provided `game_lineups_id` column itself is unique.

## Data Quality Findings

### Completeness

Important missingness:

- `clubs.total_market_value`: 100% missing.
- `clubs.coach_name`: 88.69% missing.
- `national_teams.coach_name`: 100% missing.
- `players.current_national_team_id`: 93.52% missing.
- `players.international_caps` and `players.international_goals`: 62.85% missing.
- `players.agent_name`: 46.50% missing.
- `players.contract_expiration_date`: 34.56% missing.
- `players.market_value_in_eur` and `players.highest_market_value_in_eur`: 17.77% missing.
- `transfers.market_value_in_eur`: 38.71% missing.
- `transfers.transfer_fee`: 34.88% missing.
- `games.attendance`: 12.27% missing.
- `games.home_club_position` and `games.away_club_position`: 29.00% missing.

This does not make the dataset unusable, but analytics should distinguish between unknown values, unavailable source values, and values that are legitimately not applicable.

### Referential Integrity

The dataset is not closed under all foreign-key relationships. Many fact rows reference players or clubs that are not present in the current `players.csv` or `clubs.csv` dimensions.

Examples:

- `game_lineups.player_id`: 323,862 nonempty references are missing from `players.player_id`.
- `game_lineups.club_id`: 381,987 nonempty references are missing from `clubs.club_id`.
- `game_events.player_id`: 130,617 nonempty references are missing from `players.player_id`.
- `game_events.club_id`: 168,187 nonempty references are missing from `clubs.club_id`.
- `club_games.club_id` and `club_games.opponent_id`: 23,912 references each are missing from `clubs.club_id`.
- `games.home_club_id`: 12,744 references are missing from `clubs.club_id`.
- `games.away_club_id`: 11,168 references are missing from `clubs.club_id`.
- `transfers.from_club_id`: 94,781 references are missing from `clubs.club_id`.
- `transfers.to_club_id`: 77,569 references are missing from `clubs.club_id`.

This looks like a subset dimension issue rather than random corruption: historical games, transfers, and events likely reference clubs or players outside the current dimension files. A database loader should either avoid strict foreign-key enforcement on these columns, add placeholder dimension rows, or source complete dimension tables.

### Date Semantics

Most match and event data ends in March 2026. `transfers.csv` contains 1,989 rows after 2026-06-12, with dates reaching 2030-06-30. These may represent scheduled future moves, loan returns, or contractually planned transfers, but they should not be mixed blindly into historical transfer analysis.

## Readiness Assessment

This folder is ready for:

- Exploratory analysis using DuckDB, pandas, SQLite, or Postgres.
- Building a football query layer over raw CSVs.
- Prototyping player, club, match, valuation, and transfer analytics.

This folder is not yet ready for:

- Running an app or agent.
- Installing dependencies from `requirements.txt`.
- Seeding a database through `scripts/seed_db.py`.
- CI checks or reproducible local setup.
- Strict relational loading without handling missing referenced entities.

## Recommended Next Steps

1. Add a `README.md` that documents the data source, expected setup, and common workflows.
2. Fill `requirements.txt` with the intended stack. For a lightweight analytics project, start with `duckdb`, `pandas`, `pyarrow`, and `python-dotenv`.
3. Implement `scripts/seed_db.py` to load CSVs into DuckDB or Postgres with explicit schemas and indexes.
4. Add a data validation script that checks row counts, primary key uniqueness, required columns, date ranges, and expected missingness thresholds.
5. Decide how to handle incomplete dimensions before enforcing foreign keys.
6. Add `.gitignore` rules for local databases, virtual environments, caches, and OS files such as `.DS_Store`.
7. If this becomes a git repo, avoid storing large raw CSVs directly unless that is intentional; consider Git LFS, DVC, or external object storage.

## Suggested Minimal Implementation Plan

The fastest useful path is:

1. Use DuckDB as the local analytical database.
2. Create a loader that imports every CSV into a same-named table.
3. Create indexes on frequent join keys: `player_id`, `club_id`, `game_id`, `competition_id`, and date columns.
4. Add views for common questions:
   - Player match summaries.
   - Club season summaries.
   - Transfer history with market value.
   - Game event timelines.
   - Player valuation timelines.
5. Add tests or validation checks that fail when the CSV schema changes unexpectedly.

This would turn the current folder from a raw dataset dump into a reproducible football analytics foundation.
