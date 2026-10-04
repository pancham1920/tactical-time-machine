# Football dataset provenance

## Source and attribution

The local files strongly match **Football Data from Transfermarkt**, published
on Kaggle by `davidcariboo` and maintained in `dcaribou/transfermarkt-datasets`.
The upstream project links to the same Kaggle page and documents all 12 table
names present locally. Sample local records include Transfermarkt page URLs
and `transfermarkt-scraper` paths. The original archive/version was not saved,
so this identifies the likely source rather than a byte-for-byte release match.

- [Dataset and CSV download](https://www.kaggle.com/datasets/davidcariboo/player-scores)
- [Upstream dataset project](https://github.com/dcaribou/transfermarkt-datasets)
- [Kaggle public metadata](https://www.kaggle.com/api/v1/datasets/view/davidcariboo/player-scores)
- [Upstream CC0 1.0 license](https://github.com/dcaribou/transfermarkt-datasets/blob/master/LICENSE)

Sources checked on 2026-09-22. Kaggle's metadata reports `CC0: Public Domain`,
and the upstream repository includes CC0 1.0 Universal. This records the
publisher's declared license; it does not establish rights to separately linked
photos, logos, or other third-party assets. The project does not bundle those
assets or the raw dataset. Its application code has no selected license yet.

| Provenance field | Status |
| --- | --- |
| Original website referenced by records | Transfermarkt |
| Dataset publisher / slug | `davidcariboo/player-scores` on Kaggle |
| Published license | CC0: Public Domain (Kaggle); CC0 1.0 Universal (upstream) |
| Local download date / release identifier | Not recorded; exact snapshot not verified |

Raw CSVs and the derived SQLite database remain local and are ignored by Git.
Download them from the publisher instead of storing the large files in this
source repository. Credit for collecting and preparing the source dataset
belongs to the upstream project; this application implements the agent and API.

## Preparing a compatible dataset

Open the [Kaggle dataset page](https://www.kaggle.com/datasets/davidcariboo/player-scores),
use its download option (sign in if prompted), and extract the CSV files from
the archive. Review the listed terms for the version you download and keep its
version identifier. Place the CSV files directly in a `data/` directory at the
project root, without an extra nested archive folder:

```text
data/
├── appearances.csv
├── club_games.csv
├── clubs.csv
├── competitions.csv
├── countries.csv
├── game_events.csv
├── game_lineups.csv
├── games.csv
├── national_teams.csv
├── player_valuations.csv
├── players.csv
└── transfers.csv
```

Then run, from the activated project environment:

```bash
python scripts/seed_db.py
```

The loader imports all CSVs in `data/`, normalizes their headers and filenames,
creates configured indexes, and creates `agent_match_view`. Its `INDEXES` mapping
and `create_agent_match_view()` in [scripts/seed_db.py](scripts/seed_db.py) show
which tables and columns the loader requires. The agent's known query columns
are listed in [src/agents/prompts.py](src/agents/prompts.py). Different exports
may require adapting these mappings; arbitrary CSV files are not supported.

Seeding replaces matching existing tables. Back up a database with local changes
before re-running the command. The full local dataset occupies about 700 MB of
CSV files and produces approximately a 1 GB database; sizes vary by release.

## Coverage and interpretation

This is a static dataset rather than a live football feed. The archived local
assessment in [ANALYSIS.md](ANALYSIS.md) reports 86,983 matches and notes missing
values, references to absent players/clubs, and future-dated transfer records.
Those observations apply to that snapshot and are not a promise about other
downloads. Check date coverage before describing any answer as current.

## Reproducing a particular snapshot

The original local download version is unknown. A new download can contain
different row counts, dates, or columns. To make your own results reproducible,
record the Kaggle version, download date, published terms, and file checksums
alongside any reported metrics. This project does not claim an exact version
match based only on filenames or schema.

The offline automated tests create synthetic records and do not redistribute
any rows from these football CSVs. You can run the tests and the `/health`
endpoint without acquiring the dataset.

## Compact deployment artifact

`python -m scripts.prepare_football_db` creates a local, Git-ignored artifact
from the existing database without changing it. It preserves every row of
`players`, `clubs`, `appearances`, `games`, `transfers`, and `player_valuations`,
but projects them onto the agent's documented columns plus the match view's
club join IDs. Other tables and columns are excluded. `agent_match_view` and
lookup indexes are recreated. This is schema reduction, not a sampled season
or a newly downloaded dataset; it does not repair missing source records.

The accompanying manifest records row counts, match date range, projected
columns, sizes, and SHA-256 checksums. The original upstream release remains
unknown. Publishing this artifact is separate from local preparation and needs
review of the publisher's terms. No artifact upload has been performed.
