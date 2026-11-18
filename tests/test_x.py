import asyncio
import json
import time
from datetime import datetime, timezone

import httpx

from monitor import db
from monitor.collectors import x
from monitor.config import Settings, load_config

HOUR = 3600
H0 = int(datetime(2026, 9, 17, 0, tzinfo=timezone.utc).timestamp())


def _term(tid, query):
    return (
        f'[[term]]\nid = "{tid}"\nlabel = "{tid}"\nfamily = "anti-trans"\nquery = "{query}"\n'
        f'source = "Test source"\nsource_url = "https://example.org/{tid}"\n'
        'precision = 0.9\nprecision_n = 50\nprecision_ci = [0.8, 0.95]\nadded = "2026-11-17"\n\n'
    )


def _config(tmp_path, *terms):
    body = '[probe]\nquery = "(thing OR any OR tell)"\n\n' + "".join(_term(t, f"({t} OR {t}s)") for t in terms)
    (tmp_path / "terms.toml").write_text(body, encoding="utf-8")
    return load_config(tmp_path)


def _settings(tmp_path, cap=1000):
    return Settings(db_path=tmp_path / "m.db", x_bearer_token="tok", x_max_requests_per_day=cap,
                    usage_file=tmp_path / "usage.json", public_url="")


def _stamp(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp):
    return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())


class Twitter:
    """Canned counts server. Probe: 100 an hour (0 in `dead_hours`); originals 10, reposts 4, replies 2."""

    def __init__(self, dead_hours=(), fail_for=None, page_size=None):
        self.requests, self.dead, self.fail_for, self.page_size = [], set(dead_hours), fail_for, page_size

    def handler(self, request):
        q = request.url.params
        self.requests.append((request.url.path, dict(q)))
        query = q["query"]
        if self.fail_for and query.startswith(self.fail_for):  # the family query starts "((", so it does not match
            return httpx.Response(503, text="unavailable")
        start, end = _parse(q["start_time"]), _parse(q["end_time"])
        hours = list(range(start, end, HOUR))
        if self.page_size:  # first page holds the first `page_size` hours and a next_token
            page = 1 if "next_token" in q else 0
            chunk = hours[page * self.page_size:(page + 1) * self.page_size]
            meta = {} if page else {"next_token": "abc"}
        else:
            chunk, meta = hours, {}
        if "thing" in query:
            def n(h):
                return 0 if h in self.dead else 100
        elif "-is:retweet" in query:
            def n(h):
                return 10
        elif "is:retweet" in query:
            def n(h):
                return 4
        else:
            def n(h):
                return 2
        data = [{"start": _stamp(h), "end": _stamp(h + HOUR), "tweet_count": n(h)} for h in chunk]
        return httpx.Response(200, json={"data": data, "meta": meta})

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


async def _collect(tw, config, settings, **kw):
    async with tw.client() as client:
        return await x.collect(client, config, settings, **kw)


def test_three_requests_per_term_one_per_family_and_probe(tmp_path):
    cfg, tw = _config(tmp_path, "alpha", "beta"), Twitter()
    result = asyncio.run(_collect(tw, cfg, _settings(tmp_path), now=int(time.time())))
    assert len(tw.requests) == 2 * 3 + 1 + 1
    by_path = {}
    for path, q in tw.requests:
        by_path.setdefault(path, []).append(q["query"])
    assert len(by_path["/2/tweets/counts/recent"]) == 6
    all_queries = by_path["/2/tweets/counts/all"]
    assert len(all_queries) == 2
    assert any("thing" in q for q in all_queries) and any("alpha" in q and "beta" in q for q in all_queries)
    for _, q in tw.requests:
        assert q["query"].count("lang:en") == 1
    assert not result.errors
    assert "x.alpha-or-alphas.en.repost-share" in result.points
    assert "x.probe.en.posts" in result.points and "x.family.anti-trans.en.posts" in result.points


def test_series_stored_per_kind(tmp_path):
    cfg = _config(tmp_path, "alpha")
    result = asyncio.run(_collect(Twitter(), cfg, _settings(tmp_path), now=H0 + 10 * HOUR, start=H0, end=H0 + 3 * HOUR))
    assert set(result.points) == {"x.probe.en.posts", "x.family.anti-trans.en.posts",
                                  "x.alpha-or-alphas.en.posts", "x.alpha-or-alphas.en.reposts",
                                  "x.alpha-or-alphas.en.replies", "x.alpha-or-alphas.en.repost-share"}
    assert result.points["x.alpha-or-alphas.en.posts"] == [(H0 + HOUR, 10.0), (H0 + 2 * HOUR, 10.0), (H0 + 3 * HOUR, 10.0)]
    assert result.points["x.alpha-or-alphas.en.repost-share"][0] == (H0 + HOUR, round(100 * 4 / 14, 2))


