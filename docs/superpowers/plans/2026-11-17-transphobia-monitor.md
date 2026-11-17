# Anti-trans Rhetoric Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone repo and static site that measures explicit anti-trans term volume on Twitter around events, starting with the US midterms of 3 November 2026.

**Architecture:** A Python package `monitor/` (trimmed copies of the bot tracker's config, storage, Twitter counts collector and study code) writes hourly counts to SQLite, builds frozen study JSON, and exports a static site (`web/` + JSON + CSV) that is pushed to the repo's `gh-pages` branch. The only link to the bot tracker is one shared Twitter request counter file.

**Tech Stack:** Python 3.11+, httpx, sqlite3 (stdlib), pytest; plain HTML/CSS/JS with inline SVG charts; the terminal design system (`terminal.css`).

**Spec:** `docs/superpowers/specs/2026-11-17-transphobia-monitor-design.md`

## Global Constraints

- Store timestamps and aggregate counts only; never store or log usernames, account IDs or post text.
- A failed or empty fetch records an error, never a zero; an hour where the probe is zero is a gap (no point).
- Unknown values render as `—`; every number on the site is labelled; border-radius 0.
- User-facing text says "Twitter", never "X" (code may keep `api.x.com` URLs).
- Every term needs `source` and `source_url`; every event needs `source` and `status`.
- Only terms with hand-checked precision ≥ 0.70 are tracked in a family; `context` terms are shown but never in a family.
- Shared daily cap: `X_MAX_REQUESTS_PER_DAY` (default 150) across both projects, via the file named by `TWITTER_USAGE_FILE`.
- Costs: recent counts $0.005/request, full-archive counts $0.010/request.
- Palette: Broadcast 8s (`data-palette="term-navy"`), dark and light (`data-mode="light"`), following `terminal-design-system/DESIGN_GUIDE.md` §11.
- Runtime dependencies: httpx only (pytest for dev).

## Review Focus

1. **Twitter outage hours** (probe returns 0): hour stored as no point for every series in that pass; a day with fewer than 20 hours gets no daily value and the chart shows `—`, not a dip. → test in Task 5 and Task 6.
2. **A family query too long** after someone adds a term (over 1,024 characters with filters): config load raises with the family name and length, never truncates. → test in Task 2.
3. **Both projects collecting at the same moment**: combined requests never exceed the cap; an unreadable usage file counts as cap reached, not as zero used. → test in Task 4.
4. **A term with no reference-period variation** (all-zero or constant rate): left out of the breadth index with a note, no division by zero. → test in Task 6.
5. **Running `import-tracker` twice**: no duplicate points, same totals. → test in Task 3.

---

### Task 1: Repository scaffold and design system

**Files:**
- Create: `pyproject.toml`, `README.md`, `CLAUDE.md`, `.gitignore`, `monitor/__init__.py`, `tests/test_scaffold.py`
- Create: `terminal-design-system/` (copy of the canonical folder)
- Modify (bot tracker): `C:\Russian bot tracker\terminal-design-system\AGENTS.md` (product table), `C:\Russian bot tracker\terminal-design-system\sync_copies.py` (add `C:\USMidterms-Transphobia\terminal-design-system` as a copy)

**Interfaces:**
- Produces: package `monitor`, `monitor.ROOT: Path` (repo root), test layout `tests/`.

- [ ] **Step 1: Write the failing test** `tests/test_scaffold.py::test_design_system_is_a_synced_copy`: assert `(ROOT / "terminal-design-system" / "terminal.css").read_bytes()` equals the bot tracker's canonical `terminal.css` bytes (skip if `C:\Russian bot tracker` is absent).
- [ ] **Step 2: Run** `python -m pytest tests/test_scaffold.py -v` → FAIL (module or file missing).
- [ ] **Step 3: Create the scaffold.** `pyproject.toml`: name `antitrans-rhetoric-monitor`, `requires-python = ">=3.11"`, dependencies `["httpx>=0.27"]`, dev `["pytest>=8"]`, packages `["monitor", "monitor.collectors"]`, pytest testpaths `["tests"]`. `.gitignore`: `data/`, `site/`, `.env`, `.venv/`, `__pycache__/`, `.superpowers/`. `CLAUDE.md`: the Global Constraints above plus the bot tracker's data rules and the named-public-figures exception, verbatim from the spec's Constraints. Add this repo to the bot tracker's AGENTS.md table (role: "Copy. The site serves its own copy of `terminal.css`.") and to `sync_copies.py`, then run `python "C:/Russian bot tracker/terminal-design-system/sync_copies.py"`.
- [ ] **Step 4: Run** `python -m pytest -v` → PASS.
- [ ] **Step 5: Commit** in both repos (`Scaffold the monitor and add it as a design-system copy`; bot tracker: `Add the transphobia monitor as a design-system copy`).

### Task 2: Terms, families and settings

**Files:**
- Create: `monitor/config.py`, `config/terms.toml`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `Settings` (frozen dataclass): `db_path: Path` (env `MONITOR_DB`, default `data/monitor.db`), `x_bearer_token: str` (`X_BEARER_TOKEN`), `x_max_requests_per_day: int` (`X_MAX_REQUESTS_PER_DAY`, 150), `usage_file: Path` (`TWITTER_USAGE_FILE`, default `data/x_usage.json`), `public_url: str` (`MONITOR_PUBLIC_URL`); `Settings.from_env()`; `load_dotenv(path=ROOT/".env")` copied from the bot tracker.
  - `Term` (frozen): `id, label, family ("anti-trans"|"framing"|"context"), query, source, source_url, precision: float|None, precision_n: int|None, precision_ci: tuple[float,float]|None, added: str`.
  - `SeriesSpec` (frozen): `key, label, unit, family, term_id|None, metric ("posts"|"reposts"|"replies"|"repost-share"), query, endpoint ("recent"|"all")`.
  - `Config`: `terms: tuple[Term,...]`, `series: tuple[SeriesSpec,...]`, `probe_query: str`, `family_queries: dict[str,str]`.
  - `load_config(directory: Path = ROOT/"config") -> Config`; `slug(text) -> str` copied from the bot tracker.
  - Keys: term series `x.{slug(query)}.en.{metric}` (identical to the bot tracker's keys, so imported history lines up); family `x.family.{family}.en.posts`; probe `x.probe.en.posts`.
- `config/terms.toml`: `[probe] query = "(thing OR any OR tell)"`; one `[[term]]` per term in the spec's "Terms at launch" minus the single-sex phrases, plus `trans-youth` as `context`. Query, label, source, source_url, precision, n and interval copied from the bot tracker's `config/sources.toml` and `docs/research/precision-2026-11-16.json`; "trans youth" has no precision (topic term).

- [ ] **Step 1: Write the failing tests**
  - `test_terms_and_families`: 8 anti-trans, 8 framing, 1 context; every term has non-empty `source` and `source_url`; every family term has `precision >= 0.70`.
  - `test_keys_match_bot_tracker`: the troon posts key is `x.troon-or-troons.en.posts`.
  - `test_family_query_is_or_of_members`: `family_queries["anti-trans"]` contains each anti-trans query and no framing query; context terms are in no family.
  - `test_family_and_probe_use_full_archive`: family and probe specs have `endpoint == "all"` and metric `posts` only; term specs have `endpoint == "recent"` and metrics `posts, reposts, replies, repost-share`.
  - `test_family_query_too_long_raises` (Review Focus 2): a temp terms.toml whose family query plus `" lang:en -is:retweet"` exceeds 1,024 characters → `ValueError` whose message names the family and the length.
  - `test_term_below_threshold_rejected`: a family term with precision 0.69 → `ValueError`.
- [ ] **Step 2: Run** `python -m pytest tests/test_config.py -v` → FAIL.
- [ ] **Step 3: Implement** `monitor/config.py` and `config/terms.toml` as above (TOML via `tomllib`).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the term list, families and settings`.

### Task 3: Storage and import from the bot tracker

**Files:**
- Create: `monitor/db.py`, `monitor/importer.py`, `tests/test_db.py`, `tests/test_importer.py`

**Interfaces:**
- Consumes: `SeriesSpec`, `Config`.
- Produces (copied from the bot tracker's `tracker/db.py`, minus alerts): `session(path)`, `init(conn, specs)`, `upsert_points(conn, key, points) -> int`, `replace_hours(conn, key, points) -> int`, `points(conn, key, start, end) -> list[tuple[int,float]]`, `point_range(conn, key) -> tuple[int,int]|None`, `record_run(conn, platform, ok, points, error=None)`. Schema: `series(key, label, unit, family, term_id, metric)`, `points(key, ts, value)` (ts = end of the hour, UTC), `runs`.
- Produces: `import_tracker(conn, config, tracker_db: Path) -> dict[str, int]` (points copied per key, for every key in `config.series` that exists in the tracker DB).

- [ ] **Step 1: Write the failing tests** `test_import_copies_matching_keys_only` (a temp tracker DB with one matching and one unrelated key → only the matching key's points arrive, values equal) and `test_import_is_idempotent` (Review Focus 5: running twice leaves the same point count and sum).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with `upsert_points`; open the tracker DB read-only (`file:...?mode=ro`, `uri=True`).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add storage and the import from the bot tracker`.

### Task 4: Shared Twitter request counter (both repos)

**Files:**
- Create: `monitor/budget.py`, `tests/test_budget.py`
- Modify (bot tracker): `tracker/collectors/x.py` (`_Budget` and its construction at line 153), `tests/test_x.py` (or the existing Twitter test file)

**Interfaces:**
- Produces: `Budget(path: Path, cap: int)` with `take() -> None` raising `BudgetExhausted` (monitor) / `SourceSkipped` (bot tracker) when the UTC day's count is at the cap. File format unchanged: `{"YYYY-MM-DD": n}`.
- Locking: an exclusive lock file `<path>.lock` created with `os.open(O_CREAT|O_EXCL)`, retried every 0.1 s for up to 10 s, treated as stale after 30 s; read, increment, write via a temp file and `os.replace`, then remove the lock.
- Bot tracker: `_Budget(Path(os.environ.get("TWITTER_USAGE_FILE") or settings.db_path.parent / "x_usage.json"), cap)` with the same locking.

- [ ] **Step 1: Write the failing tests** (in both repos)
  - `test_take_counts_per_utc_day_and_stops_at_cap`: cap 2 → two takes succeed, the third raises.
  - `test_two_processes_never_exceed_cap` (Review Focus 3): 2 `multiprocessing` workers each calling `take()` 10 times against cap 12 → exactly 12 succeed in total, file says 12.
  - `test_unreadable_file_counts_as_cap_reached` (Review Focus 3): file containing `not json` → `take()` raises and the file is left unchanged.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** as above in both repos.
- [ ] **Step 4: Run both suites** (`python -m pytest` in each repo) → PASS.
- [ ] **Step 5: Commit** in both repos (`Share one Twitter request counter between projects`). Emma sets `TWITTER_USAGE_FILE=C:\Russian bot tracker\data\x_usage.json` in both `.env` files herself.

### Task 5: Twitter counts collector

**Files:**
- Create: `monitor/collectors/__init__.py`, `monitor/collectors/x.py`, `tests/test_x.py`

**Interfaces:**
- Consumes: `Budget`, `SeriesSpec`, `db.replace_hours`, `db.record_run`.
- Produces:
  - `async collect(client, config, settings, now: int, start: int|None = None, end: int|None = None) -> Result` (`Result(points: dict[str, list[tuple[int,float]]], errors: list[str])`). `start is None` → live pass over the recent endpoint's last 7 days for term series; family and probe always use the full-archive endpoint. Per term: 3 requests (originals `-is:retweet`, reposts `is:retweet`, replies `is:reply`), all with `lang:en`; per family and the probe: 1 request (originals). No per-minute request.
  - `metrics(orig, rt, reply, gaps) -> dict[str, list[tuple[int,float]]]`: the bot tracker's `metrics` minus the burst part.
  - `async backfill(config, settings, start: int, end: int|None = None, missing_before: bool = False) -> dict[str, Result]`: with `missing_before`, each keyword's window ends at its earliest stored point (skipped if that is at or before `start`).
  - Gap rule copied from the bot tracker: probe hours with 0 are gaps; no series gets a point for a gap hour.
  - `async run(config, settings, now) -> None`: live pass, writes with `replace_hours`, records a run. (The pause check lives in the `collect` command, Task 8.)

- [ ] **Step 1: Write the failing tests** with `httpx.MockTransport` serving canned counts responses:
  - `test_three_requests_per_term_one_per_family_and_probe`: a config with 2 terms in 1 family → exactly 2×3 + 1 + 1 = 8 requests; family and probe hit `/2/tweets/counts/all`.
  - `test_gap_hours_get_no_points` (Review Focus 1): probe 0 at one hour → no series has a point stamped at that hour's end; neighbouring hours present.
  - `test_failed_request_records_error_not_zero`: a 503 for one term → that term has no points and `errors` names it; other terms still written.
  - `test_backfill_missing_before_stops_at_earliest_point`: a term with stored points from 17 Sep → its request window ends at 17 Sep 00:00 UTC; a series with nothing stored gets the full window.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** by trimming the bot tracker's `tracker/collectors/x.py` (keep `buckets`, `_iso`, `_ts`, pagination via `next_token`, `recent_start`; use `Budget` from Task 4).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the Twitter counts collector`.

### Task 6: Index, composite and breadth

**Files:**
- Create: `monitor/analysis.py`, `tests/test_analysis.py`

**Interfaces:**
- Consumes: `db.points`.
- Produces (all values `None` where unknown):
  - `daily_totals(points, min_hours=20) -> dict[int, float]` (UTC day start → sum; days with fewer than 20 hourly points are absent).
  - `rate(series: dict[int,float], probe: dict[int,float]) -> dict[int,float]` (day → series/probe, only where both exist and probe > 0).
  - `weekday_index(daily: dict[int,float], ref_start: int, ref_end: int) -> dict[int,float]`: each day ÷ the mean of the same weekday's days in the reference period × 100; absent when the reference has no day of that weekday.
  - `band(index: dict[int,float], ref_start, ref_end) -> tuple[float,float]|None`: 5th and 95th percentiles of the reference days' index (the bot tracker's `_quantile`); `None` with fewer than 14 reference days.
  - `hourly_ratio(hours: dict[int,float]) -> dict[int,float]`: the bot tracker's `_ratios` (same weekday-hour 1 to 3 weeks earlier, 2 of 3 needed), × 100.
  - `breadth(term_rates: dict[str, dict[int,float]], ref_start, ref_end) -> tuple[dict[int,float], list[str]]`: EPU method. For each term: divide its rate by its reference-period standard deviation; average the scaled rates across terms present that day; rescale so the reference-period mean is 100. Returns (index, ids left out). A term with reference SD 0 or fewer than 14 reference days is left out (Review Focus 4).

- [ ] **Step 1: Write the failing tests**
  - `test_weekday_index_uses_same_weekday`: reference Mondays at 10, a later Monday at 15 → 150; a Tuesday with no reference Tuesdays → absent.
  - `test_rate_skips_days_without_probe`.
  - `test_daily_totals_drop_short_days` (Review Focus 1): a day with 19 hourly points is absent.
  - `test_breadth_equal_weight`: two terms with different volumes but the same relative rise of 20% → breadth 120 on that day; doubling one term's volume does not change the result.
  - `test_breadth_leaves_out_constant_term` (Review Focus 4): a term with a constant reference rate → returned in the left-out list, no exception.
  - `test_band_needs_14_reference_days`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the index, composite and breadth measures`.

### Task 7: Events, studies and robustness

**Files:**
- Create: `config/events.toml`, `config/studies.toml`, `monitor/study.py`, `tests/test_study.py`

**Interfaces:**
- Consumes: Task 6 functions, `db.points`.
- Produces:
  - `events.toml`: `[[event]] short = "ELECTION"`, `date = "2026-11-03"`, `label = "US midterm general election"`, `status = "confirmed"`, `source` = a checked official or wire page with its URL (check it on the page before committing).
  - `studies.toml`: `id = "us-midterms-2026"`, `title = "US midterm elections, 3 November 2026"`, `events = ["ELECTION"]`, `pre_days = 14`, `post_days = 14`, `reference_days = 21`, `question = "Did explicit anti-trans term volume on Twitter change before and after the 2026 US midterm elections?"`.
  - `frame(study) -> dict` (window 20 Oct to 17 Nov inclusive, reference 29 Sep to 19 Oct, as in the bot tracker's `study.frame`), `data_range(study) -> (start, end)` (reference start minus 21 days, for the hourly ratio).
  - `build(conn, config, study, now) -> dict` with keys: `id, title, question, window, reference, events, complete, as_of, built_at`, `families: {family: {"daily": {day: index}, "raw_daily": {...}, "band": [lo, hi], "phases": {"before","during","after": mean index}}}`, `breadth: {family: {"daily", "left_out"}}`, `terms: [{id, label, family, precision, precision_ci, "daily": {...}, "phases": {...}}]`, `robustness: {family: {"leave_one_out": {term_id: after_mean}, "raw_vs_probe": {"raw": after, "probe": after}, "originals_vs_reposts": {"posts": after, "reposts": after}, "placebo_share": float|None}}`. "During" is the event day; "after" the 14 days after it. `placebo_share`: the share of days before the study window with full data whose index is at least the after-phase mean (at most, for a fall).
  - `freeze(built, note) -> Path` writing `studies/<id>/v<N>.json` (copied from the bot tracker), `latest(id)`.

- [ ] **Step 1: Write the failing tests** `test_midterms_frame` (window 2026-10-20 to 2026-11-17, reference 2026-09-29 to 2026-10-19, data range from 2026-09-08), `test_build_phases_and_band` (synthetic DB: steady family and probe, then +50% after the event → after ≈ 150, before ≈ 100), `test_leave_one_out_has_one_entry_per_family_term`, `test_freeze_increments_version`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the midterms study, its build and robustness checks`.

### Task 8: Command line and pause between events

**Files:**
- Create: `monitor/__main__.py`, `monitor/pause.py`, `tests/test_cli.py`, `tests/test_pause.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `python -m monitor` subcommands `collect`, `backfill --from DATE [--to DATE] [--missing-before]`, `import-tracker --db PATH`, `study build [ID] [--freeze --note TEXT]`, `export`, `publish [--no-push]`, `pause --reason TEXT`, `resume --reason TEXT --event-date DATE --event-short S --event-label L --event-source TEXT [--event-status reported|confirmed]`, `close-if-done`.
- `pause.py`: `state(settings) -> dict|None` (file `data/pause.json`), `pause(settings, reason, now)`, `resume(...)` (appends the event to `events.toml`, opens a study in `studies.toml`, clears the pause), `close_if_done(conn, config, now) -> dict|None` (freezes the newest study once `now` is at least 1 day after its window end and every family has its last window day, then pauses). Copied and trimmed from the bot tracker's `pause.py` and `study.close_if_done`; no Yandex recovery logic, no Windows task toggling (collection checks `state()` instead).

- [ ] **Step 1: Write the failing tests** `test_collect_does_nothing_while_paused`, `test_close_if_done_freezes_then_pauses` (synthetic data, `now` = window end + 2 days → `v1.json` written and pause state set), `test_resume_opens_study_and_event` (temp config dir: new `[[study]]` and `[[event]]` with source and status present).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the command line and pausing between events`.

### Task 9: Static export and data downloads

**Files:**
- Create: `monitor/static.py`, `CITATION.cff`, `tests/test_static.py`

**Interfaces:**
- Consumes: `study.build`, `study.latest`, `db`, `config`.
- Produces: `export(conn, config, settings, out: Path, now) -> Path` writing: `web/*` copied; `design/terminal.css`; `data/study.json` (newest frozen version, else a provisional build with `"provisional": true`); `data/studies/<id>/v<N>.json`; `data/terms.json` (every term with family, query, label, source, source_url, precision, interval, median posts a day over the study window); `data/series/<key>.csv` (`hour_end_utc,value`) and `data/series/<key>.json`; `data/daily.csv` (`day_utc,key,value`); `data/rejected.json` (the rejected terms and reasons from the spec); `.nojekyll`. `push(out, remote, branch="gh-pages")` copied from the bot tracker.
- `CITATION.cff`: title "Anti-trans rhetoric monitor", author Emma (name only, as in the bot tracker's CITATION.cff), repository URL.

- [ ] **Step 1: Write the failing tests** `test_export_writes_every_series_csv`, `test_csv_has_no_rows_for_gap_hours`, `test_terms_json_has_sources_and_precision`, `test_provisional_flag_without_frozen_version`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add the static export and data downloads`.

### Task 10: Study page

**Files:**
- Create: `web/index.html`, `web/app.js`, `web/app.css`

**Interfaces:**
- Consumes: `data/study.json`, `data/terms.json` (Task 9).
- Produces: the study page from the chosen mockup, on `<html data-palette="term-navy">` with a dark/light toggle that sets `data-mode` (default from `prefers-color-scheme`, set in `<head>` before paint; choice remembered in `localStorage`, wrapped in try/catch).
  - Band `ANTI-TRANS RHETORIC MONITOR · <study title>`; sub row with data date and `PROVISIONAL` when provisional.
  - Hero: the anti-trans family's after-phase index, labelled `ANTI-TRANS TERMS AFTER THE ELECTION · INDEX · 100 = NORMAL (<reference dates>)`.
  - `// DAILY INDEX · 100 = NORMAL`: anti-trans and framing family lines (accent/pattern pairs a2 solid, a3 dashed), breadth as a third line (a1 dotted), the normal band shaded, `100 = NORMAL` dashed, event day marked and labelled, end labels, caption naming band and baseline; gaps break the line.
  - `// EACH TERM · SAME SCALE`: one small multiple per term in a grid, fixed scale 40 to 250, each printing before / election day / after and its precision.
  - `// ROBUSTNESS`: a table of the robustness values per family.
  - `// DATA FOR RESEARCHERS`: links to the CSV/JSON files, CITATION.cff and the Methods tab.
  - Every chart: accessible name, `SHOW DATA AS A TABLE` toggle, unknown values `—`.
  - No named-figures strip at launch (none configured); the spec's later-source work adds it.

- [ ] **Step 1: Export a site from test data** (`python -m monitor export` against a DB filled by `import-tracker`) and serve it: add a `.claude/launch.json` entry `monitor-static` running `.venv/Scripts/python.exe -m http.server 8002 --directory site`.
- [ ] **Step 2: Build the page.** Follow `dataviz` skill rules (load it first) and DESIGN_GUIDE §11.
- [ ] **Step 3: Verify in the browser** at 1280 px and 375 px, dark and light: no console errors, no horizontal scroll, labels don't collide, table view matches the chart's values for three spot-checked days, a gap day shows `—`.
- [ ] **Step 4: Commit** `Add the study page`.

### Task 11: Terms, Methods, Context and Data tabs

**Files:**
- Modify: `web/index.html`, `web/app.js`, `web/app.css`

**Interfaces:**
- Consumes: `data/terms.json`, `data/rejected.json`, `data/studies/`.
- Produces tabs (hash routes `#terms`, `#methods`, `#context`, `#data`):
  - **Terms**: table of every term (family, label, query, source link, posts a day, precision with interval) and the rejected list with reasons.
  - **Methods**: collection, probe normalisation, index, breadth, robustness, precision checks, what a count cannot show, and the statement that the midterms data was seen before the method was fixed. Prose adapted from the spec and the bot tracker's `docs/NARRATIVES.md`.
  - **Context**: the ad campaign summary from the bot tracker's `docs/MIDTERM-ADS.md`, headed as outside research, separate from our measurements, with its sources.
  - **Data**: downloads, frozen versions with notes, citation.
- [ ] **Step 1: Build the tabs.**
- [ ] **Step 2: Verify in the browser** (keyboard: tabs reachable and operable; every link works in the exported site).
- [ ] **Step 3: Commit** `Add the terms, methods, context and data tabs`.

### Task 12: Move the 13 terms out of the bot tracker

**Files (bot tracker):**
- Modify: `config/sources.toml` (remove the 13 blocks added on 16 November), `web/app.js` (restore the anti-trans and framing group descriptions and the About paragraph to describe only the terms the bot tracker keeps; label stays `SINGLE-SEX FRAMING`), `docs/NARRATIVES.md` (keep the precision table; add one line that the 13 terms are tracked by the transphobia monitor, with the repo link), `tests/` as needed.

**Interfaces:**
- The bot tracker keeps: troon(s), "no such thing as (a) trans", "you will never be a (real) woman", "trans youth", and the single-sex phrases. Its DB keeps the 13 terms' points but marks those series inactive (`db.init` already deactivates series missing from config — check this before relying on it).

- [ ] **Step 1: Write the failing test** in the bot tracker `test_sources.py::test_anti_trans_group_is_the_original_three`: the `anti-trans` tag has exactly those three Twitter keywords and the `framing` tag only the single-sex phrases.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Make the edits.**
- [ ] **Step 4: Run** the bot tracker suite → PASS; rebuild its provisional strikes study and check the anti-trans group still has 3 members and the same before/during/after values as before the move (108 / 119 / 126 on the 25 Oct build).
- [ ] **Step 5: Commit** (bot tracker) `Move the newer anti-trans terms to the transphobia monitor`.

### Task 13: Load the data, build the study, publish

- [ ] **Step 1:** `python -m monitor import-tracker --db "C:/Russian bot tracker/data/tracker.db"` → every term key present; report point counts.
- [ ] **Step 2:** `python -m monitor backfill --from 2026-09-08 --missing-before` → about 48 requests (probe and two families from 8 Sep: 9; the 13 newer terms, 8 to 17 Sep: 39), ~$0.48, checked against the usage file before and after. Stop if a dry count of planned requests exceeds 60.
- [ ] **Step 3:** Cross-check: for three terms, daily totals for 10–15 Nov equal those in `docs/research/term_screen-2026-11-16.json` of the bot tracker.
- [ ] **Step 4:** `python -m monitor study build us-midterms-2026` and review the numbers with Emma; freeze v1 only on her go-ahead (`--freeze --note "first version"`).
- [ ] **Step 5:** `python -m monitor export`, preview, then ask Emma before `publish` (it pushes to `gh-pages` and makes the site public), and before pushing `main`.
