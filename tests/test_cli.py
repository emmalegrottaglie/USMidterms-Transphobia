import sqlite3

import pytest
from test_pause import config_copy, settings_for
from test_study import HOUR, make_config, populate, ts

from monitor import __main__ as cli
from monitor import db, pause, study
from monitor.collectors import Result, x


def no_request(*a, **k):
    raise AssertionError("a request was made")


def test_collect_does_nothing_while_paused(tmp_path, monkeypatch, capsys):
    st, cfg = settings_for(tmp_path), make_config()
    pause.pause(st, "between events", 1000)
    monkeypatch.setattr(x, "run", no_request)
    monkeypatch.setattr(x, "backfill", no_request)
    assert cli.main(["collect"], config=cfg, settings=st, config_dir=config_copy(tmp_path)) == 0
    assert "between events" in capsys.readouterr().out
    assert not st.usage_file.exists()


def test_collect_runs_the_live_pass_when_not_paused(tmp_path, monkeypatch):
    st, cfg, calls = settings_for(tmp_path), make_config(), []

    async def fake_run(config, settings, now):
        calls.append(now)

    monkeypatch.setattr(x, "run", fake_run)
    with db.session(st.db_path) as conn:
        db.init(conn, cfg.series)
    assert cli.main(["collect"], config=cfg, settings=st, config_dir=config_copy(tmp_path),
                    studies_dir=tmp_path / "studies") == 0
    assert len(calls) == 1


def test_backfill_writes_mapped_series(tmp_path, monkeypatch, capsys):
    st, cfg, seen = settings_for(tmp_path), make_config(), {}
    term = next(s for s in cfg.series if s.term_id == "a1" and s.metric == "posts")
    other = next(s for s in cfg.series if s.term_id == "a1" and s.metric == "reposts")
    start = ts("2026-11-01")

    async def fake_backfill(config, settings, s, e=None, missing_before=False):
        seen.update(start=s, end=e, mb=missing_before)
        return {term.query: Result(points={term.key: [(start + HOUR, 5.0), (start + 2 * HOUR, 7.0)],
                                           other.key: [(start + HOUR, 1.0)]}, errors=["boom"])}

    monkeypatch.setattr(x, "backfill", fake_backfill)
    code = cli.main(["backfill", "--from", "2026-11-01", "--to", "2026-11-03", "--missing-before"],
                    config=cfg, settings=st, config_dir=config_copy(tmp_path))
    out = capsys.readouterr().out
    assert code == 0 and seen == {"start": start, "end": ts("2026-11-04"), "mb": True}
    assert f"{term.key}: 2 points" in out and "error: boom" in out
    with db.session(st.db_path) as conn:
        assert db.points(conn, term.key, 0, 10**10) == [(start + HOUR, 5.0), (start + 2 * HOUR, 7.0)]
        assert db.points(conn, other.key, 0, 10**10) == [(start + HOUR, 1.0)]
        assert tuple(conn.execute("SELECT ok, points FROM runs").fetchone()) == (1, 3)


def test_backfill_without_token_exits_nonzero(tmp_path, monkeypatch, capsys):
    st, cfg = settings_for(tmp_path), make_config()

    async def refuse(*a, **k):
        raise RuntimeError("Twitter bearer token (X_BEARER_TOKEN) not set")

    monkeypatch.setattr(x, "backfill", refuse)
    assert cli.main(["backfill", "--from", "2026-11-01"], config=cfg, settings=st,
                    config_dir=config_copy(tmp_path)) == 1
    assert "X_BEARER_TOKEN" in capsys.readouterr().err


def test_import_tracker_missing_file_exits_nonzero(tmp_path, capsys):
    st, cfg = settings_for(tmp_path), make_config()
    assert cli.main(["import-tracker", "--db", str(tmp_path / "nope.db")], config=cfg, settings=st,
                    config_dir=config_copy(tmp_path)) == 1
    assert "not found" in capsys.readouterr().err


def test_import_tracker_prints_counts(tmp_path, capsys):
    st, cfg = settings_for(tmp_path), make_config()
    key = "x.probe.en.posts"
    src = tmp_path / "tracker.db"
    c = sqlite3.connect(src)
    c.execute("CREATE TABLE points(key TEXT, ts INTEGER, value REAL, PRIMARY KEY(key, ts))")
    c.executemany("INSERT INTO points VALUES (?, ?, ?)", [(key, 3600, 1.0), (key, 7200, 2.0)])
    c.commit()
    c.close()
    assert cli.main(["import-tracker", "--db", str(src)], config=cfg, settings=st,
                    config_dir=config_copy(tmp_path)) == 0
    assert f"{key}: 2 points" in capsys.readouterr().out


def test_freeze_without_note_is_refused(tmp_path):
    st, cfg = settings_for(tmp_path), make_config()
    with pytest.raises(SystemExit) as e:
        cli.main(["study", "build", "--freeze"], config=cfg, settings=st, config_dir=config_copy(tmp_path),
                 studies_dir=tmp_path / "studies")
    assert e.value.code == 2 and not (tmp_path / "studies").exists()


def test_study_build_freezes_only_with_the_flag(tmp_path, capsys):
    st, cfg, cdir = settings_for(tmp_path), make_config(), config_copy(tmp_path)
    with db.session(st.db_path) as conn:
        db.init(conn, cfg.series)
        populate(conn, cfg)
    assert cli.main(["study", "build"], config=cfg, settings=st, config_dir=cdir, studies_dir=tmp_path / "s") == 0
    assert not (tmp_path / "s").exists()
    assert cli.main(["study", "build", "us-midterms-2026", "--freeze", "--note", "first"], config=cfg,
                    settings=st, config_dir=cdir, studies_dir=tmp_path / "s") == 0
    assert "v1.json" in capsys.readouterr().out


