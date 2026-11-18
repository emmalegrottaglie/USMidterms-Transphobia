"""Command line: python -m monitor {collect,backfill,import-tracker,study,pause,resume,close-if-done}

`export` and `publish` are implemented in monitor/static.py.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import db, importer, pause, static, study
from .collectors import x
from .config import Config, Settings, load_config

DAY = 86400


def _date(text: str) -> int:
    """UTC midnight of a strict YYYY-MM-DD date; time parts and offsets are rejected."""
    if len(text) != 10:
        raise ValueError(text)
    d = date.fromisoformat(text)
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _require(parser, **fields: str) -> None:
    for name, value in fields.items():
        if not value.strip():
            parser.error(f"{name} must not be empty")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="monitor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("collect", help="one live collection pass (does nothing while paused)")

    p = sub.add_parser("backfill", help="load full-archive history from Twitter")
    p.add_argument("--from", dest="start", required=True, help="UTC date, YYYY-MM-DD")
    p.add_argument("--to", dest="end", help="UTC date, YYYY-MM-DD, inclusive (default: now)")
    p.add_argument("--missing-before", action="store_true",
                   help="only the hours before each keyword's earliest stored hour")

    p = sub.add_parser("import-tracker", help="copy points from the bot tracker's database")
    p.add_argument("--db", required=True, type=Path)

    p = sub.add_parser("study", help="build a study (config/studies.toml)")
    p.add_argument("action", choices=["build"])
    p.add_argument("id", nargs="?", help="study id (default: the newest study)")
    p.add_argument("--freeze", action="store_true", help="store the build as the study's next version")
    p.add_argument("--note", default="", help="what this version is or changes (required with --freeze)")

    p = sub.add_parser("export", help="write the static site and data downloads to a folder")
    p.add_argument("--out", required=True, type=Path)

    p = sub.add_parser("publish", help="export, then force-push the folder to the gh-pages branch")
    p.add_argument("--no-push", action="store_true", help="export only; do not touch git")
    p.add_argument("--out", type=Path, help="folder to export to (default: a temporary folder)")

    p = sub.add_parser("pause", help="stop collecting until the next event")
    p.add_argument("--reason", required=True)
    p = sub.add_parser("resume", help="collect again, and open a study around a new event")
    p.add_argument("--reason", required=True)
    p.add_argument("--event-date", required=True, help="UTC date, YYYY-MM-DD")
    p.add_argument("--event-short", required=True, help="chart label, e.g. ELECTION")
    p.add_argument("--event-label", required=True, help="one line describing the event")
    p.add_argument("--event-source", required=True, help="who reported it, with date and URL")
    p.add_argument("--event-status", default="reported", choices=["reported", "confirmed"])

    sub.add_parser("close-if-done", help="freeze the newest study once its data is in, then pause")
    return parser


def main(argv: list[str] | None = None, config: Config | None = None, settings: Settings | None = None,
         config_dir: Path | None = None, studies_dir: Path | None = None) -> int:
    """`config`, `settings`, `config_dir` and `studies_dir` are injectable for tests."""
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or Settings.from_env()
    cdir = config_dir or study.CONFIG_DIR
    config = config or load_config(cdir)
    now = int(time.time())

    if args.cmd == "collect":
        record = pause.state(settings)
        if record:
            print(f"collection is paused: {record['reason']}")
            return 0
        asyncio.run(x.run(config, settings, now))
        try:
            with db.session(settings.db_path) as conn:
                done = pause.close_if_done(conn, config, now, settings, cdir, studies_dir)
        except ValueError as e:
            print(f"could not check the study (the live pass is stored): {e}", file=sys.stderr)
            return 0
        if done:
            print(f"froze study {done['id']} and paused collection")
        return 0

    if args.cmd == "backfill":
        try:
            start = _date(args.start)
            end = _date(args.end) + DAY if args.end else None
        except ValueError:
            parser.error("--from and --to must be dates like 2026-11-03 (UTC, no time or offset)")
        if end is not None and end <= start:  # --to is a whole day, so equal dates are fine; earlier is not
            parser.error("--to must not be before --from")
        try:
            results = asyncio.run(x.backfill(config, settings, start, end, args.missing_before))
        except RuntimeError as e:
            print(f"backfill not run: {e}", file=sys.stderr)
            return 1
        errors, total = [], 0
        with db.session(settings.db_path) as conn:
            db.init(conn, config.series)
            for query, result in results.items():
                errors += result.errors
                for spec in config.series:
                    if spec.query == query and spec.key in result.points:
                        n = db.replace_hours(conn, spec.key, result.points[spec.key])
                        total += n
                        print(f"{spec.key}: {n} points")
            db.record_run(conn, x.PLATFORM, bool(total), total, "; ".join(errors)[:2000] or None)
        for e in errors:
            print(f"error: {e}")
        print(f"{total} points written, {len(errors)} errors")
        return 0 if total or not errors else 1

    if args.cmd == "import-tracker":
        if not args.db.exists():
            print(f"tracker database not found: {args.db}", file=sys.stderr)
            return 1
        with db.session(settings.db_path) as conn:
            db.init(conn, config.series)
            copied = importer.import_tracker(conn, config, args.db)
        for key, n in copied.items():
            print(f"{key}: {n} points")
        print(f"{len(copied)} series imported")
        return 0

    if args.cmd == "study":
        if args.freeze and not args.note.strip():
            parser.error("--freeze needs --note saying what this version is or changes")
        chosen = study.get(args.id, cdir)
        if chosen is None:
            parser.error(f"no study {args.id!r} in studies.toml" if args.id else "no study in studies.toml")
        try:
            with db.session(settings.db_path) as conn:
                db.init(conn, config.series)
                built = study.build(conn, config, chosen, now, cdir)
        except ValueError as e:
            print(f"cannot build study {chosen.id}: {e}", file=sys.stderr)
            return 1
        print(f"{chosen.id}: {'complete' if built['complete'] else 'window still open'}")
        for fam, info in built["families"].items():
            ph = info["phases"]
            print(f"  {fam}: before {ph['before']}  during {ph['during']}  after {ph['after']}")
        if args.freeze:
            try:
                print(f"frozen: {study.freeze(built, args.note, studies_dir)}")
            except ValueError as e:
                print(f"not frozen: {e}", file=sys.stderr)
                return 1
        return 0

    if args.cmd in ("export", "publish"):
        temp = args.cmd == "publish" and not args.out
        out = Path(tempfile.mkdtemp(prefix="monitor-site-")) if temp else args.out
        try:
            with db.session(settings.db_path) as conn:
                db.init(conn, config.series)
                static.export(conn, config, settings, out, now, cdir, studies_dir)
            print(f"exported to {out}")
            if args.cmd == "publish" and not args.no_push:
                static.push(out, static.default_remote())
                print("pushed to gh-pages")
        except (ValueError, subprocess.CalledProcessError) as e:
            detail = (e.stderr or "").strip() if isinstance(e, subprocess.CalledProcessError) else ""
            print(f"{args.cmd} failed: {e}", file=sys.stderr)
            if detail:
                print(detail, file=sys.stderr)
            if temp:
                print(f"the exported folder was kept at {out}", file=sys.stderr)
            return 1
        if temp and not args.no_push:
            static._rmtree(out)
        return 0

    if args.cmd == "pause":
        _require(parser, **{"--reason": args.reason})
        pause.pause(settings, args.reason, now)
        print(f"paused: {args.reason}")
        return 0

    if args.cmd == "resume":
        _require(parser, **{"--reason": args.reason, "--event-short": args.event_short,
                            "--event-label": args.event_label, "--event-source": args.event_source})
        try:
            _date(args.event_date)
        except ValueError:
            parser.error("--event-date must be a date like 2026-11-03 (UTC, no time or offset)")
        event = {"date": args.event_date, "short": args.event_short, "label": args.event_label,
                 "source": args.event_source, "status": args.event_status}
        opened = pause.resume(settings, args.reason, event, cdir)
        print(f"resumed; opened study {opened}")
        return 0

    if args.cmd == "close-if-done":
        try:
            with db.session(settings.db_path) as conn:
                db.init(conn, config.series)
                done = pause.close_if_done(conn, config, now, settings, cdir, studies_dir)
        except ValueError as e:
            print(f"cannot check the study: {e}", file=sys.stderr)
            return 1
        print(f"froze study {done['id']} and paused collection" if done else "nothing to freeze")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
