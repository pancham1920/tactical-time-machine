"""Build the small fictional dataset. Never overwrites an existing database."""

import argparse
import json
from pathlib import Path
import sqlite3

from scripts.football_artifact import COLUMNS, INDEXES, VIEW_SQL

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/sample_football.json"


def create_sample(path: Path) -> None:
    data = json.loads(FIXTURE.read_text())["tables"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb"):
        pass
    connection = sqlite3.connect(path)
    numeric = {"season", "goals", "assists", "yellow_cards", "red_cards", "minutes_played", "home_club_goals", "away_club_goals"}
    try:
        for table, columns in COLUMNS.items():
            definitions = []
            for column in columns:
                if column in ("market_value_in_eur", "transfer_fee"):
                    kind = "REAL"
                elif column in ("competition_id", "domestic_competition_id"):
                    kind = "TEXT"
                elif column.endswith("_id") or column in numeric:
                    kind = "INTEGER"
                else:
                    kind = "TEXT"
                definitions.append(f"{column} {kind}")
            connection.execute(f"CREATE TABLE {table} ({', '.join(definitions)})")
            connection.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in columns)})", data[table])
            for column in INDEXES[table]:
                connection.execute(f"CREATE INDEX idx_{table}_{column} ON {table} ({column})")
        connection.execute(VIEW_SQL)
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/sample/football_vault.db")
    args = parser.parse_args()
    create_sample(args.output)
    print("Created fictional sample: 8 matches, 6 players, 4 clubs. Original data unchanged.")
