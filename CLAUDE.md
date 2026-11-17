# Anti-trans Rhetoric Monitor

Measures anti-trans term volume on Twitter. Split from the Russian bot tracker (`C:\Russian bot tracker`), which keeps its own copy of the original terms.

UI must follow `terminal-design-system/DESIGN_GUIDE.md`. That folder is a copy; the canonical one is in the bot tracker repo. Never edit it here: change the canonical copy and run its `sync_copies.py` (see `terminal-design-system/AGENTS.md`). Any design decision that adds or changes a rule must be written into `DESIGN_GUIDE.md` and synced in the same piece of work.

## Constraints

- Store timestamps and aggregate counts only. Collectors may read post text in memory to compute aggregate measures; only hourly totals are stored. Never store or log usernames, account IDs or post text.
- Exception for named public figures (Emma, 16 November 2026): a short, hand-picked list of public accounts may be tracked by name, to measure how often they post transphobic or transphobic-coded language. Only people with a public role (politicians, officials, platform owners, media figures) or accounts that post as a public brand or outlet qualify, never private individuals. Each entry needs the reason it was picked and a checked source. Counts only: posts matching the terms and the account's total posts per hour. Never store their post text, and never collect anything about the accounts that reply to, follow or repost them.
- Precision checks read posts in memory or in the session; usernames and links are stripped, the text is deleted after coding, and only tallies are kept.
- A failed or empty fetch records an error, never a zero. An hour where the probe returns zero is a gap (no point).
- Unknown values render as `—`. Every number on the site is labelled. Border radius 0.
- User-facing text says "Twitter", never "X" (code may keep `api.x.com` URLs).
- Every term needs `source` and `source_url`; every event needs `source` and `status`. Only terms with hand-checked precision of 0.70 or more are tracked in a family; `context` terms are shown but never in a family.
- Twitter budget: one account serves both projects. Shared daily cap `X_MAX_REQUESTS_PER_DAY` (default 150) across both, via the file named by `TWITTER_USAGE_FILE`. Recent counts cost $0.005 a request, full-archive counts $0.010.
- Palette: Broadcast 8s (`data-palette="term-navy"`), dark and light (`data-mode="light"`), following `terminal-design-system/DESIGN_GUIDE.md` §11.
- Stack: Python with httpx and SQLite. Runtime dependencies: httpx only (pytest for dev). No new runtime dependency without a good reason.
- Tests: `python -m pytest`.
