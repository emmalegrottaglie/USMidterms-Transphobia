"""Studies: fixed windows around events, built once and frozen (config/studies.toml).

A rolling chart drifts away from the event it is about as time passes, and its
comparison period moves with it. A study fixes both: the window around the event
and the reference period every index is measured against. `freeze` stores a build
as a numbered version in studies/<id>/, and the site shows the newest one.

Conventions: the window is `pre_days` before the event's UTC day to `post_days`
after it, inclusive. The reference is the `reference_days` immediately before the
window. All times are UTC. Day keys are UTC day starts (integer seconds; JSON turns
them into strings).
"""

from __future__ import annotations

import json
import statistics
import subprocess
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import analysis, db
from .config import FAMILIES, ROOT, Config

DAY = 86400
CONFIG_DIR = ROOT / "config"
STUDIES_DIR = ROOT / "studies"
PROBE_KEY = "x.probe.en.posts"


@dataclass(frozen=True)
class Study:
    id: str
    title: str
    events: tuple[str, ...]
    pre_days: int
    post_days: int
    reference_days: int
    question: str = ""


@dataclass(frozen=True)
class Event:
    short: str
    date: str
    label: str
    status: str
    source: str
    ts: int  # UTC seconds: `at` if given, else midnight UTC of `date`


def load(directory: Path = CONFIG_DIR) -> list[Study]:
    path = Path(directory) / "studies.toml"
    if not path.exists():
        return []
    items = tomllib.loads(path.read_text(encoding="utf-8")).get("study", [])
    return [Study(id=s["id"], title=s["title"], events=tuple(s["events"]), pre_days=s.get("pre_days", 14),
                  post_days=s.get("post_days", 14), reference_days=s.get("reference_days", 21),
                  question=s.get("question", "")) for s in items]


def get(study_id: str | None = None, directory: Path = CONFIG_DIR) -> Study | None:
    """The study with this id, or the newest (last) study when no id is given."""
    studies = load(directory)
    if study_id is None:
        return studies[-1] if studies else None
    return next((s for s in studies if s.id == study_id), None)


def load_events(directory: Path = CONFIG_DIR) -> list[Event]:
    path = Path(directory) / "events.toml"
    if not path.exists():
        return []
    out = []
    for e in tomllib.loads(path.read_text(encoding="utf-8")).get("event", []):
        for key in ("date", "short", "label", "status", "source"):
            if not str(e.get(key, "")).strip():
                raise ValueError(f"event {e.get('short', '?')!r} is missing {key}")
        if e.get("at"):
            ts = int(datetime.fromisoformat(str(e["at"]).replace("Z", "+00:00")).timestamp())
        else:
            ts = int(datetime.fromisoformat(str(e["date"])).replace(tzinfo=timezone.utc).timestamp())
        out.append(Event(short=e["short"], date=str(e["date"]), label=e["label"], status=e["status"],
                         source=e["source"], ts=ts))
    return out


def frame(study: Study, directory: Path = CONFIG_DIR) -> dict:
    """Window, event days and reference of a study, as UTC seconds.

    `start`/`end`: first second of the window's first day and last second of its last
    day. `reference_start`/`reference_end`: first day start of the reference and the
    start of the window (exclusive end, as analysis expects). `event_days`: start of
    the first event's day and last second of the last event's day.
    """
    events = sorted((e for e in load_events(directory) if e.short in study.events), key=lambda e: e.ts)
    missing = set(study.events) - {e.short for e in events}
    if missing:
        raise ValueError(f"study {study.id}: no event named {', '.join(sorted(missing))} in events.toml")
    first, last = events[0].ts // DAY * DAY, events[-1].ts // DAY * DAY
    start = first - study.pre_days * DAY
    return {
        "events": events,
        "start": start,
        "end": last + (study.post_days + 1) * DAY - 1,
        "event_days": (first, last + DAY - 1),
        "reference_start": start - study.reference_days * DAY,
        "reference_end": start,
    }


def data_range(study: Study, directory: Path = CONFIG_DIR) -> tuple[int, int]:
    """The hours a study reads: the reference start minus three weeks (what the
    hour-by-hour ratio compares its first hours with) up to just after the window's last
    hour (the last hour is stamped at the next midnight)."""
    f = frame(study, directory)
    return f["reference_start"] - 21 * DAY, f["end"] + 1


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def _phases(daily: dict[int, float], f: dict, study: Study) -> dict:
    """Mean index before (window start to the day before the event), during (event
    days) and after (the `post_days` days after the event). None when no day has a value."""
    first, last = f["event_days"]
    after_end = last + study.post_days * DAY
    out = {"before": [], "during": [], "after": []}
    for d, v in daily.items():
        if f["start"] <= d < first:
            out["before"].append(v)
        elif first <= d <= last:
            out["during"].append(v)
        elif last < d <= after_end:
            out["after"].append(v)
    return {k: _mean(vs) for k, vs in out.items()}


def _after(daily: dict[int, float], f: dict, study: Study) -> float | None:
    return _phases(daily, f, study)["after"]


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _placebo_share(daily: dict[int, float], f: dict, study: Study, data_start: int) -> float | None:
    """Of the days from the start of the data up to the day before the window that
    have an index value, the share at or above the after-phase mean (at or below it
    when the after mean is under 100). None when there are no such days or no after mean."""
    after = _after(daily, f, study)
    days = [v for d, v in daily.items() if data_start <= d < f["start"]]
    if after is None or not days:
        return None
    hits = sum(1 for v in days if (v >= after if after >= 100 else v <= after))
    return round(hits / len(days), 3)


