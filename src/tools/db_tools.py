"""Database tools for the football agent.

Block 3 will add safe, read-only SQLite query functions here.
"""

from pathlib import Path
import json
import re

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from langchain_core.tools import tool


# This file is at src/tools/db_tools.py, so parents[2] is the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "football_vault.db"
MAX_ROWS = 100
READ_QUERY = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
WRITE_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM)\b",
    re.IGNORECASE,
)


def get_database_engine() -> Engine:
    """Create a SQLAlchemy engine that connects to the local SQLite database."""
    return create_engine(f"sqlite:///{DATABASE_PATH}")


def validate_read_query(query: str) -> str | None:
    """Return an error message unless query is one read-only SQL statement."""
    statement = query.strip()

    if not statement:
        return "The SQL query cannot be empty."
    if not READ_QUERY.match(statement):
        return "Only read-only SELECT queries are allowed."
    if WRITE_KEYWORDS.search(statement):
        return "The query contains a database-changing command."
    if ";" in statement.rstrip(";"):
        return "Submit exactly one SQL statement."

    return None


def run_query(query: str) -> dict[str, object]:
    """Run a safe SQL query and return up to MAX_ROWS result rows."""
    validation_error = validate_read_query(query)
    if validation_error:
        return {"error": validation_error}

    engine = get_database_engine()

    try:
        with engine.connect() as connection:
            result = connection.execute(text(query))
            rows = [
                dict(row)
                for row in result.mappings().fetchmany(MAX_ROWS + 1)
            ]
    except SQLAlchemyError as exc:
        return {"error": f"SQLite query failed: {exc}"}

    truncated = len(rows) > MAX_ROWS
    return {"rows": rows[:MAX_ROWS], "truncated": truncated}


def format_query_results(result: dict[str, object]) -> str:
    """Convert a query result into JSON text that a future agent tool can return."""
    rows = result.get("rows", [])
    columns = list(rows[0]) if rows else []
    return json.dumps({"columns": columns, **result}, default=str)


@tool
def execute_sql(query: str) -> str:
    """Run one read-only SQLite query against the football database.

    Use SELECT queries only. Prefer agent_match_view for historical match-score
    questions. Results are limited to 100 rows.
    """
    result = run_query(query)
    return format_query_results(result)
