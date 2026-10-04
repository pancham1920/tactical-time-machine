"""Database execution and structured SQL-error classification."""

from pathlib import Path
import json
import re
import sqlite3
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool
from langchain_core.tools import tool


# This file is at src/tools/db_tools.py, so parents[2] is the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "football_vault.db"
MAX_ROWS = 100
READ_QUERY = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
SQL_TIMEOUT_SECONDS = 5
WRITE_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM)\b",
    re.IGNORECASE,
)


def get_database_engine() -> Engine:
    """Create a SQLAlchemy engine that connects to the local SQLite database."""
    if not DATABASE_PATH.is_file():
        raise FileNotFoundError("Football database is missing; seed it before querying.")
    def connect():
        connection = sqlite3.connect(DATABASE_PATH.resolve().as_uri() + "?mode=ro", uri=True,
                                     timeout=2, check_same_thread=False)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 128 * 1024)
        connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 20_000)
        deadline = time.monotonic() + SQL_TIMEOUT_SECONDS
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        connection.set_authorizer(authorize_sql)
        return connection
    return create_engine("sqlite://", creator=connect, poolclass=NullPool)


KNOWN_TABLES = {"agent_match_view", "players", "clubs", "appearances", "games", "transfers", "player_valuations"}


def authorize_sql(action, first, second, database, source):
    """SQLite-enforced table/function boundary, independent of prompt and regex."""
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    # SQLite reports no database name for COUNT(*)'s empty-column read.
    if action == sqlite3.SQLITE_READ and database in ("main", None) and first in KNOWN_TABLES:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (second or "").lower() in {
        "count", "sum", "avg", "min", "max", "total", "round", "abs",
        "coalesce", "ifnull", "nullif", "lower", "upper", "trim", "ltrim", "rtrim",
        "substr", "substring", "length", "instr", "like", "glob",
        "date", "datetime", "strftime", "julianday", "unixepoch",
        "row_number", "rank", "dense_rank", "lag", "lead", "first_value", "last_value",
    }:
        return sqlite3.SQLITE_OK
    # SQLAlchemy checks this pragma when initializing its SQLite dialect.
    if action == sqlite3.SQLITE_PRAGMA and first == "read_uncommitted" and second is None:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def classify_sql_error(error: SQLAlchemyError) -> dict:
    """Allow corrections only for known query mistakes, not infrastructure failures."""
    detail = str(getattr(error, "orig", error)).split("\n")[0][:300]
    lower = detail.lower()
    retryable = False
    code = "database_error"
    if "no such table:" in lower:
        table = lower.split("no such table:", 1)[1].strip().split(".")[-1].strip('"`[]')
        retryable = table not in KNOWN_TABLES
        code = "unknown_table" if retryable else "database_setup"
    elif any(marker in lower for marker in (
        "no such column:", "ambiguous column name:", "syntax error", "incomplete input",
        "no such function:", "wrong number of arguments to function", "misuse of aggregate",
        "misuse of window", "having clause on a non-aggregate", "order by term does not match",
    )):
        retryable = True
        code = "invalid_sql"
    # SQLite's short diagnostic helps the model correct SQL; omit SQLAlchemy's
    # appended SQL/parameters/traceback. Infrastructure errors get a generic message.
    message = f"SQLite query failed: {detail}" if retryable else "Database unavailable or setup incomplete; SQL rewriting cannot fix this."
    return {"error": message, "error_code": code, "retryable": retryable}


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
        return {"error": validation_error, "error_code": "query_rejected", "retryable": False}

    engine = None
    try:
        engine = get_database_engine()
        with engine.connect() as connection:
            result = connection.execute(text(query))
            rows = [
                dict(row)
                for row in result.mappings().fetchmany(MAX_ROWS + 1)
            ]
    except SQLAlchemyError as exc:
        return classify_sql_error(exc)
    except FileNotFoundError:
        return {"error": "Football database is missing; seed it before querying.", "error_code": "database_setup", "retryable": False}
    finally:
        if engine is not None:
            engine.dispose()

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