def test_gap_hours_get_no_points(tmp_path):
    cfg, gap = _config(tmp_path, "alpha", "beta"), H0 + HOUR  # bucket 01:00-02:00, stamped 02:00
    tw = Twitter(dead_hours={gap})
    result = asyncio.run(_collect(tw, cfg, _settings(tmp_path), now=H0 + 10 * HOUR, start=H0, end=H0 + 4 * HOUR))
    assert result.points
    for key, pts in result.points.items():
        stamps = {t for t, _ in pts}
        assert gap + HOUR not in stamps, key
        assert {H0 + HOUR, H0 + 3 * HOUR, H0 + 4 * HOUR} <= stamps, key
    assert any("no data for 1 hours" in e for e in result.errors)


def test_probe_gap_applies_to_live_recent_terms(tmp_path):
    cfg, now = _config(tmp_path, "alpha"), int(time.time())
    gap = (now - 15) // HOUR * HOUR - 2 * HOUR
    result = asyncio.run(_collect(Twitter(dead_hours={gap}), cfg, _settings(tmp_path), now=now))
    stamps = {t for t, _ in result.points["x.alpha-or-alphas.en.posts"]}
    assert gap + HOUR not in stamps and gap + 2 * HOUR in stamps


def test_failed_request_records_error_not_zero(tmp_path):
    cfg = _config(tmp_path, "alpha", "beta")
    result = asyncio.run(_collect(Twitter(fail_for="(alpha"), cfg, _settings(tmp_path),
                                  now=H0 + 10 * HOUR, start=H0, end=H0 + 3 * HOUR))
    assert not any(k.startswith("x.alpha") for k in result.points)
    assert any("alpha" in e for e in result.errors)
    assert result.points["x.beta-or-betas.en.posts"]
    assert "x.probe.en.posts" in result.points


def test_failed_probe_writes_nothing(tmp_path):
    cfg, tw = _config(tmp_path, "alpha"), Twitter(fail_for="(thing")
    result = asyncio.run(_collect(tw, cfg, _settings(tmp_path), now=H0 + 10 * HOUR, start=H0, end=H0 + 3 * HOUR))
    assert result.points == {} and any("probe" in e.lower() for e in result.errors)
    assert len(tw.requests) == 1


def test_budget_exhausted_keeps_only_whole_keywords(tmp_path):
    cfg = _config(tmp_path, "alpha", "beta")
    # probe (1) + alpha (3) + one of beta's three: the cap hits in the middle of beta
    result = asyncio.run(_collect(Twitter(), cfg, _settings(tmp_path, cap=5),
                                  now=H0 + 10 * HOUR, start=H0, end=H0 + 3 * HOUR))
    assert "x.alpha-or-alphas.en.posts" in result.points
    assert not any(k.startswith("x.beta") for k in result.points)
    assert not any(k.startswith("x.family") for k in result.points)
    assert any("cap" in e and "5" in e for e in result.errors)
    assert "x.probe.en.posts" in result.points  # paid for, so kept


def test_paging_follows_next_token(tmp_path):
    cfg, tw = _config(tmp_path, "alpha"), Twitter(page_size=2)
    result = asyncio.run(_collect(tw, cfg, _settings(tmp_path), now=H0 + 10 * HOUR, start=H0, end=H0 + 4 * HOUR))
    assert len(result.points["x.probe.en.posts"]) == 4
    assert any(q.get("next_token") == "abc" for _, q in tw.requests)
    day = time.strftime("%Y-%m-%d", time.gmtime())
    assert json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))[day] == len(tw.requests)  # one unit per page


def test_lang_en_added_exactly_once():
    assert x.filtered("(a OR b) lang:en", "-is:retweet") == "(a OR b) lang:en -is:retweet"
    assert x.filtered("(a OR b)", "-is:retweet") == "(a OR b) lang:en -is:retweet"
    assert x.filtered("(a OR b)", "") == "(a OR b) lang:en"


