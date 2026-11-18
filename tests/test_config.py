import pytest

from monitor.config import load_config, slug

SUFFIX = " lang:en -is:retweet"


def _term(tid, family, query, precision):
    prec = "" if precision is None else f"precision = {precision}\nprecision_n = 50\nprecision_ci = [0.5, 0.9]\n"
    return (
        f'[[term]]\nid = "{tid}"\nlabel = "{tid}"\nfamily = "{family}"\nquery = "{query}"\n'
        f'source = "Test source"\nsource_url = "https://example.org/{tid}"\n{prec}added = "2026-11-17"\n\n'
    )


def _write(tmp_path, body):
    (tmp_path / "terms.toml").write_text('[probe]\nquery = "(thing OR any OR tell)"\n\n' + body, encoding="utf-8")
    return tmp_path


def test_terms_and_families():
    cfg = load_config()
    by_family = {}
    for t in cfg.terms:
        by_family.setdefault(t.family, []).append(t)
    assert len(by_family["anti-trans"]) == 9
    assert len(by_family["framing"]) == 8
    assert len(by_family["context"]) == 1
    for t in cfg.terms:
        assert t.source and t.source_url
        if t.family != "context":
            assert t.precision is not None and t.precision >= 0.70


def test_keys_match_bot_tracker():
    assert slug("(troon OR troons)") == "troon-or-troons"
    keys = {s.key for s in load_config().series}
    assert "x.troon-or-troons.en.posts" in keys
    assert "x.family.anti-trans.en.posts" in keys
    assert "x.probe.en.posts" in keys


def test_family_query_is_or_of_members():
    cfg = load_config()
    fq = cfg.family_queries["anti-trans"]
    for t in cfg.terms:
        if t.family == "anti-trans":
            assert t.query in fq
        elif t.family == "framing":
            assert t.query not in fq
    assert set(cfg.family_queries) == {"anti-trans", "framing"}
    context = [t for t in cfg.terms if t.family == "context"]
    assert all(t.query not in q for t in context for q in cfg.family_queries.values())


def test_family_and_probe_use_full_archive():
    cfg = load_config()
    wide = [s for s in cfg.series if s.term_id is None]
    assert len(wide) == 3
    for s in wide:
        assert s.endpoint == "all" and s.metric == "posts"
    assert cfg.probe_query == "(thing OR any OR tell)"
    terms = [s for s in cfg.series if s.term_id is not None]
    assert all(s.endpoint == "recent" for s in terms)
    assert {s.metric for s in terms} == {"posts", "reposts", "replies", "repost-share"}
    assert len(terms) == 4 * len(cfg.terms)


def test_family_query_too_long_raises(tmp_path):
    body = "".join(_term(f"t{i}", "anti-trans", "word" + "x" * 150 + str(i), 0.9) for i in range(8))
    with pytest.raises(ValueError) as e:
        load_config(_write(tmp_path, body))
    assert "anti-trans" in str(e.value)
    assert "1024" in str(e.value)
    assert str(len("(" + " OR ".join("word" + "x" * 150 + str(i) for i in range(8)) + ")" + SUFFIX)) in str(e.value)


def test_term_below_threshold_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, _term("low", "framing", "lowterm", 0.69)))


def test_trans_cult_is_tracked_with_its_checked_source():
    cfg = load_config()
    t = {x.id: x for x in cfg.terms}["trans-cult"]
    assert t.family == "anti-trans" and t.query == '("trans cult" OR "gender cult")'
    assert (t.precision, t.precision_n, t.precision_ci) == (0.86, 50, (0.738, 0.93)) or \
        (t.precision, t.precision_n, list(t.precision_ci)) == (0.86, 50, [0.738, 0.93])
    assert "rationalwiki.org/wiki/TERF_glossary" in t.source_url and "Trans cult" in t.source
    assert '"trans cult"' in cfg.family_queries["anti-trans"]