def test_pause_and_resume_commands(tmp_path):
    st, cfg, cdir = settings_for(tmp_path), make_config(), config_copy(tmp_path)
    assert cli.main(["pause", "--reason", "quiet"], config=cfg, settings=st, config_dir=cdir) == 0
    assert pause.state(st)["reason"] == "quiet"
    assert cli.main(["resume", "--reason", "news", "--event-date", "2027-01-06", "--event-short", "HEARING",
                     "--event-label", "A hearing", "--event-source", "C-SPAN"], config=cfg, settings=st,
                    config_dir=cdir) == 0
    assert pause.state(st) is None and study.get("hearing-2027-01-06", cdir)


def future_study(cdir):
    return pause.open_study({"date": "2099-01-01", "short": "FUTURE", "label": "Later", "source": "s",
                             "status": "reported"}, cdir)


def test_freeze_of_open_study_reports_error_without_traceback(tmp_path, capsys):
    st, cfg, cdir = settings_for(tmp_path), make_config(), config_copy(tmp_path)
    sid = future_study(cdir)
    assert cli.main(["study", "build", sid, "--freeze", "--note", "n"], config=cfg, settings=st,
                    config_dir=cdir, studies_dir=tmp_path / "s") == 1
    assert "still open" in capsys.readouterr().err and not (tmp_path / "s").exists()


def broken_study(cdir):
    with (cdir / "studies.toml").open("a", encoding="utf-8") as f:
        f.write('\n[[study]]\nid = "broken"\ntitle = "t"\nevents = ["NOPE"]\n')


def test_missing_event_is_reported_by_build_and_close_if_done(tmp_path, capsys):
    st, cfg, cdir = settings_for(tmp_path), make_config(), config_copy(tmp_path)
    broken_study(cdir)
    assert cli.main(["study", "build"], config=cfg, settings=st, config_dir=cdir) == 1
    assert "NOPE" in capsys.readouterr().err
    assert cli.main(["close-if-done"], config=cfg, settings=st, config_dir=cdir) == 1
    assert "NOPE" in capsys.readouterr().err


def test_collect_keeps_pass_and_reports_missing_event(tmp_path, monkeypatch, capsys):
    st, cfg, cdir, calls = settings_for(tmp_path), make_config(), config_copy(tmp_path), []
    broken_study(cdir)

    async def fake_run(config, settings, now):
        calls.append(now)

    monkeypatch.setattr(x, "run", fake_run)
    assert cli.main(["collect"], config=cfg, settings=st, config_dir=cdir) == 0
    assert len(calls) == 1 and "NOPE" in capsys.readouterr().err


def test_collect_treats_unreadable_pause_file_as_paused(tmp_path, monkeypatch, capsys):
    st, cfg = settings_for(tmp_path), make_config()
    monkeypatch.setattr(x, "run", no_request)
    st.db_path.parent.mkdir(parents=True)
    for bad in ("{not json", "[]", '{"since": 1}'):
        (st.db_path.parent / "pause.json").write_text(bad, encoding="utf-8")
        assert cli.main(["collect"], config=cfg, settings=st, config_dir=config_copy(tmp_path)) == 0
        assert "unreadable" in capsys.readouterr().out


@pytest.mark.parametrize("args", [
    ["backfill", "--from", "2026-11-01T00:00:00"],
    ["backfill", "--from", "2026-11-01", "--to", "2026-11-03+01:00"],
    ["backfill", "--from", "20261101"],
    ["backfill", "--from", "2026-11-05", "--to", "2026-11-04"],
    ["pause", "--reason", "  "],
    ["resume", "--reason", "r", "--event-date", "2027-01-06T10:00", "--event-short", "S",
     "--event-label", "L", "--event-source", "src"],
    ["resume", "--reason", "r", "--event-date", "2027-01-06", "--event-short", "S",
     "--event-label", "L", "--event-source", ""],
    ["resume", "--reason", "r", "--event-date", "2027-01-06", "--event-short", " ",
     "--event-label", "L", "--event-source", "src"],
    ["resume", "--reason", "r", "--event-date", "2027-01-06", "--event-short", "S",
     "--event-label", "", "--event-source", "src"],
    ["study", "build", "--freeze", "--note", " "],
])
def test_bad_arguments_are_refused_cleanly(tmp_path, monkeypatch, args):
    st, cfg, cdir = settings_for(tmp_path), make_config(), config_copy(tmp_path)
    monkeypatch.setattr(x, "backfill", no_request)
    before = (cdir / "events.toml").read_text(encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        cli.main(args, config=cfg, settings=st, config_dir=cdir, studies_dir=tmp_path / "s")
    assert e.value.code == 2
    assert (cdir / "events.toml").read_text(encoding="utf-8") == before and pause.state(st) is None


def test_backfill_same_day_range_is_one_day(tmp_path, monkeypatch):
    st, cfg, seen = settings_for(tmp_path), make_config(), {}

    async def fake(config, settings, s, e=None, missing_before=False):
        seen.update(s=s, e=e)
        return {}

    monkeypatch.setattr(x, "backfill", fake)
    cli.main(["backfill", "--from", "2026-11-03", "--to", "2026-11-03"], config=cfg, settings=st,
             config_dir=config_copy(tmp_path))
    assert seen["e"] - seen["s"] == 86400
