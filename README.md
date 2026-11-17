# Anti-trans rhetoric monitor

Measures how often anti-trans terms appear on Twitter, as hourly counts. Split from the Russian bot tracker; it runs on its own and shares only the Twitter request counter.

Counts only: no usernames, account IDs or post text are stored.

## Development

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest
```

The UI follows `terminal-design-system/`, a copy of the canonical folder in the bot tracker repo. Do not edit it here; see its `AGENTS.md`.