def build(conn, config: Config, study: Study, now: int | None = None,
          events_dir: Path = CONFIG_DIR) -> dict:
    """Every number the study page needs.

    Time values: `window`, `reference`, event `ts` and day keys are UTC seconds (day
    keys are day starts) as ints; `as_of` (latest stored probe point) and `built_at`
    are ISO-8601 UTC strings ("...Z"); `as_of` is None with no probe data. Families
    and terms carry daily weekday indexes of their probe-normalised rate (100 = a
    normal weekday), `raw_daily` the family's raw daily post counts. Unknown values
    are None or absent, never 0.
    """
    now = now or int(time.time())
    f = frame(study, events_dir)
    lo, hi = data_range(study, events_dir)
    rs, re_ = f["reference_start"], f["reference_end"]
    by_term_metric = {(s.term_id, s.metric): s.key for s in config.series if s.term_id}

    def totals(key: str) -> dict[int, float]:
        return analysis.daily_totals(db.points(conn, key, lo, hi))

    probe_pts = db.points(conn, PROBE_KEY, lo, hi)
    probe = analysis.daily_totals(probe_pts)
    as_of = _iso(probe_pts[-1][0]) if probe_pts else None

    families: dict[str, dict] = {}
    for fam in FAMILIES:
        raw = totals(f"x.family.{fam}.en.posts")
        daily = analysis.weekday_index(analysis.rate(raw, probe), rs, re_)
        bnd = analysis.band(daily, rs, re_)
        families[fam] = {"daily": daily, "raw_daily": raw, "band": list(bnd) if bnd else None,
                         "phases": _phases(daily, f, study)}

    terms_out = []
    rates: dict[str, dict[int, float]] = {}
    for t in config.terms:
        rates[t.id] = analysis.rate(totals(by_term_metric[(t.id, "posts")]), probe)
        daily = analysis.weekday_index(rates[t.id], rs, re_)
        terms_out.append({"id": t.id, "label": t.label, "family": t.family, "precision": t.precision,
                          "precision_ci": list(t.precision_ci) if t.precision_ci else None,
                          "daily": daily, "phases": _phases(daily, f, study)})

    breadth_out: dict[str, dict] = {}
    robustness: dict[str, dict] = {}
    for fam in FAMILIES:
        members = [t for t in config.terms if t.family == fam]  # "context" terms are in neither family
        if not members:
            continue
        idx, left_out = analysis.breadth({t.id: rates[t.id] for t in members}, rs, re_)
        breadth_out[fam] = {"daily": idx, "left_out": left_out}

        # The family headline is one pooled OR query, so a term cannot be removed from it;
        # leave-one-out is done on the breadth index.
        loo = {}
        for t in members:
            rest, _ = analysis.breadth({m.id: rates[m.id] for m in members if m.id != t.id}, rs, re_)
            loo[t.id] = _after(rest, f, study)

        raw_idx = analysis.weekday_index(families[fam]["raw_daily"], rs, re_)
        sums = {}
        for metric in ("posts", "reposts"):
            per_term = [totals(by_term_metric[(t.id, metric)]) for t in members]
            common = set.intersection(*(set(p) for p in per_term))  # a day any term lacks is unknown
            pooled = {d: sum(p[d] for p in per_term) for d in common}
            sums[metric] = _after(analysis.weekday_index(pooled, rs, re_), f, study)

        robustness[fam] = {
            "leave_one_out": loo,
            "raw_vs_probe": {"raw": _after(raw_idx, f, study), "probe": families[fam]["phases"]["after"]},
            "originals_vs_reposts": sums,
            "placebo_share": _placebo_share(families[fam]["daily"], f, study, lo),
        }

    return {
        "id": study.id,
        "title": study.title,
        "question": study.question,
        "window": {"start": f["start"], "end": f["end"], "pre_days": study.pre_days, "post_days": study.post_days},
        "event_days": {"start": f["event_days"][0], "end": f["event_days"][1]},
        "reference": {"start": rs, "end": re_ - DAY, "days": study.reference_days},
        "events": [{"short": e.short, "date": e.date, "label": e.label, "status": e.status,
                    "source": e.source, "ts": e.ts} for e in f["events"]],
        "complete": now > f["end"],
        "as_of": as_of,
        "built_at": _iso(now),
        "families": families,
        "breadth": breadth_out,
        "terms": terms_out,
        "robustness": robustness,
    }


def versions(study_id: str, directory: Path | None = None) -> list[Path]:
    folder = (directory or STUDIES_DIR) / study_id
    return sorted(folder.glob("v*.json"), key=lambda p: int(p.stem[1:])) if folder.exists() else []


def latest(study_id: str, directory: Path | None = None) -> dict | None:
    """The newest frozen version of a study, or None."""
    found = versions(study_id, directory)
    return json.loads(found[-1].read_text(encoding="utf-8")) if found else None


def _commit() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        return r.stdout.strip() or None
    except OSError:
        return None


def freeze(built: dict, note: str, directory: Path | None = None) -> Path:
    """Store a build as the study's next version (highest existing + 1). A study whose
    window is still open cannot be frozen: its after-period is not complete."""
    if not built["complete"]:
        raise ValueError(f"study {built['id']} is still open: its window ends after the build time")
    folder = directory or STUDIES_DIR
    existing = versions(built["id"], folder)
    n = int(existing[-1].stem[1:]) + 1 if existing else 1
    path = folder / built["id"] / f"v{n}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**built, "version": n, "note": note, "commit": _commit()},
                               separators=(",", ":")), encoding="utf-8")
    return path
