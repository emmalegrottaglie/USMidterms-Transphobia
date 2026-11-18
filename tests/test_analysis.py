import pytest

from monitor import analysis

DAY = 86400
HOUR = 3600
WEEK = 7 * DAY


def day_points(day, n=24, value=1.0):
    """n hourly points for the UTC day starting at `day`, each stamped at the end of its hour."""
    return [(day + (h + 1) * HOUR, value) for h in range(n)]


def test_daily_totals_drop_short_days():
    pts = day_points(0, n=19) + day_points(DAY, n=20)
    assert analysis.daily_totals(pts) == {DAY: 20.0}


def test_daily_totals_end_of_hour_stamp_belongs_to_previous_day():
    # Hour 23:00-24:00 of day 0 is stamped at DAY (00:00 next day) and counts toward day 0.
    pts = day_points(0, n=24) + [(DAY + HOUR * (h + 1), 1.0) for h in range(23)]
    # Day 0 gets hours stamped 1:00..24:00 (24 points); day 1 gets 23 points here.
    totals = analysis.daily_totals(pts)
    assert totals[0] == 24.0
    assert totals[DAY] == 23.0
    # A lone point stamped exactly at midnight must not start a new day.
    assert analysis.daily_totals([(DAY, 5.0)], min_hours=1) == {0: 5.0}


def _day(day, value, hours=range(24)):
    """Hourly points for the given hours of a day, stamped at each hour's end."""
    return [(day + (h + 1) * HOUR, value(h) if callable(value) else value) for h in hours]


def test_rate_skips_days_without_probe():
    series = _day(0, 10.0) + _day(DAY, 20.0) + _day(2 * DAY, 30.0)
    probe = _day(0, 100.0) + _day(DAY, 0.0)
    assert analysis.rate(series, probe) == {0: 0.1}


def test_rate_compares_series_and_probe_over_the_same_hours():
    # The term misses the last 3 hours of the day, when the probe is four times busier.
    series = _day(0, 10.0, range(21))
    probe = _day(0, lambda h: 400.0 if h >= 21 else 100.0)
    assert analysis.rate(series, probe) == {0: 210 / 2100}  # 21 shared hours, not 24 probe hours
    # A probe gap counts the same way: the series hour it lacks is left out too.
    assert analysis.rate(_day(0, 10.0), _day(0, 100.0, range(22))) == {0: 0.1}


def test_rate_needs_twenty_shared_hours():
    probe = _day(0, 100.0)
    assert analysis.rate(_day(0, 10.0, range(20)), probe) == {0: 0.1}
    assert analysis.rate(_day(0, 10.0, range(19)), probe) == {}
    # 20 series hours and 20 probe hours, but only 16 of them shared
    assert analysis.rate(_day(0, 10.0, range(20)), _day(0, 100.0, range(4, 24))) == {}


def test_weekday_index_uses_same_weekday():
    mondays = [4 * DAY + i * WEEK for i in range(4)]  # 1970-01-05 was a Monday
    daily = {d: 10.0 for d in mondays}
    later_monday = 4 * DAY + 10 * WEEK
    tuesday = later_monday + DAY
    daily[later_monday] = 15.0
    daily[tuesday] = 15.0
    out = analysis.weekday_index(daily, mondays[0], mondays[-1] + DAY)
    assert out[later_monday] == pytest.approx(150.0)
    assert tuesday not in out


def test_weekday_index_reference_end_is_exclusive():
    daily = {0: 10.0, WEEK: 30.0}
    # Only day 0 is in the reference; WEEK is excluded as ref_end.
    out = analysis.weekday_index(daily, 0, WEEK)
    assert out[0] == pytest.approx(100.0)
    assert out[WEEK] == pytest.approx(300.0)


def test_band_needs_14_reference_days():
    idx13 = {i * DAY: 100.0 + i for i in range(13)}
    assert analysis.band(idx13, 0, 13 * DAY) is None
    idx14 = {i * DAY: 100.0 + i for i in range(14)}
    lo, hi = analysis.band(idx14, 0, 14 * DAY)
    assert lo == pytest.approx(100.65)
    assert hi == pytest.approx(112.35)
    # a day outside the reference is ignored
    idx14[20 * DAY] = 1000.0
    assert analysis.band(idx14, 0, 14 * DAY) == (lo, hi)


