"""Growth periods and board rankings shared by the Repos (tf.build) and Skills (tf.skills) builds.

Both boards keep one value per item per day (stars or installs). From that daily series each build
derives, per period p in PERIODS:

  p["1"|"7"|"30"] = {d: gain, b: baseline value, w: days actually covered, r: d / b,
                     g: rank on Top gains, q: rank on Fastest growing, n: rank on New (repos only)}

A period is offered only once the board's history covers it (`available_periods`), so "7d" appears
after 7 days of collection and "30d" after 30. Inside an offered period an item that joined later
uses its own oldest value and reports the shorter span in `w`.

Ranks are computed over every item before anything is filtered or trimmed, so the page can show an
item's board rank under any filter.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping

PERIODS = (1, 7, 30)
SPARK_DAYS = 7          # sparklines always show the last 7 days


def shift(date: str, days: int) -> str:
    return (dt.date.fromisoformat(date) + dt.timedelta(days=days)).isoformat()


def ndays(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def available_periods(first: str, date: str) -> list[int]:
    """Periods the history from `first` to `date` fully covers."""
    return [p for p in PERIODS if ndays(first, date) >= p]


def period_stats(series: list[tuple[str, int]], date: str, p: int) -> dict | None:
    """Gain over the last `p` days of an ascending (date, value) series that ends on `date`."""
    start = shift(date, -p)
    pts = [x for x in series if x[0] >= start]
    if not pts or pts[-1][0] != date:
        return None
    base_date, base = pts[0]
    w = ndays(base_date, date)
    if w <= 0:
        return None
    d = pts[-1][1] - base
    return {"d": d, "b": base, "w": w, **({"r": round(d / base, 5)} if base > 0 else {})}


def spark(series: list[tuple[str, int]], date: str) -> list[int]:
    start = shift(date, -SPARK_DAYS)
    return [v for d, v in series if d >= start]


def ranks(values: Mapping[str, float], tie: Mapping[str, float] | None = None) -> dict[str, int]:
    """1-based ranks, highest value first; ties go to the higher `tie` value, then the key."""
    tie = tie or {}
    order = sorted(values, key=lambda k: (-values[k], -tie.get(k, 0), k))
    return {k: i + 1 for i, k in enumerate(order)}


def add_periods(stats: dict[str, dict], series: dict[str, list[tuple[str, int]]], date: str,
                periods: list[int], rate_min_base: int, totals: Mapping[str, float],
                new: set[str] | None = None) -> None:
    """Fill stats[key]["p"][str(p)] with gain stats and the Top gains / Fastest growing / New ranks."""
    for p in periods:
        cur = {k: s for k in stats if (s := period_stats(series[k], date, p))}
        g = ranks({k: v["d"] for k, v in cur.items() if v["d"] > 0}, totals)
        q = ranks({k: v["r"] for k, v in cur.items() if v.get("r", 0) > 0 and v["b"] >= rate_min_base}, totals)
        n = ranks({k: cur[k]["d"] if k in cur else float("-inf") for k in (new or ())}, totals)
        for k in stats:
            v = dict(cur.get(k, {}))
            for name, board in (("g", g), ("q", q), ("n", n)):
                if k in board:
                    v[name] = board[k]
            if v:
                stats[k].setdefault("p", {})[str(p)] = v
