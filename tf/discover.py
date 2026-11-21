"""Discover established (>= discovery.min_stars) agent-ecosystem repos not yet tracked.

Two feeds, both deterministic (no LLM):
  1. GitHub search by topic   — `topic:<t> stars:>=N`, topics listed in sources.json
  2. github.com/trending       — daily/weekly pages, kept when description/topics match keywords

New repos are added straight to data/registry.json and probed for marker files.
Every repo on the *daily* trending page is also logged to data/gh-trending.json ({repo id: [dates]}),
so the page can say how many times a repo has been on GitHub Trending.
Usage: uv run python -m tf.discover [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys

import httpx

from .common import DATA, dump, load, now_iso, today
from .gh import REPO_FIELDS, GitHub, topics
from .probe import probe
from .sources import (
    TOPIC_TAGS,
    apply_files,
    entry_from_node,
    manual_tags,
    write_registry,
)

SEARCH = """query($q: String!, $after: String) {
  search(query: $q, type: REPOSITORY, first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on Repository { %s } }
  }
}""" % REPO_FIELDS
DEV_POPULAR = re.compile(r'Popular repo</div>\s*<h1[^>]*>\s*<a[^>]*href="/([A-Za-z0-9-]+/[A-Za-z0-9_.-]+)"')
TRENDING_LINK = re.compile(r'<h2 class="h3 lh-condensed">\s*<a[^>]*href="/([A-Za-z0-9-]+/[A-Za-z0-9_.-]+)"')


def search_topic(gh: GitHub, topic: str, min_stars: int) -> list[dict]:
    q = f"topic:{topic} stars:>={min_stars} archived:false fork:false"
    out, after = [], None
    for _ in range(10):  # search caps at 1000 results
        res = (gh.graphql(SEARCH, {"q": q, "after": after}).get("data") or {}).get("search")
        if not res:
            break
        out += [n for n in res["nodes"] if n]
        if not res["pageInfo"]["hasNextPage"]:
            break
        after = res["pageInfo"]["endCursor"]
    return out


def parse_trending(html: str) -> list[str]:
    return list(dict.fromkeys(TRENDING_LINK.findall(html)))


def parse_trending_devs(html: str) -> list[str]:
    return list(dict.fromkeys(DEV_POPULAR.findall(html)))


def trending_names(since: str) -> list[str]:
    r = httpx.get(f"https://github.com/trending?since={since}", headers={"User-Agent": "agent-trending"},
                  timeout=30, follow_redirects=True)
    r.raise_for_status()
    return parse_trending(r.text)


def trending_dev_repos(since: str) -> list[str]:
    """Popular repo of each developer on github.com/trending/developers."""
    r = httpx.get(f"https://github.com/trending/developers?since={since}", headers={"User-Agent": "agent-trending"},
                  timeout=30, follow_redirects=True)
    r.raise_for_status()
    return parse_trending_devs(r.text)


GH_TRENDING = DATA / "gh-trending.json"


def record_gh_trending(ids: list[str], date: str, path=GH_TRENDING) -> dict:
    """Add `date` to each repo's list of days on the daily GitHub Trending page (idempotent)."""
    log = load(path, {"repos": {}})
    for rid in ids:
        days = log["repos"].setdefault(rid, [])
        if date not in days:
            days.append(date)
            days.sort()
    log["updated"] = now_iso()
    dump(path, log, compact=True)
    return log


