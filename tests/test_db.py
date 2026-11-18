from monitor import db
from monitor.config import SeriesSpec


def spec(key="k1", label="L"):
    return SeriesSpec(key=key, label=label, unit="POSTS / H", family="anti-trans",
                      term_id="t", metric="posts", query="q", endpoint="recent")


def test_init_writes_and_updates_series(tmp_path):
    with db.session(tmp_path / "m.db") as conn:
        db.init(conn, [spec(label="A")])
        db.init(conn, [spec(label="B")])
        rows = conn.execute("SELECT key, label, unit, family, term_id, metric FROM series").fetchall()
    assert [tuple(r) for r in rows] == [("k1", "B", "POSTS / H", "anti-trans", "t", "posts")]


def test_points_upsert_range_and_replace_hours(tmp_path):
    with db.session(tmp_path / "m.db") as conn:
        db.init(conn, [spec()])
        assert db.upsert_points(conn, "k1", [(3600, 1), (7200, 2)]) == 2
        db.upsert_points(conn, "k1", [(3600, 5)])
        assert db.points(conn, "k1", 0, 7200) == [(3600, 5.0), (7200, 2.0)]
        assert db.point_range(conn, "k1") == (3600, 7200)
        assert db.point_range(conn, "none") is None
        db.upsert_points(conn, "k1", [(5000, 9)])
        db.replace_hours(conn, "k1", [(7200, 4)])
        assert db.points(conn, "k1", 0, 9000) == [(3600, 5.0), (7200, 4.0)]


def test_record_run(tmp_path):
    with db.session(tmp_path / "m.db") as conn:
        db.init(conn, [])
        db.record_run(conn, "twitter", False, 0, "boom")
        row = conn.execute("SELECT platform, ok, points, error FROM runs").fetchone()
    assert tuple(row) == ("twitter", 0, 0, "boom")
