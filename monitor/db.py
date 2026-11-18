"""SQLite storage: series metadata, hourly points and collection runs."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from .config import SeriesSpec

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    key     TEXT PRIMARY KEY,
    label   TEXT NOT NULL,
    unit    TEXT NOT NULL,
    family  TEXT NOT NULL,
    term_id TEXT,
    metric  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS points (
    key   TEXT NOT NULL,
    ts    INTEGER NOT NULL,     -- unix seconds, UTC; value covers the hour ending at ts
    value REAL NOT NULL,
    PRIMARY KEY (key, ts)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS runs (
    id       INTEGER PRIMARY KEY,
    ts       INTEGER NOT NULL,
    platform TEXT NOT NULL,
    ok       INTEGER NOT NULL,
    points   INTEGER NOT NULL,
    error    TEXT
);
CREATE INDEX IF NOT EXISTS runs_platform_ts ON runs (platform, ts);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def session(path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init(conn: sqlite3.Connection, specs: Iterable[SeriesSpec]) -> None:
    """Create tables and write or update one series row per spec."""
    conn.executescript(SCHEMA)
    conn.executemany(
        """INSERT INTO series (key, label, unit, family, term_id, metric)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (key) DO UPDATE SET label=excluded.label, unit=excluded.unit,
             family=excluded.family, term_id=excluded.term_id, metric=excluded.metric""",
        [(s.key, s.label, s.unit, s.family, s.term_id, s.metric) for s in specs],
    )


def upsert_points(conn: sqlite3.Connection, key: str, points: Iterable[tuple[int, float]]) -> int:
    rows = [(key, int(ts), float(v)) for ts, v in points]
    conn.executemany(
        "INSERT INTO points (key, ts, value) VALUES (?, ?, ?) "
        "ON CONFLICT (key, ts) DO UPDATE SET value = excluded.value",
        rows,
    )
    return len(rows)


def replace_hours(conn: sqlite3.Connection, key: str, points: Iterable[tuple[int, float]]) -> int:
    """Store hourly values (stamped at each hour's end) as the only value of their hour:
    any other sample inside a covered hour is removed. Other hours are left alone."""
    points = [(int(ts), float(v)) for ts, v in points]
    conn.executemany(
        "DELETE FROM points WHERE key = ? AND ts > ? AND ts < ?",
        [(key, ts - 3600, ts) for ts, _ in points],
    )
    return upsert_points(conn, key, points)


def point_range(conn: sqlite3.Connection, key: str) -> tuple[int, int] | None:
    row = conn.execute("SELECT MIN(ts), MAX(ts) FROM points WHERE key = ?", (key,)).fetchone()
    return (row[0], row[1]) if row[0] is not None else None


def points(conn: sqlite3.Connection, key: str, start: int, end: int) -> list[tuple[int, float]]:
    """Points with ts in [start, end], oldest first."""
    rows = conn.execute(
        "SELECT ts, value FROM points WHERE key = ? AND ts BETWEEN ? AND ? ORDER BY ts",
        (key, start, end),
    )
    return [(int(t), float(v)) for t, v in rows]


def record_run(conn: sqlite3.Connection, platform: str, ok: bool, points: int, error: str | None = None) -> None:
    conn.execute(
        "INSERT INTO runs (ts, platform, ok, points, error) VALUES (?, ?, ?, ?, ?)",
        (int(time.time()), platform, int(ok), points, error),
    )
