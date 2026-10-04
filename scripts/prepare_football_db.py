"""Create a compact, all-row deployment artifact from the local football DB."""

import argparse
import gzip
import json
from pathlib import Path
import shutil
import sqlite3

from scripts.football_artifact import COLUMNS, INDEXES, VIEW_SQL, readonly, sha256, validate_database


def prepare(source: Path, output: Path) -> dict:
    # Never overwrite a previous artifact or touch the source database.
    source_connection = readonly(source)
    try:
        source_connection.execute("BEGIN")  # Consistent read snapshot across tables.
        output.mkdir(parents=True, exist_ok=False)
        database = output / "football_vault.db"
        target = sqlite3.connect(database)
        try:
            for table, columns in COLUMNS.items():
                # Derive SQLite affinities, not arbitrary source schema SQL.
                types = {row[1]: row[2].upper() for row in source_connection.execute(f"PRAGMA table_info({table})")}
                definitions = []
                for column in columns:
                    declared = types[column]
                    affinity = "INTEGER" if "INT" in declared else "REAL" if any(t in declared for t in ("REAL", "FLOA", "DOUB")) else "TEXT"
                    definitions.append(f"{column} {affinity}")
                target.execute(f"CREATE TABLE {table} ({', '.join(definitions)})")
                rows = source_connection.execute(f"SELECT {', '.join(columns)} FROM {table}")
                while batch := rows.fetchmany(5000):
                    target.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' for _ in columns)})", batch)
                for column in INDEXES[table]:
                    target.execute(f"CREATE INDEX idx_{table}_{column} ON {table} ({column})")
            target.execute(VIEW_SQL)
            target.commit()
        finally:
            target.close()
    finally:
        source_connection.close()
    metadata = validate_database(database)
    artifact = output / "football_vault.db.gz"
    with database.open("rb") as raw, artifact.open("xb") as compressed:
        with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as zipped:
            shutil.copyfileobj(raw, zipped)
    metadata.update({
        "format_version": 1,
        "coverage": "All rows from six agent tables; only documented columns and match-view join IDs retained. Other source tables excluded.",
        "source_release": "Unknown original release; see DATA_SOURCES.md",
        "columns": COLUMNS,
        "database_bytes": database.stat().st_size,
        "artifact_bytes": artifact.stat().st_size,
        "database_sha256": sha256(database),
        "artifact_sha256": sha256(artifact),
    })
    (output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("football_vault.db"))
    parser.add_argument("--output", type=Path, default=Path("build/football-artifact"))
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output), indent=2))