def discover(dry_run: bool = False, since: list[str] | None = None, topics_on: bool = True,
             dev_since: list[str] | None = None) -> list[str]:
    cfg = load(DATA / "sources.json")["discovery"]
    ov = load(DATA / "overrides.json", {"include": {}, "tags": {}, "block": []})
    blocked = {b.lower() for b in ov.get("block", [])}
    manual = manual_tags(ov)
    registry = load(DATA / "registry.json")
    repos: dict[str, dict] = registry["repos"]
    min_stars = cfg["min_stars"]
    gh = GitHub()

    found: dict[str, tuple[dict, dict, str]] = {}  # id -> (node, tag hints, source)

    for topic, hint in (cfg["topics"].items() if topics_on else []):
        try:
            nodes = search_topic(gh, topic, min_stars)
        except Exception as e:
            print(f"  ! topic {topic}: {e}", file=sys.stderr)
            continue
        new = 0
        for n in nodes:
            if n["id"] in repos:
                continue
            if n["id"] not in found:
                found[n["id"]] = (n, {"type": set(), "scope": set()}, f"discover:topic/{topic}")
                new += 1
            for k, v in hint.items():
                found[n["id"]][1][k].update(v)
        print(f"  topic {topic}: {len(nodes)} >= {min_stars}★, {new} new", file=sys.stderr)

    kw = re.compile(cfg["trending"]["keywords"], re.I)
    names: list[str] = []
    daily: list[str] = []
    fetched = 0
    for period in since or cfg["trending"]["since"]:
        try:
            got = trending_names(period)
            names += got
            if period == "daily":
                daily = got
            fetched += 1
        except Exception as e:  # scraping is best-effort
            print(f"  ! trending {period}: {e}", file=sys.stderr)
    if fetched and not names:
        print("::warning::github.com/trending parsed 0 repos — markup may have changed")
    origin = {n: "discover:trending" for n in names}
    dev_names: list[str] = []
    dev_fetched = 0
    for period in dev_since or cfg["trending"].get("developers_since", []):
        try:
            dev_names += trending_dev_repos(period)
            dev_fetched += 1
        except Exception as e:
            print(f"  ! trending developers {period}: {e}", file=sys.stderr)
    if dev_fetched and not dev_names:
        print("::warning::github.com/trending/developers parsed 0 repos — markup may have changed")
    for n in dev_names:
        origin.setdefault(n, "discover:trending-dev")
    print(f"  trending developers: {len(set(dev_names))} popular repos listed", file=sys.stderr)
    trending_new = 0
    resolved = gh.repos_by_name(origin)
    if daily and not dry_run:
        log = record_gh_trending([resolved[n]["id"] for n in daily if resolved.get(n)], today())
        print(f"  gh-trending.json: {len(daily)} repos on today's daily page, {len(log['repos'])} logged so far",
              file=sys.stderr)
    for name, n in resolved.items():
        if not n or n["id"] in repos or n["id"] in found or n["stargazerCount"] < min_stars:
            continue
        text = " ".join([n["nameWithOwner"], n.get("description") or "", *topics(n)])
        if kw.search(text) and not n["isFork"] and not n["isArchived"]:
            found[n["id"]] = (n, {"type": set(), "scope": set()}, origin[name])
            trending_new += 1
    print(f"  trending repos + developers: {trending_new} new", file=sys.stderr)

    added = []
    for rid, (n, hints, source) in found.items():
        if n["nameWithOwner"].lower() in blocked:
            continue
        tags = {"type": set(hints["type"]), "scope": set(hints["scope"])}
        for t in topics(n):
            if t in TOPIC_TAGS:
                k, v = TOPIC_TAGS[t]
                tags[k].add(v)
        entry = {"added": today(), **entry_from_node(n), "sources": [source],
                 "tags": {k: sorted(v) for k, v in tags.items()}}
        if override := manual.get(n["nameWithOwner"].lower()):
            entry["tags"] = {k: sorted(override.get(k, [])) for k in ("type", "scope")}
        repos[rid] = entry
        added.append(n["nameWithOwner"])

    if added:
        probe(gh, {rid: repos[rid] for rid in found if rid in repos})
        apply_files(repos, manual)
    print(f"discover: {len(added)} repos added", file=sys.stderr)
    if added and not dry_run:
        registry["repos"] = dict(sorted(repos.items(), key=lambda kv: kv[1]["name"].lower()))
        registry["count"] = len(repos)
        registry["updated"] = now_iso()
        write_registry(registry)
    return added


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--since", help="override trending periods (repos and developers), e.g. daily,weekly,monthly")
    ap.add_argument("--trending-only", action="store_true", help="skip topic search")
    a = ap.parse_args()
    periods = a.since.split(",") if a.since else None
    added = discover(a.dry_run, periods, not a.trending_only, periods)
    for name in added[:50]:
        print(name)
