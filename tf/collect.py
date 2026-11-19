"""Collect today's star counts for every active registry repo.

Writes data/snapshots/YYYY-MM-DD.json = {date, collected_at, stars: {nodeId: n}, missing: [nodeId]}
Usage: uv run python -m tf.collect [--date YYYY-MM-DD] [--force]
"""

from __future__ import annotations

import argparse
import sys

from .common import DATA, SNAPSHOTS, dump, load, now_iso, today
from .gh import GitHub

LIGHT_FIELDS = "id stargazerCount"


def collect(date: str, force: bool = False) -> dict:
    path = SNAPSHOTS / f"{date}.json"
    if path.exists() and not force:
        print(f"{path.name} already collected; skipping (use --force to overwrite)", file=sys.stderr)
        return load(path)

    registry = load(DATA / "registry.json")
    ids = [rid for rid, e in registry["repos"].items() if not e.get("archived")]
    nodes = GitHub().repos_by_id(ids, LIGHT_FIELDS)

    stars = {rid: n["stargazerCount"] for rid, n in nodes.items() if n}
    missing = sorted(rid for rid, n in nodes.items() if not n)
    snap = {"date": date, "collected_at": now_iso(), "stars": stars, "missing": missing}
    dump(path, snap, compact=True)
    print(f"{path.name}: {len(stars)} repos, {len(missing)} missing", file=sys.stderr)
    return snap


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=today())
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    collect(a.date, a.force)