def test_backfill_missing_before_stops_at_earliest_point(tmp_path):
    cfg, settings = _config(tmp_path, "alpha", "beta"), _settings(tmp_path)
    with db.session(settings.db_path) as conn:
        db.init(conn, cfg.series)
        db.replace_hours(conn, "x.alpha-or-alphas.en.posts", [(H0 + HOUR, 1.0), (H0 + 2 * HOUR, 1.0)])  # first stored stamp 17 Sep 01:00, the end of the 00:00 hour
    start, end = H0 - 5 * HOUR, H0 + 30 * HOUR
    tw = Twitter()

    async def go():
        async with tw.client() as client:
            return await x.backfill(cfg, settings, start, end=end, missing_before=True, client=client)

    out = asyncio.run(go())
    ends = {}
    for _, q in tw.requests:
        ends.setdefault(q["query"], set()).add(q["end_time"])
    alpha = {e for query, es in ends.items() if "alpha" in query and "beta" not in query for e in es}
    beta = {e for query, es in ends.items() if "beta" in query and "alpha" not in query for e in es}
    assert alpha == {"2026-09-17T00:00:00Z"}
    assert beta == {_stamp(end)}
    assert len(out["(alpha OR alphas)"].points["x.alpha-or-alphas.en.posts"]) == 5
    assert len(out["(beta OR betas)"].points["x.beta-or-betas.en.posts"]) == 35


def test_backfill_skips_keyword_already_stored_before_start(tmp_path):
    cfg, settings = _config(tmp_path, "alpha"), _settings(tmp_path)
    with db.session(settings.db_path) as conn:
        db.init(conn, cfg.series)
        db.replace_hours(conn, "x.alpha-or-alphas.en.posts", [(H0 - 10 * HOUR, 1.0)])
    tw = Twitter()

    async def go():
        async with tw.client() as client:
            return await x.backfill(cfg, settings, H0, end=H0 + 5 * HOUR, missing_before=True, client=client)

    out = asyncio.run(go())
    assert "(alpha OR alphas)" not in out
    assert not any(q["query"].startswith("(alpha") for _, q in tw.requests)  # the family query still runs


def test_run_writes_points_and_records_run(tmp_path, monkeypatch):
    cfg, settings, tw = _config(tmp_path, "alpha"), _settings(tmp_path), Twitter()
    real = httpx.AsyncClient
    monkeypatch.setattr(x.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(tw.handler)))
    asyncio.run(x.run(cfg, settings, int(time.time())))
    with db.session(settings.db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM points WHERE key = 'x.alpha-or-alphas.en.posts'").fetchone()[0]
        run = conn.execute("SELECT platform, ok, points, error FROM runs").fetchone()
    assert n > 100 and run["platform"] == "twitter" and run["ok"] == 1 and run["points"] > n


def test_backfill_skips_keyword_stored_up_to_start_plus_an_hour(tmp_path):
    cfg, settings = _config(tmp_path, "alpha"), _settings(tmp_path)
    with db.session(settings.db_path) as conn:
        db.init(conn, cfg.series)
        db.replace_hours(conn, "x.alpha-or-alphas.en.posts", [(H0 + HOUR, 1.0)])  # the hour starting at `start`
    tw = Twitter()

    async def go():
        async with tw.client() as client:
            return await x.backfill(cfg, settings, H0, end=H0 + 5 * HOUR, missing_before=True, client=client)

    out = asyncio.run(go())
    assert "(alpha OR alphas)" not in out
    assert not any(q["query"].startswith("(alpha") for _, q in tw.requests)
    # only the family and the probe (nothing stored) were requested, and each took one budget unit
    day = time.strftime("%Y-%m-%d", time.gmtime())
    assert json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))[day] == len(tw.requests) == 2


def test_malformed_body_is_an_error_and_keeps_complete_keywords(tmp_path):
    cfg, tw = _config(tmp_path, "alpha", "beta"), Twitter()
    ok = tw.handler

    def handler(request):
        if request.url.params["query"].startswith("(beta") and "-is:retweet" in request.url.params["query"]:
            return httpx.Response(200, json={"data": [{"start": "2026-09-17T00:00:00Z"}]})  # no tweet_count
        return ok(request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await x.collect(client, cfg, _settings(tmp_path), now=H0 + 10 * HOUR, start=H0, end=H0 + 3 * HOUR)

    result = asyncio.run(go())
    assert any("malformed" in e for e in result.errors)
    assert not any(k.startswith("x.beta") for k in result.points)
    assert "x.alpha-or-alphas.en.posts" in result.points and "x.probe.en.posts" in result.points
