"""Consistent SQLite backup while bot/web are running. Run as the raffle user."""
import datetime
import os
import sqlite3
from pathlib import Path

os.umask(0o077)
source = Path("/var/lib/shopen-raffle/raffle.sqlite3")
folder = source.parent / "backups"
folder.mkdir(mode=0o700, exist_ok=True)
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
target = folder / f"raffle-{stamp}.sqlite3"
with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(target) as dest:
    src.backup(dest)
print(target)
