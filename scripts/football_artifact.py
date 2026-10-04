"""Compact football artifact helpers. No model calls or conversation data."""

import hashlib
from pathlib import Path
import sqlite3


COLUMNS = {
    "players": "player_id current_club_id current_club_name name position sub_position market_value_in_eur".split(),
    "clubs": "club_id name domestic_competition_id".split(),
    "appearances": "player_id game_id date goals assists yellow_cards red_cards minutes_played".split(),
    "games": "game_id competition_id season date home_club_id away_club_id home_club_name away_club_name home_club_goals away_club_goals".split(),
    "transfers": "player_name transfer_date from_club_name to_club_name transfer_fee market_value_in_eur".split(),
    "player_valuations": "player_id date market_value_in_eur current_club_name".split(),
}
INDEXES = {
    "players": ["player_id", "current_club_id"],
    "clubs": ["club_id", "domestic_competition_id"],
    "appearances": ["game_id", "player_id", "date"],
    "games": ["game_id", "competition_id", "date", "home_club_id", "away_club_id"],
    "transfers": ["transfer_date"],
    "player_valuations": ["player_id", "date"],
}
VIEW_SQL = """
CREATE VIEW agent_match_view AS
SELECT g.date, COALESCE(home.name, g.home_club_name) AS home_team,
       COALESCE(away.name, g.away_club_name) AS away_team,
       g.home_club_goals AS home_score, g.away_club_goals AS away_score
FROM games AS g
LEFT JOIN clubs AS home ON home.club_id = g.home_club_id
LEFT JOIN clubs AS away ON away.club_id = g.away_club_id
WHERE g.date IS NOT NULL
"""


def readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_database(path: Path) -> dict:
    connection = readonly(path)
    try:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Football artifact failed SQLite integrity check.")
        counts = {}
        for table, columns in COLUMNS.items():
            connection.execute(f'SELECT {", ".join(columns)} FROM {table} LIMIT 0')
            counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if not counts["games"]:
            raise ValueError("Football artifact contains no games.")
        connection.execute("SELECT date, home_team, away_team, home_score, away_score FROM agent_match_view LIMIT 1").fetchall()
        dates = connection.execute("SELECT MIN(date), MAX(date) FROM games").fetchone()
        return {"row_counts": counts, "match_date_min": dates[0], "match_date_max": dates[1]}
    finally:
        connection.close()
