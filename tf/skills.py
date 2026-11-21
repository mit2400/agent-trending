"""skills.sh install tracking.

Every skill on the skills.sh leaderboards (all-time ∪ trending) is collected daily from the
public JSON endpoint the site itself uses (`/api/skills/{view}/{page}`, 200 rows per page).

  raw/                     full daily snapshots, last KEEP_DAYS days. Lives on the `skills-raw`
                           branch (one force-pushed commit, so history never grows); gitignored on main.
    all-time/DATE.json.gz  {date, collected_at, total, installs: {key: n}, official: [key], names: {key: name}}
    trending/DATE.json.gz  {date, collected_at, total, order: [[key, installs_24h], ...]}  (rank = position)
  data/skills/DATE.json    display snapshot committed to main: the skills shown on the page that day
                           plus the trending top TREND_CUT. Fallback history if raw/ is lost.
  data/skills.json         page data, rebuilt at deploy (gitignored).

A skill's key is "source|skillId" (both parts may contain "/").

Usage:
  uv run python -m tf.skills collect [--date D] [--force]   fetch both lists into raw/, prune old days
  uv run python -m tf.skills build [--date D] [--snapshot]  write data/skills.json (+ display snapshot)
  uv run python -m tf.skills gate [--date D]                validate before the daily commit
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from .common import DATA, ROOT, SNAPSHOTS, dump, load, now_iso, today

API = "https://skills.sh/api/skills/{view}/{page}"
VIEWS = ("all-time", "trending")
RAW = ROOT / "raw"
SKILL_SNAPS = DATA / "skills"
OUT = DATA / "skills.json"

KEEP_DAYS = 30          # raw history kept on the skills-raw branch
TREND_CUT = 300         # "in trending" = top N of the 24h list (skills.sh's own first screen)
TOP = 300               # rows per leaderboard tab
WINDOW = 7
RATE_MIN_BASE = 1000    # % ranking only considers skills with at least this many baseline installs
MOVES_DAYS = 30

DELAY = 2.0             # seconds between page requests
VIEW_GAP = 60.0         # pause between the two lists (a burst of ~50 fast requests gets HTTP 429)
BACKOFF = (15, 30, 60, 120, 240)
MAX_PAGES = 200
MIN_COVERAGE = 0.98     # rows received vs the `total` the API reports
GATE_MIN_COUNT = 0.95   # today's all-time count vs the previous day
GATE_MAX_DROP_SHARE = 0.01
UA = "agent-trending (+https://github.com/mit2400/agent-trending)"

GH_SOURCE = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9_.-]+$")


def key(source: str, skill_id: str) -> str:
    return f"{source}|{skill_id}"


def split_key(k: str) -> tuple[str, str]:
    src, _, sid = k.partition("|")
    return src, sid


def shift(date: str, days: int) -> str:
    return (dt.date.fromisoformat(date) + dt.timedelta(days=days)).isoformat()


def ndays(a: str, b: str) -> int:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


# ---------------------------------------------------------------- fetch
def get_page(client: httpx.Client, view: str, page: int, sleep: Callable[[float], None]) -> dict:
    url = API.format(view=view, page=page)
    for attempt in range(len(BACKOFF) + 1):
        try:
            r = client.get(url)
        except httpx.TransportError as e:
            if attempt == len(BACKOFF):
                raise
            wait = BACKOFF[attempt]
            print(f"  {view}/{page}: {type(e).__name__}; retry in {wait}s", file=sys.stderr)
            sleep(wait)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == len(BACKOFF):
                r.raise_for_status()
            ra = r.headers.get("retry-after", "")
            wait = int(ra) if ra.isdigit() else BACKOFF[attempt]
            print(f"  {view}/{page}: HTTP {r.status_code}; retry in {wait}s", file=sys.stderr)
            sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("unreachable")


def fetch_view(client: httpx.Client, view: str, delay: float = DELAY,
               sleep: Callable[[float], None] = time.sleep) -> tuple[list[dict], int]:
    """All rows of one list, deduplicated by key, in API order.

    Ranks shift while paging, so a skill can appear twice or slip between pages; duplicates are
    dropped and the run fails if fewer than MIN_COVERAGE of the reported total arrived.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    total = 0
    for page in range(MAX_PAGES):
        if page:
            sleep(delay)
        d = get_page(client, view, page, sleep)
        total = d.get("total") or total
        for s in d.get("skills", []):
            k = key(s["source"], s["skillId"])
            if k not in seen:
                seen.add(k)
                rows.append(s)
        if not d.get("hasMore") or not d.get("skills"):
            break
    else:
        raise RuntimeError(f"{view}: more than {MAX_PAGES} pages")
    if not rows or (total and len(rows) < total * MIN_COVERAGE):
        raise RuntimeError(f"{view}: got {len(rows)} of {total} skills (< {MIN_COVERAGE:.0%})")
    return rows, total


