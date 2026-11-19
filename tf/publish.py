"""Reader-facing outputs derived from snapshots.

  feed    RSS 2.0 feed of the daily Top 10 for the last FEED_DAYS days   -> _site/feed.xml
  digest  Weekly markdown digest (Mondays, full 7-day window only)        -> data/digests/YYYY-Www.md
          The workflow publishes it as a GitHub Release, which GitHub emails
          to everyone watching the repo's releases.

Usage:
  uv run python -m tf.publish feed --out _site/feed.xml
  uv run python -m tf.publish digest [--date YYYY-MM-DD] [--force]
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from email.utils import format_datetime
from html import escape
from pathlib import Path

from .build import WINDOW, build
from .common import DATA, SNAPSHOTS, today

SITE = "https://mit2400.github.io/agent-trending/"
REPO = "https://github.com/mit2400/agent-trending"
FEED_DAYS = 14
TOP = 10
TYPE_ORDER = ["mcp", "skill", "plugin", "marketplace", "subagent", "agent", "framework", "client", "tool"]
TYPE_LABEL = {"mcp": "MCP servers", "skill": "Skills", "plugin": "Plugins", "marketplace": "Marketplaces",
              "subagent": "Subagents", "agent": "Agents", "framework": "Frameworks", "client": "Clients", "tool": "Tools"}


def gainers(t: dict) -> list[dict]:
    return [r for r in t["repos"] if r["delta"] and r["delta"] > 0]


def fastest(t: dict) -> list[dict]:
    rs = [r for r in gainers(t) if r["base"] >= t["rate_min_base"]]
    return sorted(rs, key=lambda r: -r["rate"])


def window_days(t: dict) -> int:
    return (dt.date.fromisoformat(t["date"]) - dt.date.fromisoformat(t["baseline_date"])).days


# ---------------------------------------------------------------- feed
def feed(out: Path) -> None:
    dates = sorted(p.stem for p in SNAPSHOTS.glob("*.json"))[-FEED_DAYS:]
    items = []
    for d in reversed(dates):
        t = build(SNAPSHOTS, date=d, write=False)
        top = gainers(t)[:TOP]
        if not top:
            continue
        wd = window_days(t)
        lis = "".join(
            f'<li><a href="https://github.com/{escape(r["name"])}">{escape(r["name"])}</a> '
            f'<b>+{r["delta"]:,}</b> ★ ({r["stars"]:,} total){" — " + escape(r["desc"]) if r["desc"] else ""}</li>'
            for r in top)
        pub = dt.datetime.fromisoformat(t["latest_collected_at"].replace("Z", "+00:00"))
        items.append(f"""    <item>
      <title>{escape(f"{d}: {top[0]['name']} leads with +{top[0]['delta']:,} stars ({wd}d)")}</title>
      <link>{SITE}</link>
      <guid isPermaLink="false">agent-trending-{d}</guid>
      <pubDate>{format_datetime(pub)}</pubDate>
      <description>{escape(f"<p>Top {TOP} star gains over {wd} day(s), as of {d}.</p><ol>{lis}</ol>")}</description>
    </item>""")
    now = format_datetime(dt.datetime.now(dt.timezone.utc))
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Agent Trending</title>
    <link>{SITE}</link>
    <atom:link href="{SITE}feed.xml" rel="self" type="application/rss+xml"/>
    <description>Daily top star gainers in the AI agent ecosystem.</description>
    <language>en</language>
    <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml)
    print(f"{out}: {len(items)} items", file=sys.stderr)


# ---------------------------------------------------------------- digest
def week_label(date: str) -> tuple[str, str, str]:
    """The window ending on `date` covers the 7 days before it."""
    end = dt.date.fromisoformat(date) - dt.timedelta(days=1)
    start = end - dt.timedelta(days=WINDOW - 1)
    y, w, _ = end.isocalendar()
    return f"{y}-W{w:02d}", start.strftime("%b %-d"), end.strftime("%b %-d")


def md_row(i: int, r: dict, metric: str) -> str:
    desc = (r["desc"] or "").replace("|", "\\|")
    return f"| {i} | [{r['name']}](https://github.com/{r['name']}) | {metric} | {r['stars']:,} | {desc} |"


def table(rows: list[dict], metric) -> str:
    head = "| # | Repository | Gain | Stars | Description |\n|---:|---|---:|---:|---|"
    return "\n".join([head, *(md_row(i, r, metric(r)) for i, r in enumerate(rows, 1))])


def digest(date: str, force: bool = False) -> Path | None:
    t = build(SNAPSHOTS, date=date, write=False)
    wd = window_days(t)
    if wd < WINDOW and not force:
        print(f"window is {wd}d (< {WINDOW}d); skipping digest", file=sys.stderr)
        return None
    label, start, end = week_label(t["date"])
    g = gainers(t)
    parts = [
        f"# Agent Trending — {label} ({start} – {end})",
        f"Star growth across **{t['count']:,}** tracked AI-agent-ecosystem repos over {wd} days. "
        f"Live leaderboard: {SITE}",
        "## 🔥 Top gains",
        table(g[:20], lambda r: f"+{r['delta']:,}"),
        "## 📈 Fastest growing",
        f"_Repos with at least {t['rate_min_base']} stars at the start of the week._",
        table(fastest(t)[:10], lambda r: f"+{r['rate'] * 100:.1f}%"),
    ]
    new = [r for r in g if r["new"]][:10]
    if new:
        parts += ["## ✨ New this week", table(new, lambda r: f"+{r['delta']:,}")]
    parts.append("## 🏷️ Top by type")
    lines = []
    for typ in TYPE_ORDER:
        best = next((r for r in g if typ in r["type"]), None)
        if best:
            lines.append(f"- **{TYPE_LABEL[typ]}** — [{best['name']}](https://github.com/{best['name']}) +{best['delta']:,}")
    parts.append("\n".join(lines))
    parts.append(f"---\nGet this digest by email: **Watch → Custom → Releases** on [{REPO.removeprefix('https://github.com/')}]({REPO}). "
                 f"Daily RSS: {SITE}feed.xml")
    out = DATA / "digests" / f"{label}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n\n".join(parts) + "\n")
    print(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("feed")
    f.add_argument("--out", type=Path, required=True)
    d = sub.add_parser("digest")
    d.add_argument("--date", default=today())
    d.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "feed":
        feed(a.out)
    else:
        digest(a.date, a.force)
