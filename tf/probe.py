"""File-based type detection: look for marker files in each repo's default branch.

Results are stored per repo as `files` (types implied by marker files) plus a
`probed` date, so each repo is probed once; tag computation merges `files` in.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from .common import today
from .gh import GitHub

# alias -> (path at HEAD, implied type)
MARKERS = {
    "mk": (".claude-plugin/marketplace.json", "marketplace"),
    "pl": (".claude-plugin/plugin.json", "plugin"),
    "gx": ("gemini-extension.json", "plugin"),
    "sk": ("SKILL.md", "skill"),
    "sd": ("skills", "skill"),
}
BATCH = 25


MIN_MARKETPLACE_PLUGINS = 3  # single-plugin repos ship a marketplace.json just for installation


def _query(ids: list[str]) -> str:
    def sel(alias: str) -> str:
        return "{ ... on Blob { text } }" if alias == "mk" else "{ id }"
    fields = " ".join(f'{a}: object(expression: {json.dumps("HEAD:" + p)}) {sel(a)}' for a, (p, _) in MARKERS.items())
    parts = [f"r{i}: node(id: {json.dumps(rid)}) {{ ... on Repository {{ {fields} }} }}" for i, rid in enumerate(ids)]
    return "query {" + "\n".join(parts) + "}"


def marketplace_size(text: str | None) -> int:
    try:
        plugins = json.loads(text or "").get("plugins", [])
        return len(plugins) if isinstance(plugins, list) else 0
    except (ValueError, AttributeError):
        return 0


def probe(gh: GitHub, repos: dict[str, dict], only_unprobed: bool = True) -> int:
    """Mutates registry entries in place; returns how many repos were probed."""
    ids = [rid for rid, e in repos.items() if not e.get("archived") and (not only_unprobed or "probed" not in e)]
    if not ids:
        return 0
    chunks = [ids[i : i + BATCH] for i in range(0, len(ids), BATCH)]

    def run(chunk: list[str]) -> dict[str, dict | None]:
        try:
            data = gh.graphql(_query(chunk)).get("data") or {}
        except RuntimeError as e:  # unprobed repos are retried on the next run
            print(f"  ! probe batch skipped: {e}", file=sys.stderr)
            return {}
        return {rid: data.get(f"r{i}") for i, rid in enumerate(chunk)}

    date = today()
    with ThreadPoolExecutor(4) as pool:
        for k, res in enumerate(pool.map(run, chunks), 1):
            for rid, node in res.items():
                if node is None:
                    continue
                found = {t for a, (_, t) in MARKERS.items() if a != "mk" and node.get(a)}
                if node.get("mk"):
                    found.add("marketplace" if marketplace_size(node["mk"].get("text")) >= MIN_MARKETPLACE_PLUGINS else "plugin")
                found = sorted(found)
                repos[rid]["files"] = found
                repos[rid]["probed"] = date
            if k % 20 == 0 or k == len(chunks):
                print(f"  probed {k}/{len(chunks)} batches", file=sys.stderr, flush=True)
    return len(ids)
