# Anti-trans rhetoric monitor

Measures how often anti-trans terms appear on Twitter, as hourly counts. Split from the Russian bot tracker; it runs on its own and shares only the Twitter request counter.

Counts only: no usernames, account IDs or post text are stored.

## Running it

### Settings

Settings come from the environment or from a `.env` file in the project folder (`.env.example` lists them). Variables already set in the environment win over the file.

| Variable | Needed for | Meaning |
|---|---|---|
| `X_BEARER_TOKEN` | `collect`, `backfill` | Twitter API bearer token. |
| `TWITTER_USAGE_FILE` | `collect`, `backfill` | Path of the request counter file shared with the Bot Traffic Monitor. Both projects must name the same file, so their combined use stays under one daily cap. Without it the monitor refuses to make any Twitter request. |
| `X_MAX_REQUESTS_PER_DAY` | `collect`, `backfill` | The shared daily request cap across both projects (default 150). |
| `MONITOR_DB` | every command | The SQLite database (default `data/monitor.db`). |
| `MONITOR_PUBLIC_URL` | optional | The site's public address. It is read into the settings, but no command uses it yet. |

Relative paths are taken from the project folder.

Format of `.env`:

- One `KEY=VALUE` per line. Quotes around the value are removed.
- No `export` in front of the key.
- No comment after a value on the same line: everything after `=` is the value. Whole-line comments starting with `#` are fine.

### Commands

Run them from the project folder with `.venv\Scripts\python.exe -m monitor <command>`, in this order:

1. `import-tracker --db <path to the bot tracker's data/tracker.db>` copies the existing hourly points for the shared series. No Twitter request.
2. `backfill --from YYYY-MM-DD [--to YYYY-MM-DD] [--missing-before] [--max-requests N]` loads full-archive history. It counts the requests it would make before making any, and refuses if there are more than N (default 60). With `--missing-before` it fetches only the hours before each search's earliest stored hour, and skips a search already stored back to the start date. Full-archive requests cost $0.010 each.
3. `study build [id]` builds the newest study (or the one named) from the database and prints its numbers. It writes nothing.
4. `export --out <folder>` writes the static site and the data downloads. Without a frozen version the site shows the study as provisional.
5. `publish` exports to a temporary folder and force-pushes it to the `gh-pages` branch (`--no-push` exports only).

`collect` runs one live pass (three requests per term plus the two family searches and the probe: 54 with the 17 terms in `config/terms.toml` today) and is meant to run once a day while a study is open. It does nothing while collection is paused (`pause --reason ...`; `resume ...` opens a study around a new event). After a pass it checks the newest study: once a day has passed since the window ended and the study's data is complete (every family has a normal range, a before and an after mean, and the probe and every family have the window's last day), it freezes the study and pauses collection. If the data is not complete it freezes nothing and logs why. `close-if-done` runs the same check without collecting.

Freezing a study (`study build --freeze --note "..."`, or `collect` as above) and publishing the site are the owner's decisions. A frozen version is what the site shows; changing it means freezing a new version with a note saying what changed.

## Development

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest
```

The UI follows `terminal-design-system/`, a copy of the canonical folder in the bot tracker repo. Do not edit it here; see its `AGENTS.md`.
