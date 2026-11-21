"""skills.sh install tracking.

Every skill on the skills.sh leaderboards (all-time ∪ trending) is collected daily from the
public JSON endpoint the site itself uses (`/api/skills/{view}/{page}`, 200 rows per page).

  data/skills-raw/                full daily lists, committed to main and never pruned (like repo
                                  snapshots). One skill per line so git stores each day as a small delta.
    all-time/DATE.json            {date, collected_at, total, official: [key], names: {key: name},
                                   installs: {key: n}}
    trending/DATE.json            {date, collected_at, total, order: [[key, installs_24h], ...]} (rank = position)
  data/skills.json                page data, rebuilt at deploy from the last READ_DAYS days (gitignored).

A skill's key is "source|skillId" (both parts may contain "/").

Usage:
  uv run python -m tf.skills collect [--date D] [--force]   fetch both lists into data/skills-raw/
  uv run python -m tf.skills build [--date D]               write data/skills.json
  uv run python -m tf.skills build --preview-dir preview/skills
                                                           same, but while production has fewer than two
                                                           days, build from two manual test collections
                                                           instead and mark the page as preview
  uv run python -m tf.skills gate [--date D]                validate before the daily commit
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from .common import DATA, SNAPSHOTS, dump, load, now_iso, today
from .rank import PERIODS, SPARK_DAYS, add_periods, available_periods, ndays, ranks, shift, spark

API = "https://skills.sh/api/skills/{view}/{page}"
VIEWS = ("all-time", "trending")
RAW = DATA / "skills-raw"
OUT = DATA / "skills.json"

READ_DAYS = max(PERIODS)  # build reads only this many recent days (history itself is never pruned)
TREND_CUT = 300         # "in trending" = top N of the 24h list (skills.sh's own first screen)
TOP = 300               # rows per leaderboard tab and period
RATE_MIN_BASE = 1000    # % ranking only considers skills with at least this many baseline installs

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
BODY = {"all-time": "installs", "trending": "order"}  # the big field, written one entry per line


def raw_path(raw: Path, view: str, date: str) -> Path:
    return raw / view / f"{date}.json"


def write_raw(path: Path, obj: dict, body: str) -> None:
    """JSON with the small fields on the first line and one entry of `body` per line after it."""
    j = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
    head = {k: v for k, v in sorted(obj.items()) if k != body}
    items = obj[body]
    if isinstance(items, dict):
        lines, open_, close = [f"{j(k)}:{j(v)}" for k, v in sorted(items.items())], "{", "}"
    else:
        lines, open_, close = [j(x) for x in items], "[", "]"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{j(head)[:-1]},{j(body)}:{open_}\n" + ",\n".join(lines) + f"\n{close}}}\n")


def read_raw(path: Path) -> dict | None:
    return load(path)


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


def collect(date: str, raw: Path = RAW, force: bool = False, client: httpx.Client | None = None,
            delay: float = DELAY, gap: float = VIEW_GAP, sleep: Callable[[float], None] = time.sleep) -> None:
    client = client or httpx.Client(timeout=30, headers={"User-Agent": UA}, follow_redirects=True)
    fetched = 0
    for view in VIEWS:
        path = raw_path(raw, view, date)
        if path.exists() and not force:
            print(f"{view}/{path.name} already collected; skipping (use --force to overwrite)", file=sys.stderr)
            continue
        if fetched:
            sleep(gap)
        t0 = time.monotonic()
        rows, total = fetch_view(client, view, delay, sleep)
        write_raw(path, to_raw(view, rows, total, date, now_iso()), BODY[view])
        fetched += 1
        print(f"{view}: {len(rows)}/{total} skills in {time.monotonic() - t0:.0f}s", file=sys.stderr)


# ---------------------------------------------------------------- history
@dataclass
class Day:
    date: str
    collected_at: str
    installs: dict[str, int]
    trending: list[tuple[str, int]]            # [[key, installs_24h], ...] in rank order
    official: set[str] = field(default_factory=set)
    names: dict[str, str] = field(default_factory=dict)

    @property
    def cut(self) -> dict[str, int]:
        return {k: i + 1 for i, (k, _) in enumerate(self.trending[:TREND_CUT])}


def load_day(date: str, raw: Path) -> Day | None:
    a = read_raw(raw_path(raw, "all-time", date))
    if not a:
        return None
    t = read_raw(raw_path(raw, "trending", date)) or {}
    return Day(date, a["collected_at"], a["installs"], [tuple(x) for x in t.get("order", [])],
               set(a.get("official", [])), a.get("names", {}))


def available_dates(raw: Path, upto: str | None = None) -> list[str]:
    return sorted(p.stem for p in (raw / "all-time").glob("*.json") if upto is None or p.stem <= upto)


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


def build(date: str | None = None, raw: Path = RAW, write: bool = True, preview: bool = False) -> dict:
    dates = available_dates(raw, date)
    if not dates:
        raise SystemExit(f"no skill snapshots in {raw}")
    date = dates[-1]
    # only the last READ_DAYS days are read; older files stay in the repo as history
    days = [d for d in (load_day(x, raw) for x in dates if x >= shift(date, -READ_DAYS)) if d]
    cur = days[-1]
    prev = days[-2] if len(days) > 1 else None
    periods = available_periods(dates[0], date)

    t24: dict[str, int] = {k: n for k, n in cur.trending}
    cut, prev_cut = cur.cut, (prev.cut if prev else {})
    series = {k: [(d.date, d.installs[k]) for d in days if k in d.installs] for k in cur.installs}
    stats: dict[str, dict] = {k: {} for k in cur.installs}
    add_periods(stats, series, date, periods, RATE_MIN_BASE, cur.installs)
    rank_all = ranks(cur.installs)
    prev_rank_all = ranks(prev.installs) if prev else {}

    # shipped: the top TOP of every board (each period's gains and growth, all-time, trending cut)
    boards = set(sorted(rank_all, key=lambda k: rank_all[k])[:TOP]) | set(cut)
    for k, st in stats.items():
        if any(v.get(b, TOP + 1) <= TOP for v in st.get("p", {}).values() for b in ("g", "q")):
            boards.add(k)
    repos = repo_index()
    # every skill of a tracked repo is shipped too, so a repo's "N skills" link lists all N;
    # those rows carry "x" and stay out of the unfiltered boards
    linked = {k for k in cur.installs if split_key(k)[0].lower() in repos} - boards

    rows = []
    for k in boards | linked:
        src, sid = split_key(k)
        repo = repos.get(src.lower())
        row = {
            "k": k, "src": src, "id": sid, "name": cur.names.get(k),
            "gh": bool(GH_SOURCE.match(src)),
            "official": k in cur.official or None,
            "installs": cur.installs.get(k),
            "ar": rank_all.get(k), "par": prev_rank_all.get(k),
            "p": stats.get(k, {}).get("p"),
            "spark": spark(series[k], date) if k in series else None,
            "tr": cut.get(k), "ptr": prev_cut.get(k), "t24": t24.get(k),
            "streak": streak_back(days, len(days) - 1, k) if k in cut else None,
            "repo": repo["name"] if repo else None, "stars": repo["stars"] if repo else None,
            "x": 1 if k in linked else None,
        }
        rows.append({f: v for f, v in row.items() if v is not None})  # keep the payload small
    rows.sort(key=lambda r: (r.get("ar") or 10**9, r["k"]))

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
        "preview": preview,
        "tracking_start": dates[0],
        "periods": periods,
        "collected_at": cur.collected_at,
        "prev_collected_at": prev.collected_at if prev else None,
        "spark_dates": [d.date for d in days if d.date >= shift(date, -SPARK_DAYS)],
        "trend_cut": TREND_CUT,
        "rate_min_base": RATE_MIN_BASE,
        "totals": {"tracked": len(tracked), "all_time": len(cur.installs), "trending": len(t24)},
        "by_repo": by_repo,
        "moves": moves(days, shift(date, -(READ_DAYS - 1))),
        "skills": rows,
    }
    if write:
        dump(OUT, out, compact=True)
        print(f"skills.json: {len(rows)} shown of {len(tracked)} tracked, periods {periods}, "
              f"{len(days)} days read", file=sys.stderr)
    return out


def use_preview(raw: Path, preview_dir: Path | None) -> bool:
    """Deploy preview data until production has two days to compare."""
    if not preview_dir:
        return False
    return len(available_dates(raw)) < 2 and len(available_dates(preview_dir)) >= 2


# ---------------------------------------------------------------- gate
def check(date: str, raw: Path = RAW) -> tuple[list[str], list[str]]:
    from .gate import git

    errors: list[str] = []
    warns: list[str] = []
    changed = [l[3:] for l in git("status", "--porcelain", "--untracked-files=all").splitlines()]
    outside = [p for p in changed if not p.startswith("data/")]
    if outside:
        errors.append(f"files changed outside data/: {outside[:5]}")
    for view in VIEWS:
        rel = f"data/skills-raw/{view}/{date}.json"
        if git("ls-files", rel).strip() and rel in changed:
            errors.append(f"{rel} is already committed and was modified")

    a = read_raw(raw_path(raw, "all-time", date))
    t = read_raw(raw_path(raw, "trending", date))
    if not a or a.get("date") != date or not a.get("installs"):
        errors.append(f"all-time list for {date} missing or malformed")
        return errors, warns
    if not t or t.get("date") != date or not t.get("order"):
        errors.append(f"trending list for {date} missing or malformed")
    bad = [k for k, v in a["installs"].items() if "|" not in k or not isinstance(v, int) or v < 0]
    if bad:
        errors.append(f"all-time has {len(bad)} invalid entries, e.g. {bad[:3]}")

    older = [d for d in available_dates(raw) if d < date]
    p = read_raw(raw_path(raw, "all-time", older[-1])) if older else None
    if p:
        cur, prv = a["installs"], p["installs"]
        if len(cur) < len(prv) * GATE_MIN_COUNT:
            errors.append(f"all-time skill count fell {len(prv)} -> {len(cur)}")
        crashed = [k for k, v in cur.items() if k in prv and prv[k] >= 100 and v < prv[k] * 0.5]
        if len(crashed) > len(cur) * GATE_MAX_DROP_SHARE:
            errors.append(f"{len(crashed)} skills lost >50% installs (limit {GATE_MAX_DROP_SHARE:.0%})")
        elif crashed:
            warns.append(f"{len(crashed)} skills lost >50% installs: {crashed[:5]}")

    out = load(OUT)
    if not out or out.get("date") != date:
        errors.append("skills.json missing or not built for today")
    elif out.get("preview"):
        errors.append("skills.json is preview data")
    return errors, warns


# ---------------------------------------------------------------- cli
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["collect", "build", "gate"])
    ap.add_argument("--date")
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--preview-dir", type=Path, help="raw-layout test collections to use until production has 2 days")
    a = ap.parse_args()
    if a.cmd == "collect":
        collect(a.date or today(), a.raw, a.force)
    elif a.cmd == "build":
        if use_preview(a.raw, a.preview_dir):
            print(f"fewer than 2 production days; building preview data from {a.preview_dir}", file=sys.stderr)
            build(a.date, a.preview_dir, preview=True)
        else:
            build(a.date, a.raw)
    else:
        d = a.date or today()
        errors, warns = check(d, a.raw)
        for w in warns:
            print(f"WARN  {w}")
        for e in errors:
            print(f"FAIL  {e}")
        print("skills gate: FAILED" if errors else "skills gate: passed")
        sys.exit(1 if errors else 0)
