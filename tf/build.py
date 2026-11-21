"""Build data/trending.json from snapshots + registry.

Gains, growth and ranks per period (1, 7, 30 days) come from tf.rank, shared with the Skills
board; only the last 30 days of snapshots are read.

Usage: uv run python -m tf.build [--snapshots DIR] [--date YYYY-MM-DD] [--preview]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .common import DATA, SNAPSHOTS, dump, load, now_iso
from .rank import PERIODS, SPARK_DAYS, add_periods, available_periods, ndays, ranks, shift, spark

JOINED_DAYS = 7        # repos added to the registry this recently (after tracking began) count as "new"
NEW_REPO_DAYS = 30      # repos created this recently count as "new"
RATE_MIN_BASE = 100     # % ranking only considers repos with at least this many baseline stars
DESC_MAX = 160


def source_credits(cfg: dict, overrides: dict, registry: dict, live: dict) -> dict:
    """Where tracked repos come from, with how many currently tracked repos each one supplied."""
    counts: Counter = Counter()
    for rid, e in registry.items():
        if rid in live:
            counts.update(set(e.get("sources", [])))
    topic_n = sum(n for k, n in counts.items() if k.startswith("discover:topic/"))
    disc = cfg["discovery"]
    topic_list = list(disc["topics"])
    manual = {k.lower() for k in overrides.get("include", {})}
    return {
        "min_stars": cfg["min_stars"],
        "discovery": [
            {"label": "GitHub Trending — repos", "url": "https://github.com/trending",
             "count": counts["discover:trending"]},
            {"label": "GitHub Trending — developers' popular repos", "url": "https://github.com/trending/developers",
             "count": counts["discover:trending-dev"]},
            {"label": f"GitHub topics ({len(topic_list)})", "url": f"https://github.com/topics/{topic_list[0]}",
             "detail": ", ".join(topic_list), "count": topic_n},
            {"label": "Manual picks", "url": "https://github.com/mit2400/agent-trending/blob/main/data/overrides.json",
             "count": sum(1 for rid, e in registry.items() if rid in live and e["name"].lower() in manual)},
        ],
        "curated": sorted(
            ({"repo": s["repo"], "count": counts[s["repo"]]} for s in cfg["sources"]),
            key=lambda s: -s["count"]),
    }


def gh_trending_fields(days: list[str], date: str) -> dict:
    """`ght`: times on GitHub Trending up to `date`, only for repos that are on it on `date`."""
    seen = [d for d in days if d <= date]
    return {"ght": len(seen)} if date in seen else {}


def build(snap_dir: Path = SNAPSHOTS, date: str | None = None, preview: bool = False, write: bool = True) -> dict:
    files = sorted(p for p in snap_dir.glob("*.json") if date is None or p.stem <= date)
    if not files:
        raise SystemExit(f"no snapshots in {snap_dir}")
    latest = load(files[-1])
    date = latest["date"]
    tracking_start = files[0].stem
    # only the last max(PERIODS) days are read; older snapshots stay in the repo as history
    snaps = [load(p) for p in files if p.stem >= shift(date, -max(PERIODS))]
    prev = snaps[-2] if len(snaps) > 1 else None
    first_seen = set(load(files[0])["stars"])  # repos present when tracking began
    periods = available_periods(tracking_start, date)

    registry = load(DATA / "registry.json")["repos"]
    pushed = load(DATA / "activity.json", {}).get("pushed", {})
    # skills.sh skills published from each tracked repo (written by `tf.skills build`, if present)
    repo_skills = (load(DATA / "skills.json") or {}).get("by_repo", {})
    # days each repo was on the daily GitHub Trending page (written by `tf.discover`)
    gh_trending = (load(DATA / "gh-trending.json") or {}).get("repos", {})
    cur_stars = latest["stars"]
    live = [rid for rid in registry if rid in cur_stars]

    series = {rid: [(s["date"], s["stars"][rid]) for s in snaps if rid in s["stars"]] for rid in live}
    new = set()
    for rid in live:
        e = registry[rid]
        created_recently = ndays(e["created"], date) <= NEW_REPO_DAYS
        # preview snapshots predate most registry additions; don't flag those as new
        joined_recently = not preview and rid not in first_seen and ndays(e["added"], date) <= JOINED_DAYS
        if created_recently or joined_recently:
            new.add(rid)
    stats: dict[str, dict] = {rid: {} for rid in live}
    add_periods(stats, series, date, periods, RATE_MIN_BASE, cur_stars, new)
    rank_all = ranks(cur_stars)
    prev_rank_all = ranks(prev["stars"]) if prev else {}

    out = []
    for rid in live:
        e = registry[rid]
        out.append({
            "id": rid,
            "name": e["name"],
            "desc": e.get("description", "")[:DESC_MAX],
            "lang": e.get("language"),
            "type": e["tags"].get("type", []),
            "created": e["created"],
            "pushed": pushed.get(rid),
            "stars": cur_stars[rid],
            "ar": rank_all[rid],
            **({"par": prev_rank_all[rid]} if rid in prev_rank_all else {}),
            "p": stats[rid].get("p", {}),
            "spark": spark(series[rid], date),
            "new": rid in new,
            **({"skills": repo_skills[e["name"]]} if e["name"] in repo_skills else {}),
            **gh_trending_fields(gh_trending.get(rid, []), date),
        })
    out.sort(key=lambda r: r["ar"])

    cfg = load(DATA / "sources.json")
    overrides = load(DATA / "overrides.json", {"include": {}})
    trending = {
        "generated_at": now_iso(),
        "date": date,
        "preview": preview,
        "tracking_start": tracking_start,
        "periods": periods,
        "collected_at": latest["collected_at"],
        "prev_collected_at": prev["collected_at"] if prev else None,
        "spark_dates": [s["date"] for s in snaps if s["date"] >= shift(date, -SPARK_DAYS)],
        "gh_trending_since": min((d[0] for d in gh_trending.values() if d), default=None),
        "rate_min_base": RATE_MIN_BASE,
        "new_repo_days": NEW_REPO_DAYS,
        "count": len(out),
        "counts": {"type": dict(Counter(t for r in out for t in r["type"]).most_common())},
        "sources": source_credits(cfg, overrides, registry, cur_stars),
        "repos": out,
    }
    if not write:
        return trending
    dump(DATA / "trending.json", trending, compact=True)
    print(f"trending.json: {len(out)} repos, periods {periods}, {len(snaps)} days read", file=sys.stderr)
    return trending


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    ap.add_argument("--date")
    ap.add_argument("--preview", action="store_true", help="mark output as preview/test data")
    a = ap.parse_args()
    build(a.snapshots, a.date, a.preview)
