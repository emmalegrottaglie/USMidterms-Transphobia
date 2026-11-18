import csv
import json
import shutil
import subprocess

from test_pause import config_copy, settings_for
from test_study import HOUR, make_config, new_db, populate, ts

from monitor import __main__ as cli
from monitor import db, static, study

NOW = ts("2026-11-20")


def built(tmp_path, with_data=True, **kw):
    cfg, st = make_config(), settings_for(tmp_path)
    conn = new_db(tmp_path, cfg)
    if with_data:
        populate(conn, cfg)
    out = static.export(conn, cfg, st, tmp_path / "site", NOW, config_copy(tmp_path), tmp_path / "studies", **kw)
    return cfg, conn, out


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_export_writes_every_series_csv(tmp_path):
    cfg, _, out = built(tmp_path)
    for s in cfg.series:
        rows = read_csv(out / "data" / "series" / f"{s.key}.csv")
        assert rows[0] == ["hour_end_utc", "value"]
        assert (out / "data" / "series" / f"{s.key}.json").exists()
    rows = read_csv(out / "data" / "series" / "x.a1.en.posts.csv")
    assert len(rows) > 1 and rows[1][0].endswith("Z") and "T" in rows[1][0]
    daily = read_csv(out / "data" / "daily.csv")
    assert daily[0] == ["day_utc", "key", "value"]
    assert (out / ".nojekyll").exists()
    assert (out / "design" / "terminal.css").exists()


def test_csv_has_no_rows_for_gap_hours(tmp_path):
    cfg, conn, _ = built(tmp_path, with_data=True)
    key = "x.a1.en.posts"
    gap = ts("2026-10-25") + 5 * HOUR
    conn.execute("DELETE FROM points WHERE key = ? AND ts = ?", (key, gap))
    out = static.export(conn, cfg, settings_for(tmp_path), tmp_path / "site2", NOW, config_copy(tmp_path),
                        tmp_path / "studies")
    stamps = [r[0] for r in read_csv(out / "data" / "series" / f"{key}.csv")[1:]]
    assert static._iso(gap) not in stamps
    assert static._iso(gap - HOUR) in stamps and static._iso(gap + HOUR) in stamps


def test_terms_json_has_sources_and_precision(tmp_path):
    cfg, _, out = built(tmp_path)
    terms = json.loads((out / "data" / "terms.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in terms] == [t.id for t in cfg.terms]
    a1 = next(t for t in terms if t["id"] == "a1")
    assert a1["family"] == "anti-trans" and a1["query"] == "a1" and a1["label"] == "A1"
    assert a1["source"] == "s" and a1["source_url"] == "u"
    assert a1["precision"] == 0.9 and a1["interval"] == [0.8, 0.95]
    assert a1["median_posts_a_day"] > 0


def test_median_is_null_without_full_days(tmp_path):
    _, _, out = built(tmp_path, with_data=False)
    terms = json.loads((out / "data" / "terms.json").read_text(encoding="utf-8"))
    assert all(t["median_posts_a_day"] is None for t in terms)


def test_provisional_flag_without_frozen_version(tmp_path):
    _, _, out = built(tmp_path)
    data = json.loads((out / "data" / "study.json").read_text(encoding="utf-8"))
    assert data["provisional"] is True and data["id"] == "us-midterms-2026"
    assert not (out / "data" / "studies").exists()


def test_frozen_version_is_published_not_provisional(tmp_path):
    cfg, st = make_config(), settings_for(tmp_path)
    conn = new_db(tmp_path, cfg)
    populate(conn, cfg)
    cdir = config_copy(tmp_path)
    s = study.get(None, cdir)
    study.freeze(study.build(conn, cfg, s, NOW, cdir), "first", tmp_path / "studies")
    study.freeze(study.build(conn, cfg, s, NOW, cdir), "second", tmp_path / "studies")
    out = static.export(conn, cfg, st, tmp_path / "site", NOW, cdir, tmp_path / "studies")
    top = json.loads((out / "data" / "study.json").read_text(encoding="utf-8"))
    assert "provisional" not in top and top["version"] == 2 and top["note"] == "second"
    for n in (1, 2):
        assert (out / "data" / "studies" / s.id / f"v{n}.json").exists()


def test_rejected_json_content(tmp_path):
    _, _, out = built(tmp_path, with_data=False)
    r = json.loads((out / "data" / "rejected.json").read_text(encoding="utf-8"))
    assert "Bot Traffic Monitor docs/NARRATIVES.md" in r["source"]
    by = {t["term"]: t for t in r["terms"]}
    assert len(r["terms"]) == 8
    g = by["groomer"]
    assert (g["posts_a_day_approx"], g["anti_trans_checked"], g["checked_n"], g["precision_pct"]) == (1630, 6, 50, 12)
    assert g["decision"] == "not added" and g["reason"]
    assert by["social contagion"]["precision_pct"] == 43
    held = by['"trans cult" / "gender cult"']
    assert held["decision"] == "held" and held["precision_pct"] == 86


def test_export_without_a_web_folder(tmp_path):
    _, _, out = built(tmp_path, web_dir=tmp_path / "no-web")
    assert (out / "data" / "terms.json").exists()
    assert not (out / "index.html").exists()


def test_export_copies_web_folder(tmp_path):
    web = tmp_path / "w"
    web.mkdir()
    (web / "index.html").write_text("<p>hi</p>", encoding="utf-8")
    _, _, out = built(tmp_path, web_dir=web)
    assert (out / "index.html").read_text(encoding="utf-8") == "<p>hi</p>"


def test_publish_no_push_exports_without_git(tmp_path, monkeypatch):
    def no_git(*a, **k):
        raise AssertionError("git was called")

    monkeypatch.setattr(static, "_git", no_git)
    monkeypatch.setattr(static, "push", no_git)
    cfg, st = make_config(), settings_for(tmp_path)
    with db.session(st.db_path) as conn:
        db.init(conn, cfg.series)
    out = tmp_path / "site"
    code = cli.main(["publish", "--no-push", "--out", str(out)], config=cfg, settings=st,
                    config_dir=config_copy(tmp_path), studies_dir=tmp_path / "studies")
    assert code == 0 and (out / "data" / "terms.json").exists()


def test_export_command(tmp_path):
    cfg, st = make_config(), settings_for(tmp_path)
    out = tmp_path / "site"
    assert cli.main(["export", "--out", str(out)], config=cfg, settings=st,
                    config_dir=config_copy(tmp_path), studies_dir=tmp_path / "studies") == 0
    assert (out / ".nojekyll").exists()


def test_push_force_pushes_one_commit_to_a_local_bare_repo(tmp_path, monkeypatch):
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "t")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "t@example.com")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    for n in (1, 2):  # two publishes: the branch is replaced, not extended
        out = tmp_path / "site"
        shutil.rmtree(out, onerror=static._clear_readonly) if out.exists() else None
        out.mkdir()
        (out / "f.txt").write_text(str(n), encoding="utf-8")
        static.push(out, str(bare))
    count = subprocess.run(["git", "--git-dir", str(bare), "rev-list", "--count", "gh-pages"],
                           capture_output=True, text=True, check=True).stdout.strip()
    assert count == "1"
