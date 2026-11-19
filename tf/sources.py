"""Re-parse curated awesome lists and sync data/registry.json.

Usage: uv run python -m tf.sources [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field

from .common import DATA, dump, load, now_iso, today
from .gh import GitHub, topics
from .probe import probe

LINK = re.compile(r"(?<![\w.])github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9_.-]{1,100})")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
HTML_TAG = re.compile(r"<[^>]+>")
MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")

# github.com/<owner>/... paths that are not repositories
RESERVED_OWNERS = {
    "about", "apps", "collections", "contact", "customer-stories", "enterprise", "explore",
    "features", "login", "marketplace", "notifications", "orgs", "pricing", "pulls", "issues",
    "readme", "search", "security", "settings", "site", "sponsors", "topics", "trending",
    "user-attachments", "users", "join", "signup", "codespaces", "copilot", "resources",
}

# repo topic -> tag heuristics (additive)
TOPIC_TAGS = {
    "mcp": ("type", "mcp"), "mcp-server": ("type", "mcp"), "mcp-servers": ("type", "mcp"),
    "model-context-protocol": ("type", "mcp"),
    "agent-skills": ("type", "skill"), "claude-skills": ("type", "skill"),
    "claude-code-plugin": ("type", "plugin"), "claude-code-plugins": ("type", "plugin"),
    "claude-code-marketplace": ("type", "marketplace"), "plugin-marketplace": ("type", "marketplace"),
    "subagents": ("type", "subagent"), "claude-code-subagents": ("type", "subagent"),
    "awesome-list": ("type", "list"),
    "claude-code": ("scope", "claude-code"), "codex": ("scope", "codex"),
    "openai-codex": ("scope", "codex"), "gemini-cli": ("scope", "gemini-cli"),
    "cursor": ("scope", "cursor"),
}


SPECIFIC_TYPES = {"marketplace", "plugin", "skill", "subagent", "mcp", "client", "framework", "list"}
GENERIC_TYPES = {"agent", "tool", "learning"}


def normalize_types(types: set[str]) -> set[str]:
    """Union of many lists over-tags; drop generic labels when a specific one exists."""
    return types - GENERIC_TYPES if types & SPECIFIC_TYPES else types


def manual_tags(ov: dict) -> dict[str, dict]:
    return {k.lower(): v for k, v in {**ov.get("include", {}), **ov.get("tags", {})}.items()}


def apply_files(repos: dict[str, dict], manual: dict[str, dict]) -> None:
    for e in repos.values():
        if e["name"].lower() in manual:
            continue
        types = set(e["tags"].get("type", [])) | set(e.get("files", []))
        e["tags"]["type"] = sorted(normalize_types(types))
        if not e["tags"].get("scope"):
            e["tags"]["scope"] = ["general"]


@dataclass
class Hit:
    sources: set[str] = field(default_factory=set)
    types: set[str] = field(default_factory=set)
    scopes: set[str] = field(default_factory=set)
    loose: bool = False  # True if any source lists it without a keyword requirement


def clean_heading(text: str) -> str:
    text = MD_LINK.sub(r"\1", HTML_TAG.sub("", text))
    return re.sub(r"[^\w\s&+./-]", "", text).strip().lower()


def parse_readme(text: str, self_name: str, cfg: dict, src: dict) -> dict[str, str]:
    """Return {owner/name: section heading} for every repo link outside skipped sections."""
    skip = [re.compile(p, re.I) for p in cfg["skip_sections"] + src.get("skip_sections", [])]
    stack: list[tuple[int, str]] = []
    found: dict[str, str] = {}
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = HEADING.match(line)
        if m:
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, clean_heading(m.group(2))))
        section = stack[-1][1] if stack else ""
        if any(p.search(section) for p in skip):
            continue
        for owner, name in LINK.findall(line):
            name = re.sub(r"(\.git|\.)+$", "", name)
            if not name or owner.lower() in RESERVED_OWNERS:
                continue
            full = f"{owner}/{name}"
            if full.lower() == self_name.lower():
                continue
            found.setdefault(full, section)
    return found


def section_type(section: str, rules: list[tuple[re.Pattern, str]]) -> str | None:
    for pat, typ in rules:
        if pat.search(section):
            return typ
    return None


def collect_hits(gh: GitHub, cfg: dict) -> dict[str, Hit]:
    rules = [(re.compile(r["match"], re.I), r["type"]) for r in cfg["section_rules"]]
    hits: dict[str, Hit] = defaultdict(Hit)
    lower_to_name: dict[str, str] = {}
    for src in cfg["sources"]:
        repo = src["repo"]
        try:
            text = gh.readme(repo)
        except Exception as e:  # one broken source must not kill the run
            print(f"  ! {repo}: {e}", file=sys.stderr)
            continue
        links = parse_readme(text, repo, cfg, src)
        default_types = src.get("tags", {}).get("type", [])
        scopes = src.get("tags", {}).get("scope", [])
        use_rules = src.get("section_rules", True)
        for full, section in links.items():
            key = lower_to_name.setdefault(full.lower(), full)
            h = hits[key]
            h.sources.add(repo)
            h.loose |= not src.get("require_keywords", False)
            h.scopes.update(scopes)
            if default_types:
                h.types.update(default_types)
            elif use_rules and (t := section_type(section, rules)):
                h.types.add(t)
        # the curated list itself is tracked too
        key = lower_to_name.setdefault(repo.lower(), repo)
        hits[key].sources.add(repo)
        hits[key].loose = True
        hits[key].types.add("list")
        hits[key].scopes.update(scopes)
        print(f"  {repo}: {len(links)} links", file=sys.stderr)
    return hits


def entry_from_node(node: dict) -> dict:
    return {
        "name": node["nameWithOwner"],
        "description": (node.get("description") or "").strip()[:300],
        "language": (node.get("primaryLanguage") or {}).get("name"),
        "topics": topics(node),
        "created": node["createdAt"][:10],
        "archived": node["isArchived"],
    }


def sync(dry_run: bool = False) -> dict:
    cfg = load(DATA / "sources.json")
    ov = load(DATA / "overrides.json", {"include": {}, "tags": {}, "block": []})
    registry = load(DATA / "registry.json", {"repos": {}})
    repos: dict[str, dict] = registry["repos"]
    before = json.loads(json.dumps(repos))  # deep copy to detect real changes
    blocked = {b.lower() for b in ov.get("block", [])}

    gh = GitHub()
    hits = collect_hits(gh, cfg)
    for name in ov.get("include", {}):
        hits.setdefault(name, Hit()).loose = True
    keywords = re.compile(cfg["discovery"]["trending"]["keywords"], re.I)

    names = [n for n in hits if n.lower() not in blocked]
    print(f"resolving {len(names)} repos …", file=sys.stderr)
    nodes = gh.repos_by_name(names)

    manual = manual_tags(ov)
    forced = {k.lower() for k in ov.get("include", {})}
    stats = defaultdict(int)
    seen: set[str] = set()
    for name in names:
        node = nodes.get(name)
        if node is None:
            stats["missing"] += 1
            continue
        rid = node["id"]
        canon = node["nameWithOwner"]
        if rid in seen:  # same repo linked under an old name
            prev = repos.get(rid)
            if prev:
                prev["sources"] = sorted(set(prev["sources"]) | hits[name].sources)
            continue
        is_forced = name.lower() in forced or canon.lower() in forced
        if canon.lower() in blocked:
            stats["blocked"] += 1
            continue
        if rid not in repos and not is_forced:
            if node["isFork"] or node["isArchived"]:
                stats["skip_fork_or_archived"] += 1
                continue
            if node["stargazerCount"] < cfg["min_stars"]:
                stats["skip_low_stars"] += 1
                continue
            text = " ".join([canon, node.get("description") or "", *topics(node)])
            if not hits[name].loose and not keywords.search(text):
                stats["skip_offtopic"] += 1
                continue
        seen.add(rid)

        h = hits[name]
        tags = {"type": set(h.types), "scope": set(h.scopes)}
        for t in topics(node):
            if t in TOPIC_TAGS:
                k, v = TOPIC_TAGS[t]
                tags[k].add(v)
        tags["type"] = normalize_types(tags["type"])
        override = manual.get(canon.lower()) or manual.get(name.lower())
        if override:
            tags = {k: set(override.get(k, [])) for k in ("type", "scope")}

        entry = repos.get(rid) or {"added": today()}
        if rid not in repos:
            stats["added"] += 1
        entry.update(entry_from_node(node))
        entry["sources"] = sorted(h.sources)
        entry["tags"] = {k: sorted(v) for k, v in tags.items()}
        repos[rid] = entry

    # prune: every tracked repo must hold >= min_stars (manual includes exempt)
    fresh = {nodes[n]["id"]: nodes[n]["stargazerCount"] for n in names if nodes.get(n)}
    rest = [rid for rid in repos if rid not in fresh]
    fresh.update({rid: n["stargazerCount"] for rid, n in gh.repos_by_id(rest, "id stargazerCount").items() if n})
    for rid in list(repos):
        e = repos[rid]
        if e["name"].lower() in forced or rid not in fresh:
            continue
        if fresh[rid] < cfg["min_stars"]:
            del repos[rid]
            stats["pruned"] += 1

    probed = probe(gh, repos)
    print(f"probed {probed} new repos for marker files", file=sys.stderr)
    apply_files(repos, manual)
    repos = dict(sorted(repos.items(), key=lambda kv: kv[1]["name"].lower()))
    changed = repos != before
    registry = {"updated": now_iso() if changed else registry.get("updated", now_iso()), "count": len(repos), "repos": repos}
    print(f"registry: {len(repos)} repos  {dict(stats)}  changed={changed}", file=sys.stderr)
    if not dry_run:
        write_registry(registry)
    return registry


def write_registry(registry: dict) -> None:
    """One repo per line: readable diffs without the bloat of full indentation."""
    lines = ["{", f'  "updated": {json.dumps(registry["updated"])},', f'  "count": {registry["count"]},', '  "repos": {']
    items = list(registry["repos"].items())
    for i, (rid, entry) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        lines.append(f"    {json.dumps(rid)}: {json.dumps(entry, ensure_ascii=False, separators=(',', ':'))}{comma}")
    lines += ["  }", "}"]
    (DATA / "registry.json").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sync(ap.parse_args().dry_run)
