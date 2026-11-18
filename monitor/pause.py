"""Pausing collection between events, and resuming it for the next one.

While paused, `collect` does nothing (no request, no budget). The pause is a small JSON
file next to the database (data/pause.json); its absence means collecting.

Resuming for an event appends the event to config/events.toml and opens a study around it
in config/studies.toml. After a collection pass, `close_if_done` freezes the newest study
once its window is over and its data is in, then pauses until the next event. "Its data is
in" means every family has a normal range and a before and an after mean, and both the
probe and every family have a total for the window's last day; otherwise nothing is
frozen and the reason is logged.
"""

from __future__ import annotations

import json
import logging
import time
import tomllib
from pathlib import Path

from . import analysis, db
from . import study as studies
from .config import FAMILIES, Config, Settings, slug

log = logging.getLogger(__name__)
DAY = 86400
FREEZE_NOTE = ("Frozen automatically: the window had ended, every family had a normal range and "
               "before and after means, and the probe and every family had the window's last day.")


def path(settings: Settings) -> Path:
    return settings.db_path.parent / "pause.json"


def state(settings: Settings) -> dict | None:
    """The pause record ({"since", "reason"}) or None when collecting. A missing file means
    collecting; a file that exists but cannot be read or parsed, or is not a record with a
    reason, counts as paused (fail closed), so a damaged file never restarts paid collection."""
    p = path(settings)
    if not p.exists():
        return None
    try:
        record = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(record, dict) and str(record.get("reason", "")).strip():
            return record
        why = "it is not a record with a reason"
    except (OSError, ValueError) as e:
        why = f"{type(e).__name__}"
    return {"since": 0, "reason": f"the pause file {p} is unreadable ({why}); fix or delete it to resume"}


def pause(settings: Settings, reason: str, now: int | None = None) -> dict:
    record = {"since": now or int(time.time()), "reason": reason}
    path(settings).parent.mkdir(parents=True, exist_ok=True)
    path(settings).write_text(json.dumps(record), encoding="utf-8")
    log.info("collection paused: %s", reason)
    return record


def _toml_str(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)  # TOML basic strings use the same escapes


def question_for(label: str) -> str:
    return f"Did explicit anti-trans term volume on Twitter change before and after: {label}?"


def open_study(event: dict, directory: Path = studies.CONFIG_DIR) -> str:
    """Append an event (date, short, label, status, source; `at` optional) to events.toml and
    a study around it to studies.toml. Returns the study id. Every event needs a source and a
    status. A `short` already used gets the date appended, since studies name events by `short`."""
    for key in ("date", "short", "label", "status", "source"):
        if not event.get(key):
            raise ValueError(f"an event needs a {key}")
    directory = Path(directory)
    events_path = directory / "events.toml"
    existing = tomllib.loads(events_path.read_text(encoding="utf-8")).get("event", []) if events_path.exists() else []
    short = event["short"].upper()
    study_id = f"{slug(short)}-{event['date']}"
    if studies.get(study_id, directory):
        return study_id  # opened already, e.g. a resume that was run twice
    if any(e.get("short") == short for e in existing):
        short = f"{short} {event['date'][5:]}"
    event = {**event, "short": short}
    lines = ["", "[[event]]"] + [f"{k} = {_toml_str(str(event[k]))}"
                                 for k in ("date", "short", "at", "label", "status", "source") if event.get(k)]
    with events_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with (directory / "studies.toml").open("a", encoding="utf-8") as f:
        f.write("\n".join(["", "[[study]]", f"id = {_toml_str(study_id)}", f"title = {_toml_str(event['label'])}",
                           f"events = [{_toml_str(short)}]", "pre_days = 14", "post_days = 14",
                           "reference_days = 21", f"question = {_toml_str(question_for(event['label']))}"]) + "\n")
    return study_id


def resume(settings: Settings, reason: str, event: dict | None = None,
           config_dir: Path = studies.CONFIG_DIR) -> str | None:
    """Clear the pause and log why. With an `event`, first open a study around it and return its id."""
    opened = open_study(event, config_dir) if event else None
    path(settings).unlink(missing_ok=True)
    log.info("collection resumed: %s", reason)
    return opened


def incomplete(conn, config: Config, s: studies.Study, built: dict,
               config_dir: Path = studies.CONFIG_DIR) -> list[str]:
    """Why a built study is not ready to freeze; empty when it is. Every family with a series
    needs a normal range (`band`), a before and an after mean, and a day total for the window's
    last day; the probe needs a day total for that day too."""
    f = studies.frame(s, config_dir)
    last_day = f["end"] + 1 - DAY
    have = [fam for fam in FAMILIES if any(sp.key == f"x.family.{fam}.en.posts" for sp in config.series)]
    if not have:
        return ["no family series to check the window against"]
    why = []
    for fam in have:
        info = built["families"][fam]
        if info["band"] is None:
            why.append(f"{fam} has no normal range (fewer than {analysis.MIN_REFERENCE_DAYS} reference days)")
        for phase in ("before", "after"):
            if info["phases"][phase] is None:
                why.append(f"{fam} has no {phase} mean")
        if last_day not in info["raw_daily"]:
            why.append(f"{fam} has no total for the window's last day")
    lo, hi = studies.data_range(s, config_dir)
    if last_day not in analysis.daily_totals(db.points(conn, studies.PROBE_KEY, lo, hi)):
        why.append("the probe has no total for the window's last day")
    return why


def close_if_done(conn, config: Config, now: int | None = None, settings: Settings | None = None,
                  config_dir: Path = studies.CONFIG_DIR, studies_dir: Path | None = None) -> dict | None:
    """Freeze the newest study once `now` is at least a day past its window end and its data is
    complete (see `incomplete`), then pause (when `settings` is given). Returns the frozen build
    with its note, or None; when the window is over but the data is not complete, the reasons are
    logged as a warning and nothing is frozen or paused. A study with a frozen version is never
    frozen again."""
    now = now or int(time.time())
    s = studies.get(directory=config_dir)
    if s is None or studies.latest(s.id, studies_dir):
        return None
    f = studies.frame(s, config_dir)
    if now < f["end"] + 1 + DAY:
        return None
    built = studies.build(conn, config, s, now, config_dir)
    why = incomplete(conn, config, s, built, config_dir)
    if why:
        log.warning("study %s not frozen: %s", s.id, "; ".join(why))
        return None
    studies.freeze(built, FREEZE_NOTE, studies_dir)
    if settings is not None:
        pause(settings, f"Study complete: {s.title}. Waiting for the next event.", now)
    return {**built, "note": FREEZE_NOTE}
