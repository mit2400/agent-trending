"""Build data/trending.json from snapshots + registry.

Per repo, the baseline is the snapshot from `date - 7d`; when tracking is younger than
that (or the repo joined later), the oldest snapshot inside the window is used instead.

Usage: uv run python -m tf.build [--snapshots DIR] [--date YYYY-MM-DD] [--preview]
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter
from pathlib import Path

from .common import DATA, SNAPSHOTS, dump, load, now_iso

WINDOW = 7
NEW_REPO_DAYS = 30      # repos created this recently count as "new"
RATE_MIN_BASE = 100     # % ranking only considers repos with at least this many baseline stars
DESC_MAX = 160


def days(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def build(snap_dir: Path = SNAPSHOTS, date: str | None = None, preview: bool = False) -> dict:
    files = sorted(p for p in snap_dir.glob("*.json") if date is None or p.stem <= date)
    if not files:
        raise SystemExit(f"no snapshots in {snap_dir}")
    latest = load(files[-1])
    date = latest["date"]
    start = (dt.date.fromisoformat(date) - dt.timedelta(days=WINDOW)).isoformat()
    window = [load(p) for p in files if p.stem >= start]
    tracking_start = files[0].stem
    first_seen = set(load(files[0])["stars"])  # repos present when tracking began

    registry = load(DATA / "registry.json")["repos"]
    cur_stars = latest["stars"]
    out = []
    for rid, e in registry.items():
        if rid not in cur_stars:
            continue
        series = [(s["date"], s["stars"][rid]) for s in window if rid in s["stars"]]
        base_date, base = series[0]
        stars = cur_stars[rid]
        wd = days(base_date, date)
        delta = stars - base if wd > 0 else None
        rate = round(delta / base, 5) if delta is not None and base > 0 else None
        created_recently = days(e["created"], date) <= NEW_REPO_DAYS
        joined_recently = rid not in first_seen and days(e["added"], date) <= WINDOW
        out.append({
            "id": rid,
            "name": e["name"],
            "desc": e.get("description", "")[:DESC_MAX],
            "lang": e.get("language"),
            "type": e["tags"].get("type", []),
            "scope": e["tags"].get("scope", []),
            "created": e["created"],
            "stars": stars,
            "base": base,
            "delta": delta,
            "rate": rate,
            "window": wd,
            "spark": [n for _, n in series],
            "new": created_recently or joined_recently,
        })
    out.sort(key=lambda r: (r["delta"] is None, -(r["delta"] or 0), -r["stars"]))

    sources = load(DATA / "sources.json")["sources"]
    trending = {
        "generated_at": now_iso(),
        "date": date,
        "preview": preview,
        "window_max": WINDOW,
        "tracking_start": tracking_start,
        "baseline_date": window[0]["date"],
        "baseline_collected_at": window[0]["collected_at"],
        "latest_collected_at": latest["collected_at"],
        "snapshots_in_window": len(window),
        "window_dates": [s["date"] for s in window],  # spark arrays are right-aligned to these
        "rate_min_base": RATE_MIN_BASE,
        "new_repo_days": NEW_REPO_DAYS,
        "count": len(out),
        "counts": {
            "type": dict(Counter(t for r in out for t in r["type"]).most_common()),
            "scope": dict(Counter(t for r in out for t in r["scope"]).most_common()),
        },
        "sources": [s["repo"] for s in sources],
        "repos": out,
    }
    dump(DATA / "trending.json", trending, compact=True)
    movers = sum(1 for r in out if r["delta"])
    print(f"trending.json: {len(out)} repos, {movers} moved, window {window[0]['date']}..{date}", file=sys.stderr)
    return trending


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    ap.add_argument("--date")
    ap.add_argument("--preview", action="store_true", help="mark output as preview/test data")
    a = ap.parse_args()
    build(a.snapshots, a.date, a.preview)
