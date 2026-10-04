"""Install a trusted, SHA-256-pinned gzip artifact during deployment build."""

import argparse
import gzip
import os
from pathlib import Path
import re
import tempfile
from urllib.request import urlopen

from scripts.football_artifact import sha256, validate_database

MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
MAX_DATABASE_BYTES = 1024 * 1024 * 1024


def copy_bounded(source, target, limit: int) -> None:
    total = 0
    while block := source.read(1024 * 1024):
        total += len(block)
        if total > limit:
            raise ValueError("Football artifact exceeds the size limit.")
        target.write(block)


def install(source: str, expected_sha256: str, destination: Path) -> None:
    if not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256):
        raise ValueError("A valid FOOTBALL_DB_SHA256 is required.")
    if destination.exists():
        raise FileExistsError("Refusing to replace an existing football database.")
    # Stage beside the destination, then publish without overwriting an existing file.
    with tempfile.TemporaryDirectory(prefix="football-install-", dir=destination.parent) as work:
        artifact = Path(work) / "artifact.gz"
        if source.startswith("https://"):
            with urlopen(source, timeout=60) as response, artifact.open("wb") as target:
                if not response.geturl().startswith("https://"):
                    raise ValueError("Artifact download must remain HTTPS.")
                copy_bounded(response, target, MAX_DOWNLOAD_BYTES)
        else:
            if "://" in source:
                raise ValueError("Remote artifacts require HTTPS.")
            with Path(source).open("rb") as local, artifact.open("wb") as target:
                copy_bounded(local, target, MAX_DOWNLOAD_BYTES)
        if sha256(artifact) != expected_sha256.lower():
            raise ValueError("Football artifact checksum mismatch.")
        staged = Path(work) / "football_vault.db"
        with gzip.open(artifact, "rb") as zipped, staged.open("wb") as target:
            copy_bounded(zipped, target, MAX_DATABASE_BYTES)
        validate_database(staged)
        os.link(staged, destination)  # Atomic no-clobber publication, same filesystem.


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", default=os.getenv("FOOTBALL_DB_URL"))
    parser.add_argument("--sha256", default=os.getenv("FOOTBALL_DB_SHA256", ""))
    parser.add_argument("--destination", type=Path, default=Path("football_vault.db"))
    args = parser.parse_args()
    if not args.artifact:
        parser.error("Set FOOTBALL_DB_URL or provide --artifact.")
    install(args.artifact, args.sha256, args.destination)
    print("Football database installed and validated.")
