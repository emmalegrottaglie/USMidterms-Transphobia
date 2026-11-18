import json
from datetime import datetime, timezone

from monitor import analysis, db, study
from monitor.config import METRICS, Config, SeriesSpec, Term, slug

DAY = 86400
HOUR = 3600


def ts(date: str) -> int:
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp())


def make_config(terms=(("a1", "anti-trans"), ("a2", "anti-trans"), ("f1", "framing"), ("ctx", "context"))):
    ts_ = tuple(Term(id=i, label=i.upper(), family=fam, query=i, source="s", source_url="u",
                     precision=0.9, precision_n=50, precision_ci=(0.8, 0.95), added="2026-11-01")
                for i, fam in terms)
    series = [SeriesSpec(key=f"x.{slug(t.query)}.en.{m}", label=t.label, unit=u, family=t.family,
                         term_id=t.id, metric=m, query=t.query, endpoint="recent")
              for t in ts_ for m, u in METRICS]
    for fam in ("anti-trans", "framing"):
        series.append(SeriesSpec(key=f"x.family.{fam}.en.posts", label=fam, unit="POSTS / H", family=fam,
                                 term_id=None, metric="posts", query="q", endpoint="all"))
    series.append(SeriesSpec(key="x.probe.en.posts", label="Probe", unit="POSTS / H", family="probe",
                             term_id=None, metric="posts", query="p", endpoint="all"))
    return Config(terms=ts_, series=tuple(series), probe_query="p", family_queries={})


def fill(conn, key, value, first_day, last_day):
    """24 hourly points per day, from first_day through last_day (UTC day starts). `value`
    is a number or a function of the day start."""
    pts = []
    for d in range(first_day, last_day + 1, DAY):
        v = value(d) if callable(value) else value
        pts += [(d + (h + 1) * HOUR, v) for h in range(24)]
    db.upsert_points(conn, key, pts)


