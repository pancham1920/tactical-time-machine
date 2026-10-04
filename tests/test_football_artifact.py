"""Artifact round-trip tests with synthetic data, no network or real dataset."""

import gzip
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.football_artifact import COLUMNS, sha256, validate_database
from scripts.prepare_football_db import prepare
from scripts.install_football_db import copy_bounded, install


class FootballArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.db"
        connection = sqlite3.connect(self.source)
        for table, columns in COLUMNS.items():
            connection.execute(f"CREATE TABLE {table} ({', '.join(c + ' TEXT' for c in columns)}, excluded TEXT)")
            values = ["2024-01-01" if c in ("date", "transfer_date") else "1" for c in columns]
            connection.execute(f"INSERT INTO {table} VALUES ({', '.join('?' for _ in range(len(columns) + 1))})", values + ["not shipped"])
        connection.execute("CREATE TABLE private_extra (value TEXT)")
        connection.commit()
        connection.close()
        self.original_hash = sha256(self.source)
        self.output = self.root / "artifact"
        self.manifest = prepare(self.source, self.output)
        self.artifact = self.output / "football_vault.db.gz"

    def test_round_trip_preserves_rows_and_leaves_original_unchanged(self):
        destination = self.root / "installed.db"
        install(str(self.artifact), self.manifest["artifact_sha256"], destination)
        metadata = validate_database(destination)
        self.assertEqual(metadata["row_counts"], {table: 1 for table in COLUMNS})
        self.assertEqual(metadata["match_date_min"], "2024-01-01")
        self.assertEqual(sha256(destination), self.manifest["database_sha256"])
        self.assertEqual(sha256(self.source), self.original_hash)
        with sqlite3.connect(destination) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM agent_match_view").fetchone()[0], 1)
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='private_extra'").fetchone())
            for table, columns in COLUMNS.items():
                self.assertEqual([r[1] for r in connection.execute(f"PRAGMA table_info({table})")], columns)

    def test_bad_checksum_does_not_publish(self):
        destination = self.root / "installed.db"
        with self.assertRaisesRegex(ValueError, "checksum"):
            install(str(self.artifact), "0" * 64, destination)
        self.assertFalse(destination.exists())

    def test_existing_database_and_artifact_directory_are_preserved(self):
        with self.assertRaises(FileExistsError):
            install(str(self.artifact), self.manifest["artifact_sha256"], self.source)
        with self.assertRaises(FileExistsError):
            prepare(self.source, self.output)
        self.assertEqual(sha256(self.source), self.original_hash)

    def test_invalid_sqlite_is_not_published_even_with_valid_checksum(self):
        invalid = self.root / "invalid.gz"
        with gzip.open(invalid, "wb") as stream:
            stream.write(b"not a database")
        destination = self.root / "installed.db"
        with self.assertRaises(sqlite3.DatabaseError):
            install(str(invalid), sha256(invalid), destination)
        self.assertFalse(destination.exists())

    def test_bounded_copy(self):
        with self.assertRaisesRegex(ValueError, "size limit"):
            copy_bounded(BytesIO(b"12345"), BytesIO(), 4)

    def test_http_download_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            install("http://example.com/data.gz", "0" * 64, self.root / "installed.db")

    def test_missing_source_does_not_create_database(self):
        missing = self.root / "missing.db"
        with self.assertRaises(sqlite3.OperationalError):
            prepare(missing, self.root / "other")
        self.assertFalse(missing.exists())
