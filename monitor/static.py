"""Static copy of the site and its data, for free hosting (GitHub Pages).

`export` writes the page (web/*) plus every download as plain files, so the site
needs no server. `push` publishes that folder to a `gh-pages` branch as a single
fresh commit each time, so published data never piles up in git history.

Only aggregate counts and timestamps are written: no post text, usernames or
account IDs exist in the database, so none can reach the export.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import sqlite3
import statistics
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import ROOT, analysis, db, study
from .config import Config, Settings

log = logging.getLogger(__name__)

SOURCE_NOTE = "Precision checks, 16 November 2026, Bot Traffic Monitor docs/NARRATIVES.md"
THRESHOLD_REASON = "Hand-checked precision is below the 70% threshold, so the term is not tracked."

# Terms screened and not added (precision run of 16 November 2026), plus one held term.
REJECTED = [
    ("gender ideology", 254, 32, 50, "pushback"),
    ("rare slurs and memes, pooled", 80, 24, 50, '"erasing women" in other contexts'),
    ("trans shooter", 39, 24, 50, "pushback, statistics"),
    ("social contagion", 97, 20, 46, "anorexia, ADHD and other topics"),
    ("gender critical", 159, 16, 50, "criticism of the movement"),
    ("groomer", 1630, 6, 50, "pet grooming, abuse survivors"),
    ("super straight", 105, 1, 45, "betting-slip spam"),
]
HELD = ('"trans cult" / "gender cult"', 74, 43, 50, "pushback")


def _row(term: str, per_day: int, k: int, n: int, other: str, decision: str, reason: str) -> dict:
    return {"term": term, "posts_a_day_approx": per_day, "anti_trans_checked": k, "checked_n": n,
            "precision_pct": round(100 * k / n), "other_uses": other, "decision": decision, "reason": reason}


def rejected() -> dict:
    rows = [_row(t, p, k, n, o, "not added", THRESHOLD_REASON) for t, p, k, n, o in REJECTED]
    t, p, k, n, o = HELD
    rows.append(_row(t, p, k, n, o, "held",
                     "Precision is above the threshold, but no source has been checked for the term yet."))
    return {"source": SOURCE_NOTE, "run": "2026-11-16", "terms": rows}


def _json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clear_readonly(func, path, _exc) -> None:
    # Git writes object files read-only; on Windows rmtree cannot delete them until cleared.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear_readonly)
    else:
        shutil.rmtree(path, onerror=_clear_readonly)


MARKER = ".monitor-export"
PROTECTED = ("web", "config", "monitor", "tests", "studies", "terminal-design-system", "docs", ".git")


def _inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _check_out(out: Path, settings: Settings) -> None:
    """Refuse an output folder that would delete source, data or git history."""
    target, root = out.resolve(), ROOT.resolve()
    db_dir = settings.db_path.resolve().parent
    if _inside(root, target):
        raise ValueError(f"refusing to export to {out}: it is or contains the project folder")
    for name in PROTECTED:
        if _inside(target, root / name):
            raise ValueError(f"refusing to export to {out}: it is inside the project's {name}/ folder")
    if _inside(target, db_dir) or _inside(db_dir, target):
        raise ValueError(f"refusing to export to {out}: it is or overlaps the database folder")
    if target.exists():
        if not target.is_dir():
            raise ValueError(f"refusing to export to {out}: it is a file")
        if any(target.iterdir()) and not (target / MARKER).exists():
            raise ValueError(f"refusing to export to {out}: it is not empty and was not made by a previous "
                             f"export (no {MARKER} file). Choose an empty or new folder.")


def _median_daily(conn, key: str, lo: int, hi: int) -> float | None:
    days = analysis.daily_totals(db.points(conn, key, lo, hi))
    return round(statistics.median(days.values()), 2) if days else None


def export(conn: sqlite3.Connection, config: Config, settings: Settings, out: Path, now: int | None = None,
           config_dir: Path | None = None, studies_dir: Path | None = None,
           web_dir: Path | None = None) -> Path:
    now = now or int(time.time())
    cdir = config_dir or study.CONFIG_DIR
    web = web_dir or ROOT / "web"
    _check_out(out, settings)
    if out.exists():
        _rmtree(out)
    if web.is_dir():
        shutil.copytree(web, out)
    else:
        out.mkdir(parents=True)
    (out / "design").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "terminal-design-system" / "terminal.css", out / "design" / "terminal.css")
    shutil.copy2(ROOT / "CITATION.cff", out / "CITATION.cff")  # the page links to this copy
    (out / MARKER).write_text("made by `python -m monitor export`; safe to replace", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is on GitHub Pages
    data = out / "data"
    data.mkdir(exist_ok=True)

    chosen = study.get(None, cdir)
    frame = study.frame(chosen, cdir) if chosen else None

    # Study: newest frozen version, else a provisional build.
    if chosen:
        frozen = study.latest(chosen.id, studies_dir)
        _json(data / "study.json", frozen if frozen else {**study.build(conn, config, chosen, now, cdir),
                                                          "provisional": True})
        for path in study.versions(chosen.id, studies_dir):
            target = data / "studies" / chosen.id / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

    # Terms, with the median posts a day over the study window (None when no full days).
    posts_key = {s.term_id: s.key for s in config.series if s.term_id and s.metric == "posts"}
    terms = []
    for t in config.terms:
        median = _median_daily(conn, posts_key[t.id], frame["start"], frame["end"] + 1) if frame else None
        terms.append({"id": t.id, "label": t.label, "family": t.family, "query": t.query,
                      "source": t.source, "source_url": t.source_url, "precision": t.precision,
                      "precision_n": t.precision_n,
                      "interval": list(t.precision_ci) if t.precision_ci else None,
                      "added": t.added, "median_posts_a_day": median})
    _json(data / "terms.json", terms)
    _json(data / "rejected.json", rejected())

    # Series: hourly CSV and JSON per key, daily CSV for all.
    daily_rows = []
    folder = data / "series"
    folder.mkdir(parents=True, exist_ok=True)
    for s in config.series:
        pts = db.points(conn, s.key, 0, now)
        with (folder / f"{s.key}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["hour_end_utc", "value"])
            w.writerows([_iso(t), v] for t, v in pts)
        _json(folder / f"{s.key}.json", {"key": s.key, "label": s.label, "unit": s.unit, "family": s.family,
                                         "points": [[_iso(t), v] for t, v in pts]})
        daily_rows += [[_iso(d)[:10], s.key, v] for d, v in sorted(analysis.daily_totals(pts).items())]
    with (data / "daily.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["day_utc", "key", "value"])
        w.writerows(daily_rows)

    log.info("static site exported to %s", out)
    return out


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def default_remote() -> str:
    try:
        return _git(["remote", "get-url", "origin"], ROOT)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise SystemExit("No git remote 'origin' in the project. Push the repo to GitHub first.")


def push(out: Path, remote: str, branch: str = "gh-pages") -> None:
    """Force-push `out` as a single commit, replacing the branch each time."""
    _git(["init", "-q"], out)
    _git(["checkout", "-q", "-B", branch], out)
    _git(["add", "-A"], out)
    _git(["commit", "-q", "-m", f"Publish data {_iso(int(time.time()))}"], out)
    _git(["push", "-q", "--force", remote, f"{branch}:{branch}"], out)
    log.info("pushed %s to %s (%s)", out, remote, branch)
