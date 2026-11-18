"""Copy hourly points for the configured series out of the bot tracker's database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import db
from .config import Config


def import_tracker(conn: sqlite3.Connection, config: Config, tracker_db: Path) -> dict[str, int]:
    """Copy points for every key in `config.series` that has points in the tracker DB,
    whether or not the tracker still marks the series active. Safe to run repeatedly."""
    src = sqlite3.connect(f"file:{Path(tracker_db).resolve().as_posix()}?mode=ro", uri=True)
    try:
        copied: dict[str, int] = {}
        for spec in config.series:
            rows = src.execute(
                "SELECT ts, value FROM points WHERE key = ? ORDER BY ts", (spec.key,)
            ).fetchall()
            if rows:
                copied[spec.key] = db.upsert_points(conn, spec.key, rows)
        return copied
    finally:
        src.close()
