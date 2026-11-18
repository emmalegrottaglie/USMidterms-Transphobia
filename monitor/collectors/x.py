"""Twitter post volumes for each tracked term, via the Twitter API counts endpoints.

Counts only: no posts or accounts are read. Per term, three requests give
- original posts per hour (query -is:retweet), the series group statistics use;
- reposts per hour (is:retweet), and the repost share of all posts;
- replies per hour (is:reply).
Each family and the probe get one request (original posts per hour). Every query is
restricted to English with lang:en, added exactly once.

The Twitter archive has outages: on 2026-09-28 from 15:00 to 24:00 UTC every query counted
zero. So each pass also counts the probe query, which matches millions of posts an hour; an
hour where even the probe is zero is a gap in the Twitter data and gets no point in any series
of the pass (the probe's own included), never a zero. The probe is fetched once per pass on
the full-archive endpoint and is also stored as a series. If the probe request fails, nothing
is written for that pass, since without it gaps cannot be told from zeros.

Pay-per-use: $0.005 per recent-counts request, $0.010 per full-archive request. Every request,
each page included, takes one from the shared daily Budget first. When the cap is reached
mid-pass, the keywords already complete are kept and the rest are left for the next pass; a
keyword is never written partly.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

import httpx

from .. import db
from ..budget import Budget, BudgetExhausted
from ..config import Config, SeriesSpec, Settings
from . import Result

RECENT = "https://api.x.com/2/tweets/counts/recent"
ALL = "https://api.x.com/2/tweets/counts/all"
HOUR = 3600
PLATFORM = "twitter"
PARTIAL = 0.1  # probe below this share of its median: Twitter coverage of that hour looks partial (logged)
log = logging.getLogger(__name__)

# Count queries per term, appended to "<query> lang:en".
VARIANTS = {"orig": "-is:retweet", "rt": "is:retweet", "reply": "is:reply"}


def filtered(query: str, variant: str) -> str:
    """The query with lang:en (once) and the variant filter."""
    base = query if "lang:en" in query else f"{query} lang:en"
    return f"{base} {variant}" if variant else base


def recent_start(stop: int, wall: int) -> int:
    """First hour of the 7-day recent window. Twitter measures the 7 days from when the request
    is made, not from the pass `now`, and a pass can reach Twitter long after it started (a
    laptop that slept: on 21 October 2026 Twitter was reached two hours late and the request
    was refused)."""
    earliest = -(-(wall - 7 * 24 * HOUR + 60) // HOUR) * HOUR  # whole hours, a minute of margin
    return max(stop - 7 * 24 * HOUR + HOUR, earliest)


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())


def buckets(payload: dict) -> dict[int, int]:
    """{bucket_start: count} from a counts response."""
    try:
        if payload.get("errors") and not payload.get("data"):
            raise ValueError(payload["errors"][0].get("message", "error"))
        return {_ts(d["start"]): int(d["tweet_count"]) for d in payload.get("data") or []}
    except (KeyError, TypeError, IndexError, AttributeError) as e:  # a malformed body is an error, not a crash
        raise ValueError(f"malformed counts response ({type(e).__name__})") from e


def metrics(orig: dict[int, int], rt: dict[int, int], reply: dict[int, int],
            gaps: set[int] = frozenset()) -> dict[str, list[tuple[int, float]]]:
    """Hourly points per metric, stamped at each hour end. Hours in `gaps` (Twitter had no
    data at all) are left out; otherwise Twitter returns zero buckets explicitly, so a zero
    here is a real zero."""
    out: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for h in sorted(set(orig) - gaps):
        out["posts"].append((h + HOUR, float(orig[h])))
        if h in rt:
            out["reposts"].append((h + HOUR, float(rt[h])))
            total = orig[h] + rt[h]
            if total:
                out["repost-share"].append((h + HOUR, round(100 * rt[h] / total, 2)))
        if h in reply:
            out["replies"].append((h + HOUR, float(reply[h])))
    return dict(out)


async def _counts(client: httpx.AsyncClient, budget: Budget, token: str, url: str, query: str,
                  start: int, end: int) -> dict[int, int]:
    out: dict[int, int] = {}
    params = {"query": query, "granularity": "hour", "start_time": _iso(start), "end_time": _iso(end)}
    while True:
        budget.take()  # before every request, each page included
        r = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 400:
            raise httpx.HTTPStatusError(f"{r.status_code}: {r.text[:200]}", request=r.request, response=r)
        payload = r.json()
        out.update(buckets(payload))
        token_next = (payload.get("meta") or {}).get("next_token")
        if not token_next:
            return out
        params["next_token"] = token_next


async def _pass(client: httpx.AsyncClient, budget: Budget, settings: Settings, probe_query: str,
                specs: list[SeriesSpec], now: int, start: int | None, end: int | None,
                probe_cache: dict) -> tuple[Result, bool]:
    """One window over `specs`. Returns the result and whether the budget ran out."""
    token, result = settings.x_bearer_token, Result()
    if not token:
        result.errors.append("Twitter bearer token (X_BEARER_TOKEN) not set")
        return result, False
    # Whole hours only, and Twitter wants end_time at least 10 s in the past.
    stop = min(now - 15, end if end is not None else now) // HOUR * HOUR
    live = start is None
    begin = recent_start(stop, int(time.time())) if live else start // HOUR * HOUR
    if begin >= stop:
        result.errors.append("Twitter window is empty (a live pass more than 7 days old by the time Twitter is reached, or no whole hour)")
        return result, False

    def url_for(spec: SeriesSpec) -> str:
        return RECENT if live and spec.endpoint == "recent" else ALL

    cache_key = (begin, stop)
    try:
        if cache_key not in probe_cache:  # a backfill calls this once per keyword
            probe_cache[cache_key] = await _counts(client, budget, token, ALL, filtered(probe_query, "-is:retweet"), begin, stop)
        probe = probe_cache[cache_key]
    except BudgetExhausted as e:
        result.errors.append(f"Twitter probe not fetched, nothing written: {e}")
        return result, True
    except (httpx.HTTPError, ValueError) as e:
        result.errors.append(f"Twitter probe: {e}")  # without it, gaps cannot be told from zeros
        return result, False
    gaps = {h for h, n in probe.items() if n == 0}
    if gaps:
        result.errors.append(f"Twitter has no data for {len(gaps)} hours ({_iso(min(gaps))} to {_iso(max(gaps) + HOUR)}): left as gaps")
    if probe:
        typical = sorted(probe.values())[len(probe) // 2]
        thin = sorted(h for h, n in probe.items() if 0 < n < PARTIAL * typical)
        if thin:
            log.warning("Twitter coverage looks partial in %d hours: %s", len(thin), ", ".join(_iso(h) for h in thin[:10]))

    groups: dict[tuple[str, bool], list[SeriesSpec]] = defaultdict(list)
    for s in specs:  # one set of requests per query: a term shares three, any other series one
        groups[(s.query, s.term_id is not None)].append(s)
    # The probe first: it is already paid for, so it is kept even if the budget runs out later.
    for (query, is_term), group in sorted(groups.items(), key=lambda kv: kv[1][0].family != "probe"):
        try:
            if is_term:
                u = url_for(group[0])
                got = {k: await _counts(client, budget, token, u, filtered(query, v), begin, stop) for k, v in VARIANTS.items()}
                by_metric = metrics(got["orig"], got["rt"], got["reply"], gaps)
            elif group[0].family == "probe":
                by_metric = metrics(probe, {}, {}, gaps)  # already fetched, no second request
            else:
                orig = await _counts(client, budget, token, url_for(group[0]), filtered(query, "-is:retweet"), begin, stop)
                by_metric = metrics(orig, {}, {}, gaps)
        except BudgetExhausted as e:
            result.errors.append(f"{e}: stopped, kept only the keywords already complete")
            return result, True
        except (httpx.HTTPError, ValueError) as e:
            result.errors.append(f"Twitter {filtered(query, '')!r}: {e}")
            continue
        for s in group:  # reached only when all of the keyword requests finished
            pts = by_metric.get(s.metric)
            if pts:
                result.points[s.key] = pts
            else:
                result.errors.append(f"{s.key}: no data returned")
    return result, False


async def collect(client: httpx.AsyncClient, config: Config, settings: Settings, now: int,
                  start: int | None = None, end: int | None = None) -> Result:
    """Data only; nothing is written. `start is None` is the live pass: terms use the recent
    endpoint (last 7 days), the family and probe series the full archive over the same hours.
    With `start`, a backfill window on the full archive for everything."""
    budget = Budget(settings.usage_file, settings.x_max_requests_per_day)
    result, _ = await _pass(client, budget, settings, config.probe_query, list(config.series), now, start, end, {})
    return result


async def backfill(config: Config, settings: Settings, start: int, end: int | None = None,
                   missing_before: bool = False, client: httpx.AsyncClient | None = None) -> dict[str, Result]:
    """Full-archive history from `start` to `end` (default: now), one Result per keyword, keyed
    by its query. With `missing_before`, a keyword window ends where its earliest stored hour starts,
    and a keyword already stored back to `start` is skipped without any request. Data only; the caller writes it.
    `client` is optional: tests pass one built on httpx.MockTransport; by default a real one is
    opened and closed here."""
    if not settings.x_bearer_token:
        raise RuntimeError("Twitter bearer token (X_BEARER_TOKEN) not set")
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=45, follow_redirects=True)
    budget, now, cache = Budget(settings.usage_file, settings.x_max_requests_per_day), int(time.time()), {}
    groups: dict[str, list[SeriesSpec]] = defaultdict(list)
    for s in config.series:
        groups[s.query].append(s)
    out: dict[str, Result] = {}
    try:
        for query, specs in groups.items():
            stop_at = end
            if missing_before:
                with db.session(settings.db_path) as conn:
                    db.init(conn, config.series)
                    ranges = [r for r in (db.point_range(conn, s.key) for s in specs) if r]
                if ranges:
                    # Stored stamps are hour ends: the earliest stored hour starts an hour before.
                    earliest = min(r[0] for r in ranges) - HOUR
                    if earliest <= start:
                        continue
                    stop_at = earliest if end is None else min(end, earliest)
            result, exhausted = await _pass(client, budget, settings, config.probe_query, specs, now, start, stop_at, cache)
            out[query] = result
            if exhausted:
                break
    finally:
        if own:
            await client.aclose()
    return out


async def run(config: Config, settings: Settings, now: int) -> None:
    """The live pass: collect, write with replace_hours, record one run."""
    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
        try:
            result = await collect(client, config, settings, now)
        except Exception as e:  # one broken pass must not stop the caller
            log.exception("Twitter pass failed")
            result = Result(errors=[f"{type(e).__name__}: {e}"])
    with db.session(settings.db_path) as conn:
        db.init(conn, config.series)
        n = sum(db.replace_hours(conn, key, pts) for key, pts in result.points.items())
        db.record_run(conn, PLATFORM, bool(result.points), n, "; ".join(result.errors)[:2000] or None)
    for err in result.errors:
        log.warning("Twitter: %s", err)
    log.info("Twitter: %d points, %d errors", n, len(result.errors))
