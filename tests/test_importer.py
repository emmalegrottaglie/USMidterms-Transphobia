import sqlite3

from monitor import db
from monitor.config import Config, SeriesSpec
from monitor.importer import import_tracker


def spec(key):
    return SeriesSpec(key=key, label=key, unit="POSTS / H", family="anti-trans",
                      term_id=None, metric="posts", query="q", endpoint="recent")


def make_tracker(path, rows):
    c = sqlite3.connect(path)
    c.executescript(
        "CREATE TABLE series(key TEXT PRIMARY KEY, kind TEXT, platform TEXT, label TEXT, unit TEXT,"
        " region TEXT, tags TEXT, active INTEGER);"
        "CREATE TABLE points(key TEXT, ts INTEGER, value REAL, PRIMARY KEY(key, ts));"
    )
    for key, active, pts in rows:
        c.execute("INSERT INTO series VALUES (?, 'x', 'twitter', ?, 'u', 'en', '[]', ?)", (key, key, active))
        c.executemany("INSERT INTO points VALUES (?, ?, ?)", [(key, t, v) for t, v in pts])
    c.commit()
    c.close()


def config(*keys):
    return Config(terms=(), series=tuple(spec(k) for k in keys), probe_query="p", family_queries={})


def test_import_copies_matching_keys_only(tmp_path):
    tr = tmp_path / "t.db"
    make_tracker(tr, [("a", 1, [(3600, 1.5), (7200, 2.5)]), ("other", 1, [(3600, 9)])])
    with db.session(tmp_path / "m.db") as conn:
        db.init(conn, config("a", "missing").series)
        result = import_tracker(conn, config("a", "missing"), tr)
        assert result == {"a": 2}
        assert db.points(conn, "a", 0, 9999) == [(3600, 1.5), (7200, 2.5)]
        assert db.point_range(conn, "other") is None


def test_import_is_idempotent(tmp_path):
    tr = tmp_path / "t.db"
    make_tracker(tr, [("a", 1, [(3600, 1.5), (7200, 2.5)])])
    cfg = config("a")
    with db.session(tmp_path / "m.db") as conn:
        db.init(conn, cfg.series)
        import_tracker(conn, cfg, tr)
        import_tracker(conn, cfg, tr)
        assert conn.execute("SELECT COUNT(*), SUM(value) FROM points").fetchone()[:] == (2, 4.0)


def test_import_ignores_tracker_active_flag(tmp_path):
    tr = tmp_path / "t.db"
    make_tracker(tr, [("a", 0, [(3600, 1.0)])])
    with db.session(tmp_path / "m.db") as conn:
        db.init(conn, config("a").series)
        assert import_tracker(conn, config("a"), tr) == {"a": 1}