def noisy(d):
    return 10.0 + (d // DAY) % 3  # varies a little so the breadth index has a reference spread


def populate(conn, config, *, after_factor=1.5, probe=lambda d: 1000.0, family=None):
    """Everything from 8 Sep to 17 Nov 2026. Family and term posts jump by `after_factor` after
    the event day (3 Nov)."""
    first, last, event = ts("2026-09-08"), ts("2026-11-17"), ts("2026-11-03")
    grow = lambda d: after_factor if d > event else 1.0
    fill(conn, "x.probe.en.posts", probe, first, last)
    for fam in ("anti-trans", "framing"):
        fn = family or (lambda d: 100.0 * grow(d))
        fill(conn, f"x.family.{fam}.en.posts", fn, first, last)
    for t in config.terms:
        fill(conn, f"x.{slug(t.query)}.en.posts", lambda d: noisy(d) * grow(d), first, last)
        fill(conn, f"x.{slug(t.query)}.en.reposts", lambda d: 2.0 * grow(d), first, last)


def new_db(tmp_path, config):
    conn = db.connect(tmp_path / "m.db")
    db.init(conn, config.series)
    return conn


def the_study():
    return study.get("us-midterms-2026")


def test_midterms_frame():
    s = the_study()
    f = study.frame(s)
    assert f["start"] == ts("2026-10-20")
    assert f["end"] == ts("2026-11-18") - 1  # last second of 17 Nov
    assert f["reference_start"] == ts("2026-09-29")
    assert f["reference_end"] - DAY == ts("2026-10-19")  # last reference day is 19 Oct
    assert f["event_days"] == (ts("2026-11-03"), ts("2026-11-04") - 1)
    start, end = study.data_range(s)
    assert start == ts("2026-09-08")
    assert end == f["end"] + 1


def test_build_phases_and_band(tmp_path):
    cfg = make_config()
    conn = new_db(tmp_path, cfg)
    populate(conn, cfg)
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-18") + HOUR)
    fam = built["families"]["anti-trans"]
    assert abs(fam["phases"]["before"] - 100) < 1
    assert abs(fam["phases"]["after"] - 150) < 1
    assert fam["phases"]["during"] is not None and abs(fam["phases"]["during"] - 100) < 1
    assert fam["band"] is not None and fam["band"][0] <= 100.001 and fam["band"][1] >= 99.999
    assert fam["raw_daily"][ts("2026-11-10")] == 24 * 150.0
    assert built["complete"] is True
    assert built["as_of"] == "2026-11-18T00:00:00Z"
    assert built["built_at"] == "2026-11-18T01:00:00Z"
    assert built["reference"] == {"start": ts("2026-09-29"), "end": ts("2026-10-19"), "days": 21}
    ids = [t["id"] for t in built["terms"]]
    assert ids == ["a1", "a2", "f1", "ctx"]  # the context term is included
    assert built["terms"][0]["precision_ci"] == [0.8, 0.95]
    assert abs(built["terms"][0]["phases"]["after"] - 150) < 1
    assert set(built["breadth"]) == {"anti-trans", "framing"}


def test_complete_is_false_while_window_is_open(tmp_path):
    cfg = make_config()
    conn = new_db(tmp_path, cfg)
    populate(conn, cfg)
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-17") + 12 * HOUR)
    assert built["complete"] is False


def test_leave_one_out_has_one_entry_per_family_term(tmp_path):
    cfg = make_config()
    conn = new_db(tmp_path, cfg)
    populate(conn, cfg)
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-18") + HOUR)
    rob = built["robustness"]
    assert set(rob["anti-trans"]["leave_one_out"]) == {"a1", "a2"}
    assert set(rob["framing"]["leave_one_out"]) == {"f1"}  # context term never counted
    for v in rob["anti-trans"]["leave_one_out"].values():
        assert abs(v - 150) < 2
    # one term left, removed: nothing to average, unknown not 0
    assert rob["framing"]["leave_one_out"]["f1"] is None
    assert abs(rob["anti-trans"]["originals_vs_reposts"]["posts"] - 150) < 1
    assert abs(rob["anti-trans"]["originals_vs_reposts"]["reposts"] - 150) < 1


def test_raw_vs_probe_when_probe_surges_with_flat_family(tmp_path):
    cfg = make_config()
    conn = new_db(tmp_path, cfg)
    event = ts("2026-11-03")
    populate(conn, cfg, after_factor=1.0, family=lambda d: 100.0,
             probe=lambda d: 2000.0 if d > event else 1000.0)
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-18") + HOUR)
    r = built["robustness"]["anti-trans"]["raw_vs_probe"]
    assert abs(r["raw"] - 100) < 1
    assert abs(r["probe"] - 50) < 1
    assert r["probe"] < r["raw"]


def test_placebo_share_on_synthetic_data(tmp_path):
    cfg = make_config()
    conn = new_db(tmp_path, cfg)
    first, ref_start = ts("2026-09-08"), ts("2026-09-29")
    # 8 to 28 Sep: three days at 300 (relative to a reference of 100), the rest at 100.
    high = {ts("2026-09-10"), ts("2026-09-12"), ts("2026-09-14")}

    def family(d):
        if d > ts("2026-11-03"):
            return 150.0
        return 300.0 if d in high else 100.0

    populate(conn, cfg, family=family)
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-18") + HOUR)
    # Placebo days run from the start of the data to the day before the reference period:
    # 8 to 28 Sep, 21 days, three of them well over the after mean (~150). Reference days
    # are left out: they define 100, so they cannot also test it. Weekday means come from
    # the reference only, so the high days index at 300.
    assert built["robustness"]["anti-trans"]["placebo_share"] == round(3 / 21, 3)
    assert first < ref_start


def test_placebo_share_leaves_out_reference_days(tmp_path):
    cfg = make_config()
    conn = new_db(tmp_path, cfg)
    # Only the reference days (29 Sep to 19 Oct) exist before the window: no placebo days.
    first = ts("2026-09-29")

    def family(d):
        return 150.0 if d > ts("2026-11-03") else 100.0

    fill(conn, "x.probe.en.posts", 1000.0, first, ts("2026-11-17"))
    fill(conn, "x.family.anti-trans.en.posts", family, first, ts("2026-11-17"))
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-18") + HOUR)
    assert built["families"]["anti-trans"]["phases"]["after"] is not None
    assert built["robustness"]["anti-trans"]["placebo_share"] is None


def test_placebo_share_is_none_without_data(tmp_path):
    cfg = make_config()
    conn = new_db(tmp_path, cfg)
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-18") + HOUR)
    fam = built["families"]["anti-trans"]
    assert fam["daily"] == {} and fam["band"] is None
    assert fam["phases"] == {"before": None, "during": None, "after": None}
    assert built["robustness"]["anti-trans"]["placebo_share"] is None
    assert built["as_of"] is None


def test_freeze_increments_version(tmp_path):
    cfg = make_config()
    conn = new_db(tmp_path, cfg)
    populate(conn, cfg)
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-18") + HOUR)
    out = tmp_path / "studies"
    p1 = study.freeze(built, "first", out)
    p2 = study.freeze(built, "second", out)
    assert (p1.name, p2.name) == ("v1.json", "v2.json")
    assert p1.parent == out / "us-midterms-2026"
    assert json.loads(p2.read_text(encoding="utf-8"))["version"] == 2
    assert study.latest("us-midterms-2026", out)["note"] == "second"
    assert study.latest("none", out) is None
    (out / "us-midterms-2026" / "v7.json").write_text("{}", encoding="utf-8")
    assert study.freeze(built, "third", out).name == "v8.json"


def test_freeze_refuses_open_study(tmp_path):
    import pytest
    cfg = make_config()
    conn = new_db(tmp_path, cfg)
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-10"))
    with pytest.raises(ValueError):
        study.freeze(built, "x", tmp_path)


def test_term_band_with_enough_reference_days(tmp_path):
    cfg = make_config()
    conn = new_db(tmp_path, cfg)
    populate(conn, cfg)
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-18") + HOUR)
    for t in built["terms"]:
        lo, hi = t["band"]
        assert lo <= 100 <= hi  # the reference days average 100 by construction
    # the same rule as the families: analysis.band over the reference days
    a1 = {int(d): v for d, v in built["terms"][0]["daily"].items()}
    ref = built["reference"]
    assert built["terms"][0]["band"] == list(analysis.band(a1, ref["start"], ref["end"] + DAY))


def test_term_band_is_null_with_too_few_reference_days(tmp_path):
    cfg = make_config((("a1", "anti-trans"), ("a2", "anti-trans"), ("late", "anti-trans"), ("f1", "framing")))
    conn = new_db(tmp_path, cfg)
    populate(conn, make_config((("a1", "anti-trans"), ("a2", "anti-trans"), ("f1", "framing"))))
    # "late" starts on 12 Oct: 8 reference days (12-19 Oct), under the 14 a band needs
    fill(conn, "x.late.en.posts", noisy, ts("2026-10-12"), ts("2026-11-17"))
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-18") + HOUR)
    late = next(t for t in built["terms"] if t["id"] == "late")
    assert late["daily"] and late["band"] is None


def test_breadth_phases_on_synthetic_data(tmp_path):
    cfg = make_config()
    conn = new_db(tmp_path, cfg)
    populate(conn, cfg)  # term posts rise by half after the event day
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-18") + HOUR)
    ph = built["breadth"]["anti-trans"]["phases"]
    assert set(ph) == {"before", "during", "after"}
    assert abs(ph["before"] - 100) < 3
    # breadth is not weekday-adjusted: the event day is its one noisy day against the
    # reference mean (21 days of 10, 11, 12: mean 11)
    assert abs(ph["during"] - noisy(ts("2026-11-03")) / 11 * 100) < 0.5
    assert abs(ph["after"] - 150) < 5
    assert ph["after"] / ph["before"] > 1.4


def test_breadth_phases_are_null_without_data(tmp_path):
    cfg = make_config()
    conn = new_db(tmp_path, cfg)
    built = study.build(conn, cfg, the_study(), now=ts("2026-11-18") + HOUR)
    assert built["breadth"]["anti-trans"]["phases"] == {"before": None, "during": None, "after": None}
    assert all(t["band"] is None for t in built["terms"])