def test_hourly_ratio_needs_two_of_three_prior_weeks():
    base = 10 * WEEK
    hours = {base - WEEK: 10.0, base - 2 * WEEK: 20.0, base: 30.0}
    assert analysis.hourly_ratio(hours)[base] == pytest.approx(200.0)
    # only one prior week: no value
    assert base - WEEK not in analysis.hourly_ratio(hours)
    only_one = {base - WEEK: 10.0, base: 30.0}
    assert analysis.hourly_ratio(only_one) == {}
    # zero baseline: no value, no error
    zero = {base - WEEK: 0.0, base - 2 * WEEK: 0.0, base: 5.0}
    assert analysis.hourly_ratio(zero) == {}


def _term(base, wobble, days=14, extra=None):
    rates = {i * DAY: base + (wobble if i % 2 else -wobble) for i in range(days)}
    if extra:
        rates.update(extra)
    return rates


def test_breadth_equal_weight():
    spike = 14 * DAY
    a = _term(11.0, 1.0, extra={spike: 13.2})
    b = _term(110.0, 10.0, extra={spike: 132.0})
    idx, left = analysis.breadth({"a": a, "b": b}, 0, 14 * DAY)
    assert left == []
    assert idx[spike] == pytest.approx(120.0)
    ref_mean = sum(idx[i * DAY] for i in range(14)) / 14
    assert ref_mean == pytest.approx(100.0)
    b2 = {d: v * 2 for d, v in b.items()}
    idx2, _ = analysis.breadth({"a": a, "b": b2}, 0, 14 * DAY)
    assert idx2[spike] == pytest.approx(120.0)


def test_breadth_leaves_out_constant_term():
    flat = {i * DAY: 5.0 for i in range(14)}
    varied = _term(11.0, 1.0)
    idx, left = analysis.breadth({"flat": flat, "varied": varied}, 0, 14 * DAY)
    assert left == ["flat"]
    assert sum(idx[i * DAY] for i in range(14)) / 14 == pytest.approx(100.0)


def test_breadth_leaves_out_short_reference_and_handles_all_left_out():
    short = _term(11.0, 1.0, days=13)
    assert analysis.breadth({"short": short}, 0, 14 * DAY) == ({}, ["short"])
    assert analysis.breadth({}, 0, 14 * DAY) == ({}, [])


def test_breadth_scales_each_term_by_its_reference_sd():
    # a alternates 10/12 (mean 11, deviation 1); b alternates 80/140 (mean 110, deviation 30).
    # Both have the same sample-SD factor k = sqrt(14/13), so SDs are 1k and 30k.
    # Spike day: a = 13.2 (+20%), b = 165 (+50%).
    # Scaled reference means: a 11/k, b 110/(30k) = 3.6667/k; combined mean 7.3333/k.
    # Scaled spike: a 13.2/k, b 165/(30k) = 5.5/k; average 9.35/k.
    # Breadth = 9.35 / 7.3333 * 100 = 127.5. A raw average would give 89.1 / 60.5 * 100 = 147.3.
    spike = 14 * DAY
    a = _term(11.0, 1.0, extra={spike: 13.2})
    b = _term(110.0, 30.0, extra={spike: 165.0})
    idx, left = analysis.breadth({"a": a, "b": b}, 0, 14 * DAY)
    assert left == []
    assert idx[spike] == pytest.approx(127.5)
    b2 = {d: v * 2 for d, v in b.items()}
    idx2, _ = analysis.breadth({"a": a, "b": b2}, 0, 14 * DAY)
    assert idx2[spike] == pytest.approx(127.5)


def test_breadth_keeps_term_with_exactly_14_reference_days():
    idx, left = analysis.breadth({"t": _term(11.0, 1.0, days=14)}, 0, 14 * DAY)
    assert left == []
    assert len(idx) == 14


def test_weekday_index_leaves_out_day_when_weekday_reference_mean_is_zero():
    # Day 0 and WEEK share a weekday; the reference (day 0 only, plus DAY) has mean 0 for it.
    daily = {0: 0.0, WEEK: 5.0, DAY: 10.0}
    out = analysis.weekday_index(daily, 0, 2 * DAY)
    assert 0 not in out and WEEK not in out
    assert out[DAY] == pytest.approx(100.0)


def test_hourly_ratio_uses_mean_of_three_earlier_weeks():
    base = 10 * WEEK
    hours = {base - WEEK: 10.0, base - 2 * WEEK: 20.0, base - 3 * WEEK: 30.0, base: 40.0}
    assert analysis.hourly_ratio(hours)[base] == pytest.approx(200.0)
