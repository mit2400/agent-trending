"""Data gate: validates the working tree before the daily commit. Exit 1 on failure.

Usage: uv run python -m tf.gate [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

from .common import DATA, ROOT, SNAPSHOTS, load, today

ID = re.compile(r"^[A-Za-z0-9_=+/-]{8,}$")  # R_kgDO… or legacy MDEwOl… node ids
MIN_COVERAGE = 0.95      # today's repo count vs previous snapshot / active registry
MAX_DROP_SHARE = 0.01    # share of repos allowed to crash (0 stars or -50%)
MAX_REGISTRY_SHRINK = 0.05


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def previous_snapshot(date: str) -> dict | None:
    older = sorted(p for p in SNAPSHOTS.glob("*.json") if p.stem < date)
    return load(older[-1]) if older else None


def check(date: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []

    # 1. only data/ may change
    changed = [l[3:] for l in git("status", "--porcelain", "--untracked-files=all").splitlines()]
    outside = [p for p in changed if not p.startswith("data/")]
    if outside:
        errors.append(f"files changed outside data/: {outside[:5]}")

    # 2. never overwrite a committed snapshot
    if git("ls-files", f"data/snapshots/{date}.json").strip() and f"data/snapshots/{date}.json" in changed:
        errors.append(f"snapshot {date} is already committed and was modified")

    # 3. registry shape
    registry = load(DATA / "registry.json")
    repos = registry.get("repos", {}) if isinstance(registry, dict) else {}
    if not repos:
        errors.append("registry.json is empty or malformed")
    for rid, e in repos.items():
        if not ID.match(rid) or not isinstance(e.get("name"), str) or "/" not in e["name"]:
            errors.append(f"registry entry malformed: {rid}")
            break
        if not isinstance(e.get("tags"), dict):
            errors.append(f"registry entry without tags: {e.get('name')}")
            break
    head_reg = git("show", "HEAD:data/registry.json")
    if head_reg:
        prev_count = len(json.loads(head_reg).get("repos", {}))
        if prev_count and len(repos) < prev_count * (1 - MAX_REGISTRY_SHRINK):
            errors.append(f"registry shrank {prev_count} -> {len(repos)}")

    # 4. today's snapshot
    path = SNAPSHOTS / f"{date}.json"
    snap = load(path)
    if not snap:
        errors.append(f"missing snapshot {path.name}")
        return errors, warns
    stars = snap.get("stars")
    if snap.get("date") != date or not isinstance(stars, dict) or not stars:
        errors.append("snapshot malformed (date/stars)")
        return errors, warns
    bad = [k for k, v in stars.items() if not ID.match(k) or not isinstance(v, int) or v < 0]
    if bad:
        errors.append(f"snapshot has {len(bad)} invalid entries, e.g. {bad[:3]}")

    active = sum(1 for e in repos.values() if not e.get("archived"))
    if active and len(stars) < active * MIN_COVERAGE:
        errors.append(f"coverage {len(stars)}/{active} active repos < {MIN_COVERAGE:.0%}")

    # 5. compare with the previous snapshot
    prev = previous_snapshot(date)
    if prev:
        p = prev["stars"]
        if len(stars) < len(p) * MIN_COVERAGE:
            errors.append(f"repo count fell {len(p)} -> {len(stars)}")
        crashed = [k for k, v in stars.items() if k in p and p[k] >= 20 and (v == 0 or v < p[k] * 0.5)]
        if len(crashed) > len(stars) * MAX_DROP_SHARE:
            errors.append(f"{len(crashed)} repos lost >50% stars (limit {MAX_DROP_SHARE:.0%})")
        elif crashed:
            warns.append(f"{len(crashed)} repos lost >50% stars: {crashed[:5]}")

    # 6. page data built from today's snapshot (never preview data)
    trending = load(DATA / "trending.json")
    if not trending or trending.get("date") != date:
        errors.append("trending.json missing or not built for today")
    elif trending.get("preview"):
        errors.append("trending.json is preview data")
    elif trending.get("count", 0) < len(stars) * MIN_COVERAGE:
        errors.append(f"trending.json has {trending.get('count')} repos, snapshot has {len(stars)}")

    if snap.get("missing"):
        warns.append(f"{len(snap['missing'])} repos missing (deleted or private)")
    return errors, warns


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=today())
    errors, warns = check(ap.parse_args().date)
    for w in warns:
        print(f"WARN  {w}")
    for e in errors:
        print(f"FAIL  {e}")
    print("gate: FAILED" if errors else "gate: passed")
    sys.exit(1 if errors else 0)
