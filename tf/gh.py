"""Minimal GitHub client: GraphQL batches + raw file fetch."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

import httpx

API = "https://api.github.com"
BATCH = 100       # light queries (ids -> stars)
NAME_BATCH = 50   # heavy queries (full fields by name)
WORKERS = 6

REPO_FIELDS = """
  id nameWithOwner description stargazerCount isArchived isFork
  createdAt pushedAt defaultBranchRef { name }
  primaryLanguage { name }
  repositoryTopics(first: 10) { nodes { topic { name } } }
"""


def token() -> str:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        return subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as e:
        raise SystemExit("No GITHUB_TOKEN and `gh auth token` failed") from e


class GitHub:
    def __init__(self) -> None:
        self.http = httpx.Client(
            headers={
                "Authorization": f"Bearer {token()}",
                "User-Agent": "agent-trending",
                "Accept": "application/vnd.github+json",
            },
            timeout=60,
            follow_redirects=True,
        )

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        """POST with retries on 5xx, rate limits, timeouts and empty/non-JSON bodies."""
        last: Exception | None = None
        for attempt in range(5):
            try:
                r = self.http.post(f"{API}/graphql", json={"query": query, "variables": variables or {}})
                if r.status_code >= 500 or (r.status_code == 403 and "rate" in r.text.lower()):
                    raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPStatusError, httpx.TransportError, ValueError) as e:
                last = e
                time.sleep(2 ** attempt * 3)
        raise RuntimeError(f"GraphQL failed after retries: {last}")

    def repos_by_name(self, names: Iterable[str]) -> dict[str, dict | None]:
        """Resolve owner/name -> repo node (None when missing). Follows renames."""
        names = list(dict.fromkeys(names))
        chunks = [names[i : i + NAME_BATCH] for i in range(0, len(names), NAME_BATCH)]

        def run(chunk: list[str]) -> dict[str, dict | None]:
            parts = []
            for j, full in enumerate(chunk):
                owner, name = full.split("/", 1)
                parts.append(f"r{j}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ {REPO_FIELDS} }}")
            data = self.graphql("query {" + "\n".join(parts) + "}").get("data") or {}
            return {full: data.get(f"r{j}") for j, full in enumerate(chunk)}

        out: dict[str, dict | None] = {}
        with ThreadPoolExecutor(WORKERS) as pool:
            for k, res in enumerate(pool.map(run, chunks), 1):
                out.update(res)
                if k % 20 == 0 or k == len(chunks):
                    print(f"  resolved {k}/{len(chunks)} batches", file=sys.stderr, flush=True)
        return out

    def repos_by_id(self, ids: Iterable[str], fields: str = REPO_FIELDS) -> dict[str, dict | None]:
        """Fetch repo nodes by GraphQL node ID (stable across renames/transfers)."""
        ids = list(dict.fromkeys(ids))
        out: dict[str, dict | None] = {}
        q = "query($ids: [ID!]!) { nodes(ids: $ids) { ... on Repository { %s } } }" % fields
        for i in range(0, len(ids), BATCH):
            chunk = ids[i : i + BATCH]
            res = self.graphql(q, {"ids": chunk})
            nodes = (res.get("data") or {}).get("nodes") or [None] * len(chunk)
            for nid, node in zip(chunk, nodes):
                out[nid] = node or None
        return out

    def readme(self, full: str) -> str:
        """Fetch README raw text (raw host avoids the 512KB API truncation)."""
        meta = self.http.get(f"{API}/repos/{full}/readme")
        meta.raise_for_status()
        url = meta.json()["download_url"]
        r = httpx.get(url, timeout=60, follow_redirects=True)
        r.raise_for_status()
        return r.text


def topics(node: dict) -> list[str]:
    return [n["topic"]["name"] for n in (node.get("repositoryTopics") or {}).get("nodes", [])]
