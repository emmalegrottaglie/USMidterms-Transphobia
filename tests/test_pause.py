import shutil
import tomllib
from pathlib import Path

from test_study import make_config, new_db, populate, ts

from monitor import ROOT, pause, study
from monitor.config import Settings

DAY = 86400


def settings_for(tmp_path) -> Settings:
    return Settings(db_path=tmp_path / "data" / "m.db", x_bearer_token="t", x_max_requests_per_day=150,
                    usage_file=tmp_path / "usage.json", public_url="")


def config_copy(tmp_path) -> Path:
    d = tmp_path / "config"
    d.mkdir(exist_ok=True)
    for name in ("events.toml", "studies.toml"):
        shutil.copy(ROOT / "config" / name, d / name)
    return d


def test_close_if_done_freezes_then_pauses(tmp_path):
    cfg, st, cdir = make_config(), settings_for(tmp_path), config_copy(tmp_path)
    conn = new_db(tmp_path, cfg)
    populate(conn, cfg)
    out = pause.close_if_done(conn, cfg, ts("2026-11-20"), st, cdir, tmp_path / "studies")
    assert out is not None and out["id"] == "us-midterms-2026"
    assert (tmp_path / "studies" / "us-midterms-2026" / "v1.json").exists()
    record = pause.state(st)
    assert record and "US midterm elections" in record["reason"]


def test_close_if_done_waits_a_day_after_window_end(tmp_path):
    cfg, st, cdir = make_config(), settings_for(tmp_path), config_copy(tmp_path)
    conn = new_db(tmp_path, cfg)
    populate(conn, cfg)
    end = study.frame(study.get(directory=cdir), cdir)["end"]
    assert pause.close_if_done(conn, cfg, end + DAY, st, cdir, tmp_path / "studies") is None  # 1 s short
    assert pause.state(st) is None and not (tmp_path / "studies").exists()
    assert pause.close_if_done(conn, cfg, end + 1 + DAY, st, cdir, tmp_path / "studies") is not None


def test_close_if_done_never_freezes_twice(tmp_path):
    cfg, st, cdir = make_config(), settings_for(tmp_path), config_copy(tmp_path)
    conn = new_db(tmp_path, cfg)
    populate(conn, cfg)
    assert pause.close_if_done(conn, cfg, ts("2026-11-20"), st, cdir, tmp_path / "studies")
    assert pause.close_if_done(conn, cfg, ts("2026-11-21"), st, cdir, tmp_path / "studies") is None
    assert len(study.versions("us-midterms-2026", tmp_path / "studies")) == 1


def test_close_if_done_needs_the_last_window_day(tmp_path):
    cfg, st, cdir = make_config(), settings_for(tmp_path), config_copy(tmp_path)
    conn = new_db(tmp_path, cfg)
    populate(conn, cfg)
    conn.execute("DELETE FROM points WHERE key = 'x.family.framing.en.posts' AND ts > ?", (ts("2026-11-17"),))
    assert pause.close_if_done(conn, cfg, ts("2026-11-20"), st, cdir, tmp_path / "studies") is None
    assert pause.state(st) is None


def test_resume_opens_study_and_event(tmp_path):
    st, cdir = settings_for(tmp_path), config_copy(tmp_path)
    pause.pause(st, "waiting", 1000)
    event = {"date": "2027-01-06", "short": "HEARING", "label": 'Senate "trans" hearing \\ day',
             "source": "C-SPAN, 6 January 2027", "status": "confirmed"}
    study_id = pause.resume(st, "major event", event, cdir)
    assert study_id == "hearing-2027-01-06"
    assert pause.state(st) is None
    events = tomllib.loads((cdir / "events.toml").read_text(encoding="utf-8"))["event"]
    new = events[-1]
    assert new["short"] == "HEARING" and new["source"] and new["status"] == "confirmed"
    assert new["label"] == event["label"]
    s = study.get(study_id, cdir)
    assert s.events == ("HEARING",) and (s.pre_days, s.post_days, s.reference_days) == (14, 14, 21)
    assert event["label"] in s.question
    assert study.get(directory=cdir).id == study_id  # newest
    assert pause.resume(st, "again", event, cdir) == study_id  # no duplicate
    assert len(tomllib.loads((cdir / "events.toml").read_text(encoding="utf-8"))["event"]) == len(events)


def test_close_if_done_does_not_freeze_without_family_series(tmp_path):
    import dataclasses
    cfg, st, cdir = make_config(), settings_for(tmp_path), config_copy(tmp_path)
    conn = new_db(tmp_path, cfg)
    populate(conn, cfg)
    cfg = dataclasses.replace(cfg, series=tuple(s for s in cfg.series if not s.key.startswith("x.family.")))
    assert pause.close_if_done(conn, cfg, ts("2026-11-20"), st, cdir, tmp_path / "studies") is None
    assert pause.state(st) is None and not (tmp_path / "studies").exists()


def test_state_fails_closed_on_a_damaged_file(tmp_path):
    st = settings_for(tmp_path)
    assert pause.state(st) is None  # missing file: collecting
    st.db_path.parent.mkdir(parents=True)
    for bad in ("{not json", "[]", "null", '{"since": 1}', '{"reason": " "}', ""):
        pause.path(st).write_text(bad, encoding="utf-8")
        record = pause.state(st)
        assert record and "unreadable" in record["reason"], bad
    pause.path(st).write_bytes(b"\xff\xfe\x00")
    assert "unreadable" in pause.state(st)["reason"]


def test_open_study_round_trips_newlines_quotes_and_backslashes(tmp_path):
    cdir = config_copy(tmp_path)
    label = 'Line one\nLine "two" ' + chr(92) + ' end\ttab'
    source = 'C-SPAN "clip"\nsecond line, C:' + chr(92) + 'path'
    sid = pause.open_study({"date": "2027-02-01", "short": "Q", "label": label, "source": source,
                            "status": "reported"}, cdir)
    new = tomllib.loads((cdir / "events.toml").read_text(encoding="utf-8"))["event"][-1]
    assert new["label"] == label and new["source"] == source
    assert study.get(sid, cdir).title == label
