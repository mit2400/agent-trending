# Agent Trending

**What's rising in the AI agent ecosystem.** Agents, MCP servers, skills, plugins, marketplaces & AI tools — ranked by GitHub star growth, refreshed daily.

[![Agent Trending](assets/og.png)](https://mit2400.github.io/agent-trending/)

🔗 **Live leaderboard: https://mit2400.github.io/agent-trending/**

Agent Trending tracks about a thousand established repos around AI agents (Claude Code, Codex, Cursor, Gemini CLI, MCP servers, skills, plugins, marketplaces, agent frameworks and AI tools) and shows which ones are gaining stars fastest right now.

- 🔥 **Top gains**: most stars gained over the last 7 days
- 📈 **Fastest growing**: biggest growth in percent
- ✨ **New**: repos created in the last 30 days, or that joined the tracked set this week
- ⭐ **All-time**: total stars

A second board, **Skills** (toggle at the top of the page, or [`?view=skills`](https://mit2400.github.io/agent-trending/?view=skills)), tracks install counts of agent skills from [skills.sh](https://skills.sh) the same way:

- 🔥 **Top gains** / 📈 **Fastest growing**: installs gained over the last 7 days
- ⚡ **Trending 24h**: skills.sh's 24-hour list, with each skill's rank change since yesterday
- 🔀 **In & out**: skills that entered or left the trending top 300 today, this week or this month
- ⭐ **All-time**: total installs

Repos that publish skills link to them, and skills link back to their source repo.

Repos that are on today's [GitHub Trending](https://github.com/trending) page get a **GitHub Trending · Nth** badge: how many days they have been on it since Nov 22, 2026, when logging began (`data/gh-trending.json`).

You can filter every repo view by **type** (MCP, Skills, Plugins, Marketplaces, Agents, Frameworks, …) and **ecosystem** (Claude Code, Codex, Cursor, Gemini CLI, General), search by name, and share a filtered view: the URL keeps your tab and filters.

---

## Follow along

| How | What you get |
|---|---|
| [**RSS feed**](https://mit2400.github.io/agent-trending/feed.xml) | The daily top 10 gainers, for the last 14 days. Works with any feed reader, or Slack's `/feed subscribe`. |
| **Weekly email digest** | Every Monday a digest (top 20 gains, fastest growing, new entries, best per type) is published as a [GitHub Release](https://github.com/mit2400/agent-trending/releases). Click **Watch → Custom → Releases** on this repo and GitHub emails it to you. |
| **Digest archive** | The same digests as Markdown files in `data/digests/`, one per week (the first one is due Monday, Nov 30, 2026, once a full week of data exists). |

---

## What gets tracked

**Every tracked repo has at least 5,000 stars.** The goal is to follow trends worth following, not every new repo. The only exceptions are a few official repos added by hand (for example `cloudflare/mcp-server-cloudflare` and `supabase/mcp`), which are often more useful than their star count suggests.

Repos come from four places:

1. **Curated lists**: 19 awesome lists such as `punkpeye/awesome-mcp-servers`, `hesreallyhim/awesome-claude-code` and `ai-boost/awesome-harness-engineering`. Every GitHub link in them is a candidate. See [`data/sources.json`](data/sources.json).
2. **GitHub topics**: repos tagged with topics like `ai-agents`, `mcp-server`, `agent-skills` or `claude-code` (17 topics).
3. **GitHub Trending**: [trending repos](https://github.com/trending), plus the popular repo of each [trending developer](https://github.com/trending/developers). Only repos that look agent-related are added.
4. **Manual picks**: [`data/overrides.json`](data/overrides.json).

The footer of the page lists every source, with how many tracked repos each one supplies.

### Tags

- **Type** comes from the section of the list a repo appears in (for example "Agent Skills" → `skill`), from its GitHub topics, and from files in the repo:

  | File in the repo | Type |
  |---|---|
  | `SKILL.md` or a `skills/` folder | skill |
  | `.claude-plugin/plugin.json` or `gemini-extension.json` | plugin |
  | `.claude-plugin/marketplace.json` listing 3 or more plugins | marketplace (fewer than 3 → plugin) |

- **Ecosystem** comes from the list a repo was found in and from topics such as `claude-code`, `codex`, `cursor` and `gemini-cli`.

Tagging is rule-based (no LLM), so a few repos are untagged or tagged loosely.

---

## How the ranking works

- Every day around **00:00 KST** (GitHub may delay scheduled runs by a few hours) the star count of every tracked repo is saved as a snapshot.
- A repo's **gain** is today's stars minus its stars **7 days ago**.
- When less than a week of history exists (right after launch, or for a repo that joined recently), the oldest snapshot available is used instead. The page then shows the shorter window next to the number, for example `+40 · 2d`.
- **Fastest growing** divides the gain by the star count at the start of the window.

### Skills

**Every skill on the skills.sh leaderboards is tracked**, about 13,500 a day: the all-time list (about 9,900 skills) plus the 24-hour trending list (about 9,950, including new skills not yet on the all-time list). They are read from the public JSON that skills.sh's own leaderboard page loads, about 100 paged requests a day spaced 2 seconds apart.

- **Gain** is today's all-time install count minus the count 7 days ago, like stars. Skills that are only on the trending list have no all-time count; they show their 24-hour installs.
- **Trending** means the top 300 of skills.sh's 24-hour list. A skill enters or leaves it on the first day it crosses that line.
- Install counts are skills.sh's CLI telemetry, taken as reported.

---

## How it works

```mermaid
flowchart LR
  A[Curated lists] --> R
  B[GitHub topics<br/>Mondays] --> R
  C[GitHub Trending<br/>repos + developers] --> R
  M[Manual picks] --> R
  R[(registry.json<br/>tracked repos)] --> S[Daily snapshot<br/>stars per repo]
  S --> G{Gate}
  G -- pass --> K[Commit data<br/>to the repo]
  G -- fail --> I[Open an issue]
  K --> T[Build trending.json<br/>+ RSS feed]
  T --> P[Deploy to<br/>GitHub Pages]
  K -. Mondays .-> D[Weekly digest<br/>GitHub Release]
```

Everything runs in one GitHub Actions workflow, [`.github/workflows/daily.yml`](.github/workflows/daily.yml), with no servers, databases or API keys beyond the built-in `GITHUB_TOKEN`.

| When | Step |
|---|---|
| Mondays | Re-read the curated lists, search GitHub topics, drop repos that fell below 5k stars, publish the weekly digest |
| Every day | Check GitHub Trending, collect stars, build the rankings, run the gate, commit the data, deploy the site |

**The gate** stops a bad run from being committed. It fails when:

- the snapshot covers less than 95% of the repos
- many repos suddenly lose most of their stars (a sign of an API problem)
- a file outside `data/` changed
- an already-committed snapshot would be overwritten

When it fails, nothing is committed and an issue is opened automatically.

**Skills** run as a separate job after the repo data is committed, so a skills.sh outage never blocks the repo board. It has its own gate (today's list must have at least 95% of yesterday's skills, no mass install drops) and opens its own `skills-gate` issue.

**What is committed:** only the raw data: the registry, one small snapshot per day and `activity.json` (last push date per repo, overwritten daily) (about 30 KB compressed, about 10 MB per year). The rankings (`trending.json`) and the RSS feed are rebuilt from the snapshots on every deploy and are never committed.

For skills, the full daily lists (about 210 KB a day compressed) are too big to keep in `main`'s history. They live on the **`skills-raw`** branch, which always holds exactly one commit with the last 30 days and is force-pushed daily, so it never grows. `main` only gets the skills shown on the page each day (`data/skills/YYYY-MM-DD.json`, about 20 KB), which also serves as fallback history if `skills-raw` is ever lost. `skills.json` is rebuilt on every deploy. Until production has two days to compare, the deploy builds the Skills board from `preview/skills/` instead: two real collections taken 48 minutes apart, labelled as preview on the page.

---

## Repository layout

```
.github/workflows/daily.yml   the whole pipeline
tf/                           Python package
  sources.py                  parse curated lists → registry (+ 5k floor, pruning)
  discover.py                 GitHub topics + Trending (repos, developers)
  probe.py                    type tags from files in each repo
  collect.py                  daily star snapshot
  skills.py                   skills.sh: collect, build skills.json, gate
  build.py                    rankings → trending.json
  gate.py                     data checks before committing
  publish.py                  RSS feed + weekly digest
  gh.py, common.py            GitHub client, shared helpers
data/
  sources.json                curated lists, discovery topics, tagging rules, star floor
  overrides.json              manual picks, tag overrides, blocklist
  registry.json               tracked repos (one per line)
  snapshots/YYYY-MM-DD.json   {repo id: stars} for each day
  activity.json               {repo id: last push date}, overwritten each run
  gh-trending.json            {repo id: [days on the daily GitHub Trending page]}
  skills/YYYY-MM-DD.json      skills shown on the page that day (+ trending top 300)
raw/                          skills-raw branch checkout (gitignored): all-time/ and trending/ *.json.gz
  digests/YYYY-Www.md         weekly digests
index.html, assets/           the static page (no build step, no framework)
tools/make_og.py              regenerates the social card (assets/og.png)
tests/                        pytest
```

Repos are keyed by their GitHub node ID, so renames and transfers don't break a repo's history.

---

## Common tasks

**Add a repo that is missing** (for example one under 5k stars, or one with no topics that no list mentions): add it to `include` in [`data/overrides.json`](data/overrides.json) with its tags.

```json
"tobi/qmd": { "type": ["tool", "mcp"], "scope": ["general"] }
```

**Hide a repo:** add `"owner/name"` to `block` in the same file.

**Fix a repo's tags:** add it under `tags` in the same file; manual tags always win.

**Add a curated list:** add an entry to `sources` in [`data/sources.json`](data/sources.json). Optional fields:

- `tags`: default type and ecosystem for everything in the list
- `skip_sections`: regular expressions for list sections to ignore
- `section_rules: false`: don't guess types from section headings
- `require_keywords: true`: only keep agent-related repos from a broad list

**Change the star floor or the discovery topics:** edit `min_stars` and `discovery` in `data/sources.json`.

All of these take effect on the next Monday run. To apply them now, use **Actions → daily → Run workflow**:

- **`sync_sources`**: re-read the lists and update the registry. This also collects today's stars, if they were not collected yet.
- **`deploy_only`**: just rebuild and redeploy the site, with no collection.

---

## Local development

Requires [uv](https://docs.astral.sh/uv/) and either the GitHub CLI logged in (`gh auth login`) or a `GITHUB_TOKEN` in the environment.

```bash
uv sync                                   # Python 3.12 + dependencies
uv run pytest -q                          # tests

uv run python -m tf.sources               # re-read curated lists (about 3 min)
uv run python -m tf.discover              # topics + trending (--trending-only, --since daily,weekly,monthly)
uv run python -m tf.collect               # today's snapshot
uv run python -m tf.build                 # data/trending.json
uv run python -m tf.gate                  # the checks the workflow runs

git fetch origin skills-raw && mkdir -p raw && git archive FETCH_HEAD | tar -x -C raw
uv run python -m tf.skills collect        # today's skills.sh lists into raw/ (about 5 min)
uv run python -m tf.skills build          # data/skills.json (run before tf.build)
uv run python -m tf.publish feed --out feed.xml
uv run python -m tf.publish digest --force

python3 -m http.server                    # then open http://localhost:8000
```

Only the scheduled workflow should commit snapshots. If you collect locally to try something out, don't commit `data/snapshots/`. To try the page on throwaway data, build from another folder:

```bash
uv run python -m tf.build --snapshots .preview/snapshots --preview
```

---

Data comes from the public GitHub API and skills.sh. Star counts are taken as reported, and repos are not checked for star manipulation.
