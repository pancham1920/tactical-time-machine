"""Build the local SQLite database from the CSV files in data/."""

from pathlib import Path
import re

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


# `__file__` is this script. parents[1] moves from scripts/ to the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = PROJECT_ROOT / "football_vault.db"


def create_database_engine() -> Engine:
    """Create a connection factory for the local SQLite database."""
    database_url = f"sqlite:///{DATABASE_PATH}"
    return create_engine(database_url)


def to_snake_case(name: str) -> str:
    """Convert a CSV header or filename into a SQLite-friendly name."""
    name = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip())
    return name.strip("_").lower()


def load_csv_table(engine: Engine, csv_path: Path) -> int:
    """Load one CSV file into a matching SQLite table in manageable chunks."""
    table_name = to_snake_case(csv_path.stem)
    row_count = 0

    for chunk_number, dataframe in enumerate(
        pd.read_csv(csv_path, chunksize=100_000, low_memory=False)
    ):
        dataframe.columns = [to_snake_case(column) for column in dataframe.columns]
        dataframe.to_sql(
            table_name,
            engine,
            if_exists="replace" if chunk_number == 0 else "append",
            index=False,
        )
        row_count += len(dataframe)

    return row_count


INDEXES = {
    "appearances": ["game_id", "player_id", "date"],
    "club_games": ["game_id", "club_id", "opponent_id"],
    "clubs": ["club_id", "domestic_competition_id"],
    "game_events": ["game_id", "player_id", "club_id", "date"],
    "game_lineups": ["game_id", "player_id", "club_id", "date"],
    "games": ["game_id", "competition_id", "date", "home_club_id", "away_club_id"],
    "player_valuations": ["player_id", "date", "current_club_id"],
    "players": ["player_id", "current_club_id"],
    "transfers": ["player_id", "transfer_date", "from_club_id", "to_club_id"],
}


def create_indexes(engine: Engine) -> int:
    """Create indexes for columns commonly used to search and join data."""
    index_count = 0

    with engine.begin() as connection:
        for table_name, columns in INDEXES.items():
            for column_name in columns:
                index_name = f"idx_{table_name}_{column_name}"
                connection.exec_driver_sql(
                    f'CREATE INDEX IF NOT EXISTS "{index_name}" '
                    f'ON "{table_name}" ("{column_name}")'
                )
                index_count += 1

    return index_count


def create_agent_match_view(engine: Engine) -> None:
    """Create the compact match-results view used by the football agent."""
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP VIEW IF EXISTS agent_match_view")
        connection.exec_driver_sql("""
            CREATE VIEW agent_match_view AS
            SELECT
                g.date,
                COALESCE(home.name, g.home_club_name) AS home_team,
                COALESCE(away.name, g.away_club_name) AS away_team,
                g.home_club_goals AS home_score,
                g.away_club_goals AS away_score
            FROM games AS g
            LEFT JOIN clubs AS home ON home.club_id = g.home_club_id
            LEFT JOIN clubs AS away ON away.club_id = g.away_club_id
            WHERE g.date IS NOT NULL
        """)


def validate_database(engine: Engine) -> None:
    """Print a small query result that proves the agent match view works."""
    with engine.connect() as connection:
        match_count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM agent_match_view"
        ).scalar_one()
        sample_matches = connection.exec_driver_sql("""
            SELECT date, home_team, away_team, home_score, away_score
            FROM agent_match_view
            LIMIT 3
        """).mappings().all()

    print(f"\nVerified agent_match_view: {match_count:,} matches")
    for match in sample_matches:
        print(
            f"- {match['date']}: {match['home_team']} {match['home_score']}-"
            f"{match['away_score']} {match['away_team']}"
        )


def find_csv_files() -> list[Path]:
    """Return the CSV files that will be loaded into the database."""
    return sorted(DATA_DIR.glob("*.csv"))


def main() -> None:
    csv_files = find_csv_files()

    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {DATA_DIR}")

    print(f"Found {len(csv_files)} CSV files:")
    for csv_file in csv_files:
        print(f"- {csv_file.name}")

    engine = create_database_engine()
    print("\nLoading CSV files into SQLite:")
    for csv_file in csv_files:
        row_count = load_csv_table(engine, csv_file)
        print(f"- {csv_file.stem}: {row_count:,} rows")

    index_count = create_indexes(engine)
    print(f"\nCreated {index_count} search indexes.")

    create_agent_match_view(engine)
    validate_database(engine)


if __name__ == "__main__":
    main()