# ---------------------------------------------------------------- raw files
def raw_path(raw: Path, view: str, date: str) -> Path:
    return raw / view / f"{date}.json.gz"


def write_gz(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    path.write_bytes(gzip.compress(text.encode(), mtime=0))


def read_gz(path: Path) -> dict | None:
    return json.loads(gzip.decompress(path.read_bytes())) if path.exists() else None


def to_raw(view: str, rows: list[dict], total: int, date: str, collected_at: str) -> dict:
    head = {"date": date, "collected_at": collected_at, "total": total}
    if view == "trending":
        return {**head, "order": [[key(s["source"], s["skillId"]), s["installs"]] for s in rows]}
    return {
        **head,
        "installs": {key(s["source"], s["skillId"]): s["installs"] for s in rows},
        "official": sorted(key(s["source"], s["skillId"]) for s in rows if s.get("isOfficial")),
        "names": {key(s["source"], s["skillId"]): s["name"] for s in rows
                  if s.get("name") and s["name"] != s["skillId"]},
    }


def prune(raw: Path, date: str, keep: int = KEEP_DAYS) -> list[Path]:
    cutoff = shift(date, -(keep - 1))
    gone = [p for v in VIEWS for p in (raw / v).glob("*.json.gz") if p.name[:10] < cutoff]
    for p in gone:
        p.unlink()
    return gone


def collect(date: str, raw: Path = RAW, force: bool = False, client: httpx.Client | None = None,
            delay: float = DELAY, gap: float = VIEW_GAP, sleep: Callable[[float], None] = time.sleep) -> None:
    client = client or httpx.Client(timeout=30, headers={"User-Agent": UA}, follow_redirects=True)
    for i, view in enumerate(VIEWS):
        path = raw_path(raw, view, date)
        if path.exists() and not force:
            print(f"{view}/{path.name} already collected; skipping (use --force to overwrite)", file=sys.stderr)
            continue
        if i:
            sleep(gap)
        t0 = time.monotonic()
        rows, total = fetch_view(client, view, delay, sleep)
        write_gz(path, to_raw(view, rows, total, date, now_iso()))
        print(f"{view}: {len(rows)}/{total} skills in {time.monotonic() - t0:.0f}s", file=sys.stderr)
    gone = prune(raw, date)
    if gone:
        print(f"pruned {len(gone)} raw files older than {KEEP_DAYS} days", file=sys.stderr)


# ---------------------------------------------------------------- history
@dataclass
class Day:
    date: str
    collected_at: str
    installs: dict[str, int]
    trending: list[tuple[str, int]]            # [[key, installs_24h], ...] in rank order
    official: set[str] = field(default_factory=set)
    names: dict[str, str] = field(default_factory=dict)
    partial: bool = False                      # rebuilt from a display snapshot, not a full list

    @property
    def cut(self) -> dict[str, int]:
        return {k: i + 1 for i, (k, _) in enumerate(self.trending[:TREND_CUT])}


def load_day(date: str, raw: Path, snaps: Path) -> Day | None:
    a = read_gz(raw_path(raw, "all-time", date))
    if a:
        t = read_gz(raw_path(raw, "trending", date)) or {}
        return Day(date, a["collected_at"], a["installs"], t.get("order", []),
                   set(a.get("official", [])), a.get("names", {}))
    s = load(snaps / f"{date}.json")
    if s:
        return Day(date, s["collected_at"], s["installs"], s.get("trending", []),
                   set(s.get("official", [])), s.get("names", {}), partial=True)
    return None


def available_dates(raw: Path, snaps: Path, upto: str | None) -> list[str]:
    ds = {p.name[:10] for p in (raw / "all-time").glob("*.json.gz")} | {p.stem for p in snaps.glob("*.json")}
    return sorted(d for d in ds if upto is None or d <= upto)


def streak_back(days: list[Day], i: int, k: str) -> int:
    """Consecutive calendar days ending at days[i] with k in the trending cut."""
    n = 0
    while i >= 0 and k in days[i].cut and (n == 0 or ndays(days[i].date, days[i + 1].date) == 1):
        n += 1
        i -= 1
    return n


def moves(days: list[Day], since: str) -> list[dict]:
    out = []
    for i in range(1, len(days)):
        prev, cur = days[i - 1], days[i]
        if cur.date < since:
            continue
        pc, cc = prev.cut, cur.cut
        t_cur: dict[str, int] = {k: n for k, n in cur.trending}
        t_prev: dict[str, int] = {k: n for k, n in prev.trending}
        entered = [{"k": k, "r": r, "t": t_cur.get(k)} for k, r in sorted(cc.items(), key=lambda x: x[1]) if k not in pc]
        left = [{"k": k, "r": r, "t": t_prev.get(k), "d": streak_back(days, i - 1, k)}
                for k, r in sorted(pc.items(), key=lambda x: x[1]) if k not in cc]
        out.append({"date": cur.date, "from": prev.date, "in": entered, "out": left})
    return out[::-1]  # newest first


# ---------------------------------------------------------------- build
def repo_index() -> dict[str, dict]:
    """Tracked GitHub repos by lowercase name, with their latest star count."""
    reg = (load(DATA / "registry.json") or {}).get("repos", {})
    snaps = sorted(SNAPSHOTS.glob("*.json"))
    stars = load(snaps[-1])["stars"] if snaps else {}
    return {e["name"].lower(): {"name": e["name"], "stars": stars.get(rid)}
            for rid, e in reg.items() if not e.get("archived")}


def build(date: str | None = None, raw: Path = RAW, snaps: Path = SKILL_SNAPS, write: bool = True,
          snapshot: bool = False) -> dict:
    dates = available_dates(raw, snaps, date)
    if not dates:
        raise SystemExit(f"no skill snapshots in {raw} or {snaps}")
    date = dates[-1]
    days = [d for d in (load_day(x, raw, snaps) for x in dates if x >= shift(date, -MOVES_DAYS)) if d]
    cur = days[-1]
    prev = days[-2] if len(days) > 1 else None
    window = [d for d in days if d.date >= shift(date, -WINDOW)]

    rank_all = {k: i + 1 for i, k in enumerate(sorted(cur.installs, key=lambda k: (-cur.installs[k], k)))}
    prev_rank_all = ({k: i + 1 for i, k in enumerate(sorted(prev.installs, key=lambda k: (-prev.installs[k], k)))}
                     if prev and not prev.partial else {})
    t24: dict[str, int] = {k: n for k, n in cur.trending}
    cut, prev_cut = cur.cut, (prev.cut if prev else {})

    stats: dict[str, dict] = {}
    for k, n in cur.installs.items():
        series = [(d.date, d.installs[k]) for d in window if k in d.installs]
        base_date, base = series[0]
        wd = ndays(base_date, date)
        delta = n - base if wd > 0 else None
        stats[k] = {
            "installs": n, "base": base, "delta": delta, "window": wd,
            "rate": round(delta / base, 5) if delta is not None and base > 0 else None,
            "d1": n - prev.installs[k] if prev and k in prev.installs else None,
            "spark": [v for _, v in series],
        }

    gainers = sorted((k for k, s in stats.items() if s["delta"]), key=lambda k: (-stats[k]["delta"], k))
    risers = sorted((k for k, s in stats.items() if s["rate"] and s["rate"] > 0 and s["base"] >= RATE_MIN_BASE),
                    key=lambda k: (-stats[k]["rate"], k))
    shown = set(gainers[:TOP]) | set(risers[:TOP]) | set(sorted(rank_all, key=lambda k: rank_all[k])[:TOP]) | set(cut)
    repos = repo_index()
    has_history = any(s["delta"] is not None for s in stats.values())

    rows = []
    for k in shown:
        src, sid = split_key(k)
        s = stats.get(k, {})
        repo = repos.get(src.lower())
        rows.append({
            "k": k, "src": src, "id": sid, "name": cur.names.get(k),
            "gh": bool(GH_SOURCE.match(src)),
            "official": k in cur.official or None,
            "installs": s.get("installs"), "base": s.get("base"), "delta": s.get("delta"),
            "rate": s.get("rate"), "window": s.get("window"), "d1": s.get("d1"), "spark": s.get("spark"),
            "ar": rank_all.get(k), "par": prev_rank_all.get(k),
            "tr": cut.get(k), "ptr": prev_cut.get(k) if prev else None, "t24": t24.get(k),
            "streak": streak_back(days, len(days) - 1, k) if k in cut else 0,
            "repo": repo["name"] if repo else None, "stars": repo["stars"] if repo else None,
        })
    rows.sort(key=lambda r: (r["delta"] is None, -(r["delta"] or 0), -(r["installs"] or 0), r["k"]))
    for r in rows:  # drop nulls/falsy flags to keep the payload small
        for f in ("name", "official", "repo", "stars", "par", "ptr", "tr", "t24", "d1"):
            if r[f] is None:
                del r[f]

    by_repo: dict[str, dict] = {}
    for k, n in cur.installs.items():
        repo = repos.get(split_key(k)[0].lower())
        if repo:
            b = by_repo.setdefault(repo["name"], {"n": 0, "installs": 0})
            b["n"] += 1
            b["installs"] += n

    tracked = set(cur.installs) | set(t24)
    out = {
        "generated_at": now_iso(),
        "date": date,
        "collected_at": cur.collected_at,
        "partial": cur.partial,
        "window_max": WINDOW,
        "tracking_start": dates[0],
        "baseline_date": window[0].date,
        "window_dates": [d.date for d in window],  # spark arrays are right-aligned to these
        "has_history": has_history,
        "trend_cut": TREND_CUT,
        "top": TOP,
        "rate_min_base": RATE_MIN_BASE,
        "totals": {
            "tracked": len(tracked),
            "all_time": len(cur.installs),
            "trending": len(t24),
            "installs": sum(cur.installs.values()),
            "window_installs": sum(s["delta"] or 0 for s in stats.values()) if has_history else None,
            "installs_24h": sum(t24.values()),
        },
        "by_repo": by_repo,
        "moves": moves(days, shift(date, -(MOVES_DAYS - 1))),
        "skills": rows,
    }
    if write:
        dump(OUT, out, compact=True)
        print(f"skills.json: {len(rows)} shown of {len(tracked)} tracked, "
              f"window {window[0].date}..{date}", file=sys.stderr)
    if snapshot:
        write_display_snapshot(cur, {r["k"] for r in rows}, snaps)
    return out


def write_display_snapshot(day: Day, keys: set[str], snaps: Path) -> Path:
    keep = keys | set(day.cut)
    path = snaps / f"{day.date}.json"
    dump(path, {
        "date": day.date,
        "collected_at": day.collected_at,
        "installs": {k: n for k, n in day.installs.items() if k in keep},
        "trending": day.trending[:TREND_CUT],
        "official": sorted(day.official & keep),
        "names": {k: v for k, v in day.names.items() if k in keep},
    }, compact=True)
    return path


# ---------------------------------------------------------------- gate
def check(date: str, raw: Path = RAW, snaps: Path = SKILL_SNAPS) -> tuple[list[str], list[str]]:
    from .gate import git

    errors: list[str] = []
    warns: list[str] = []
    changed = [l[3:] for l in git("status", "--porcelain", "--untracked-files=all").splitlines()]
    outside = [p for p in changed if not p.startswith("data/")]
    if outside:
        errors.append(f"files changed outside data/: {outside[:5]}")
    rel = f"data/skills/{date}.json"
    if git("ls-files", rel).strip() and rel in changed:
        errors.append(f"display snapshot {date} is already committed and was modified")

    a = read_gz(raw_path(raw, "all-time", date))
    t = read_gz(raw_path(raw, "trending", date))
    if not a or a.get("date") != date or not a.get("installs"):
        errors.append(f"raw all-time snapshot for {date} missing or malformed")
        return errors, warns
    if not t or t.get("date") != date or not t.get("order"):
        errors.append(f"raw trending snapshot for {date} missing or malformed")
    bad = [k for k, v in a["installs"].items() if "|" not in k or not isinstance(v, int) or v < 0]
    if bad:
        errors.append(f"all-time has {len(bad)} invalid entries, e.g. {bad[:3]}")

    older = sorted(p.name[:10] for p in (raw / "all-time").glob("*.json.gz") if p.name[:10] < date)
    p = read_gz(raw_path(raw, "all-time", older[-1])) if older else None
    if p:
        cur, prv = a["installs"], p["installs"]
        if len(cur) < len(prv) * GATE_MIN_COUNT:
            errors.append(f"all-time skill count fell {len(prv)} -> {len(cur)}")
        crashed = [k for k, v in cur.items() if k in prv and prv[k] >= 100 and v < prv[k] * 0.5]
        if len(crashed) > len(cur) * GATE_MAX_DROP_SHARE:
            errors.append(f"{len(crashed)} skills lost >50% installs (limit {GATE_MAX_DROP_SHARE:.0%})")
        elif crashed:
            warns.append(f"{len(crashed)} skills lost >50% installs: {crashed[:5]}")

    s = load(snaps / f"{date}.json")
    if not s or s.get("date") != date or not s.get("installs"):
        errors.append(f"display snapshot {rel} missing or malformed")
    out = load(OUT)
    if not out or out.get("date") != date:
        errors.append("skills.json missing or not built for today")
    return errors, warns


# ---------------------------------------------------------------- cli
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "build", "gate"])
    ap.add_argument("--date")
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--snapshot", action="store_true", help="also write the display snapshot to data/skills/")
    a = ap.parse_args()
    if a.cmd == "collect":
        collect(a.date or today(), a.raw, a.force)
    elif a.cmd == "build":
        build(a.date, a.raw, snapshot=a.snapshot)
    else:
        d = a.date or today()
        errors, warns = check(d, a.raw)
        for w in warns:
            print(f"WARN  {w}")
        for e in errors:
            print(f"FAIL  {e}")
        print("skills gate: FAILED" if errors else "skills gate: passed")
        sys.exit(1 if errors else 0)
