"""Index, composite and breadth measures. Pure functions on dicts.

Conventions:
- Hourly points are stamped at the END of their hour (UTC seconds), so the point
  stamped `ts` covers the hour starting at `ts - 3600`.
- Day keys are UTC day starts (seconds).
- A reference period is `ref_start <= day < ref_end`: the end is exclusive.
- Unknown values are absent from the returned dicts, or None; never 0.
"""

import statistics

HOUR = 3600
DAY = 86400
WEEK = 7 * DAY
MIN_REFERENCE_DAYS = 14


def _in_reference(days, ref_start: int, ref_end: int) -> list[int]:
    return [d for d in days if ref_start <= d < ref_end]


def _weekday(day: int) -> int:
    return (day // DAY + 3) % 7  # 1970-01-01 was a Thursday; Monday = 0


def daily_totals(points: list[tuple[int, float]], min_hours: int = 20) -> dict[int, float]:
    """UTC day start -> sum of its hourly points; days with fewer than `min_hours` points are absent.

    A point stamped `ts` belongs to the hour starting `ts - 3600`, so the 23:00-24:00
    hour (stamped 00:00 next day) counts toward the previous day.
    """
    sums: dict[int, float] = {}
    counts: dict[int, int] = {}
    for ts, value in points:
        day = ((ts - HOUR) // DAY) * DAY
        sums[day] = sums.get(day, 0.0) + value
        counts[day] = counts.get(day, 0) + 1
    return {d: s for d, s in sums.items() if counts[d] >= min_hours}


def rate(series: list[tuple[int, float]], probe: list[tuple[int, float]],
         min_hours: int = 20) -> dict[int, float]:
    """UTC day start -> the series' total / the probe's total, both summed over the same hours.

    Takes hourly points (stamped at each hour's end). Only hours present in both the
    series and the probe count, so a series missing some hours of a day is compared with
    the probe over those same hours, not the whole day. A day needs `min_hours` shared
    hours and a positive probe total; otherwise it is absent.
    """
    probe_at = dict(probe)
    sums: dict[int, list[float]] = {}
    for ts, value in series:
        if ts not in probe_at:
            continue
        day = ((ts - HOUR) // DAY) * DAY
        acc = sums.setdefault(day, [0.0, 0.0, 0])
        acc[0] += value
        acc[1] += probe_at[ts]
        acc[2] += 1
    return {d: s / p for d, (s, p, n) in sums.items() if n >= min_hours and p > 0}


def weekday_index(daily: dict[int, float], ref_start: int, ref_end: int) -> dict[int, float]:
    """Each day / the mean of the same weekday's days in the reference period x 100.

    Reference period is ref_start <= day < ref_end (UTC day starts). A day is absent
    when the reference has no day of that weekday, or that mean is not positive.
    """
    by_weekday: dict[int, list[float]] = {}
    for d in _in_reference(daily, ref_start, ref_end):
        by_weekday.setdefault(_weekday(d), []).append(daily[d])
    means = {w: sum(v) / len(v) for w, v in by_weekday.items()}
    out = {}
    for d, v in daily.items():
        m = means.get(_weekday(d))
        if m is not None and m > 0:
            out[d] = v / m * 100
    return out


def _quantile(sorted_vs: list[float], q: float) -> float:
    pos = q * (len(sorted_vs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vs) - 1)
    return sorted_vs[lo] + (sorted_vs[hi] - sorted_vs[lo]) * (pos - lo)


def band(index: dict[int, float], ref_start: int, ref_end: int) -> tuple[float, float] | None:
    """5th and 95th percentiles of the reference days' index (ref_start <= day < ref_end).

    None with fewer than 14 reference days.
    """
    vs = sorted(index[d] for d in _in_reference(index, ref_start, ref_end))
    if len(vs) < MIN_REFERENCE_DAYS:
        return None
    return _quantile(vs, 0.05), _quantile(vs, 0.95)


def hourly_ratio(hours: dict[int, float]) -> dict[int, float]:
    """Each hour vs the mean of the same weekday-hour 1-3 weeks earlier (2 of 3 needed), x 100."""
    out = {}
    for h, v in hours.items():
        past = [hours[h - w * WEEK] for w in (1, 2, 3) if h - w * WEEK in hours]
        if len(past) >= 2:
            base = sum(past) / len(past)
            if base > 0:
                out[h] = v / base * 100
    return out


def breadth(
    term_rates: dict[str, dict[int, float]], ref_start: int, ref_end: int
) -> tuple[dict[int, float], list[str]]:
    """EPU-style breadth index. Returns (index by day, sorted ids left out).

    Each term's daily rate is divided by the sample standard deviation of its
    reference-period rates (ref_start <= day < ref_end); the day's value averages
    the scaled rates of the terms present that day; the series is then rescaled so
    its mean over the reference days is 100. A term with fewer than 14 reference
    days or a zero SD is left out. If every term is left out, returns ({}, all ids).
    Likewise, if the combined series has no reference days or a reference mean of 0,
    every id is returned as left out.
    """
    scaled: dict[str, dict[int, float]] = {}
    left_out: list[str] = []
    for term, rates in term_rates.items():
        ref = [rates[d] for d in _in_reference(rates, ref_start, ref_end)]
        sd = statistics.stdev(ref) if len(ref) >= MIN_REFERENCE_DAYS else 0.0
        if sd > 0:
            scaled[term] = {d: v / sd for d, v in rates.items()}
        else:
            left_out.append(term)
    left_out.sort()

    sums: dict[int, float] = {}
    counts: dict[int, int] = {}
    for rates in scaled.values():
        for d, v in rates.items():
            sums[d] = sums.get(d, 0.0) + v
            counts[d] = counts.get(d, 0) + 1
    series = {d: sums[d] / counts[d] for d in sums}

    ref_vals = [series[d] for d in _in_reference(series, ref_start, ref_end)]
    mean = sum(ref_vals) / len(ref_vals) if ref_vals else 0.0
    if not series or mean <= 0:
        return {}, sorted(term_rates)
    return {d: v / mean * 100 for d, v in series.items()}, left_out
