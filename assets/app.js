(() => {
  "use strict";

  /* ================================================================ config
   * One page, two boards. TABS describes every tab once (how it ranks, what it shows);
   * BOARDS holds only what differs between Repos and Skills. Ranks come precomputed from the
   * build (tf/rank.py), so a filtered list always shows each item's rank on the whole board. */

  const PAGE = 50;
  const PERIOD_LABEL = { 1: "Today", 7: "7 days", 30: "30 days" };
  const TYPE_LABEL = {
    mcp: "MCP", skill: "Skills", plugin: "Plugins", marketplace: "Marketplaces", subagent: "Subagents",
    agent: "Agents", framework: "Frameworks", client: "Clients", tool: "Tools", list: "Lists", learning: "Learning",
  };

  const per = (x, p) => (x.p && x.p[p]) || {};
  // periodic: the tab follows the Today / 7 days / 30 days chips; needsPeriod: hidden until a period exists
  const TABS = {
    gain: { label: "🔥 Top gains", periodic: true, needsPeriod: true, rank: (x, p) => per(x, p).g, metric: "Gain" },
    rate: { label: "📈 Fastest growing", periodic: true, needsPeriod: true, rank: (x, p) => per(x, p).q, metric: "Growth" },
    alltime: { label: "⭐ All-time", periodic: true, rank: (x) => x.ar, prev: (x) => x.par, metric: "Gain" },
    new: { label: "✨ New", periodic: true, needsPeriod: true, rank: (x, p) => per(x, p).n, metric: "Gain" },
    trending: { label: "⚡ Trending 24h", rank: (x) => x.tr, prev: (x) => x.ptr, metric: "24h installs" },
    moves: { label: "🔀 In & out", periodic: true },
  };

  const BOARDS = {
    repos: {
      url: "data/trending.json",
      tabs: ["gain", "rate", "alltime", "new"],
      title: `What's rising in the<br><span class="hl">AI agent ecosystem</span>`,
      lede: "Agents, MCP servers, skills, plugins, marketplaces &amp; AI tools — ranked by GitHub star growth, refreshed daily.",
      search: "Search repos", nameHead: "Repository", totalHead: "Stars", unit: "stars", tipUnit: " ★",
      items: (d) => d.repos,
      tracked: (d) => `<b>${nf.format(d.count)}</b> repos tracked`,
      source: (d) => `<span><b>${d.sources.curated.length}</b> curated lists + GitHub Trending</span>`,
      matches: (r, q) => (state.type === "all" || r.type.includes(state.type)) &&
        (!q || r.name.toLowerCase().includes(q) || (r.desc || "").toLowerCase().includes(q)),
      href: (r) => `https://github.com/${r.name}`,
      avatar: (r, size) => avatar(r.name.split("/")[0], size),
      name: (r) => nameHTML(r.name),
      sub: (r) => (r.desc ? `<p class="desc" title="${esc(r.desc)}">${esc(r.desc)}</p>` : ""),
      cardDesc: (r) => esc(r.desc),
      tags: repoTags,
      extra: activityHTML,
      total: (r) => r.stars,
      totalHTML: (r) => `★ ${cf.format(r.stars)}`,
      chips: repoChips,
    },
    skills: {
      url: "data/skills.json",
      tabs: ["gain", "rate", "alltime", "trending", "moves"],
      title: `What agents are<br><span class="hl">installing</span>`,
      lede: "Agent skills from skills.sh — ranked by install growth, with daily moves in and out of the trending top 300. Refreshed daily.",
      search: "Search skills", nameHead: "Skill", totalHead: "Installs", unit: "installs", tipUnit: " installs",
      items: (d) => d.skills,
      tracked: (d) => `<b>${nf.format(d.totals.tracked)}</b> skills tracked`,
      source: () => `<span>Data from <a href="https://skills.sh" target="_blank" rel="noopener"><b>skills.sh</b></a></span>`,
      // repo-linked extras ("x") only show up when the list is narrowed to a source or a search
      matches: (s, q) => (state.source !== "all" || q || !s.x) && sameSource(s.src) && matchesQ(q, s.id, s.name, s.src),
      href: skillURL,
      avatar: skillAvatar,
      name: (s) => esc(skillName(s)),
      sub: (s) => `<p class="desc">${sourceHTML(s)}</p>`,
      cardDesc: (s) => `${esc(s.src)}${s.official ? " · official" : ""}`,
      tags: skillTags,
      extra: () => "",
      total: (s) => s.installs,
      totalHTML: (s) => (s.installs == null ? `<span title="Not on the skills.sh all-time board yet">—</span>` : cf.format(s.installs)),
      chips: sourceChips,
    },
  };

  /* ================================================================ state */
  const $ = (id) => document.getElementById(id);
  const nf = new Intl.NumberFormat("en-US");
  const cf = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // The page always opens on Repos; only an explicit ?view=skills link lands on Skills.
  const params = new URLSearchParams(location.search);
  const LEGACY_TAB = { delta: "gain" };
  const state = {
    view: params.get("view") === "skills" ? "skills" : "repos",
    tab: LEGACY_TAB[params.get("tab")] || params.get("tab") || "gain",
    period: +(params.get("period") || params.get("days")) || null,   // null = the board's default
    type: params.get("type") || "all",
    source: params.get("source") || "all",
    q: params.get("q") || "",
    limit: PAGE,
  };
  const loaded = {};        // view -> data
  const loading = {};       // view -> promise
  let skillIndex = new Map();
  const board = () => BOARDS[state.view];
  const data = () => loaded[state.view];

  /* ================================================================ formatting */
  function pct(rate) {
    const p = rate * 100;
    const digits = Math.abs(p) >= 10 ? 0 : Math.abs(p) >= 1 ? 1 : 2;
    return `${p.toFixed(digits)}%`;
  }
  function deltaHTML(d) {
    if (d == null) return `<span class="sub">—</span>`;
    if (d === 0) return `<span>0</span>`;
    const up = d > 0;
    return `<span class="arrow ${up ? "up" : "down"}" aria-hidden="true">${up ? "▲" : "▼"}</span>${up ? "+" : "−"}${nf.format(Math.abs(d))}`;
  }
  const avatar = (owner, size) =>
    `<img class="avatar" src="https://github.com/${esc(owner)}.png?size=${size * 2}" alt="" width="${size}" height="${size}" loading="lazy" decoding="async">`;
  const letterAvatar = (label, size) =>
    `<span class="avatar letter" style="width:${size}px;height:${size}px" aria-hidden="true">${esc(label.replace(/^www\./, "")[0].toUpperCase())}</span>`;
  function nameHTML(name) {
    const [o, n] = name.split("/");
    return `<span class="owner">${esc(o)}/</span>${esc(n)}`;
  }
  const ordinal = (n) => {
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
  };
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const fmtDate = (d) => new Date(`${d}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const kst = (iso) => new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Seoul", hour12: false });
  const ago = (d, ref) => {
    const n = Math.max(0, Math.round((Date.parse(ref) - Date.parse(d)) / 864e5));
    return n < 1 ? "today" : n < 30 ? `${n}d ago` : n < 365 ? `${Math.floor(n / 30)}mo ago` : `${Math.floor(n / 365)}y ago`;
  };

  /* ================================================================ periods */
  const periods = () => data().periods || [];
  // default: 7 days once collected, else the longest shorter period
  function period() {
    const ps = periods();
    if (ps.includes(state.period)) return state.period;
    return ps.includes(7) ? 7 : ps.filter((p) => p < 7).pop() ?? null;
  }
  // preview data = two collections minutes apart, labelled by the real time between them
  function periodLabel(p) {
    const d = data();
    if (d.preview && p === 1 && d.prev_collected_at) return `${Math.round((Date.parse(d.collected_at) - Date.parse(d.prev_collected_at)) / 60000)}m`;
    return `${p}d`;
  }
  // an item that joined later covers fewer days than the period
  const spanNote = (st, p) => (st.w && st.w !== p && !data().preview ? `${st.w}d` : "");

  /* ================================================================ sparkline */
  function spark(values, w, h) {
    const pad = 3;
    if (!values || values.length < 2) {
      return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true"><line class="flat" x1="${pad}" y1="${h / 2}" x2="${w - pad}" y2="${h / 2}"/></svg>`;
    }
    const min = Math.min(...values), max = Math.max(...values);
    const range = max - min || 1;
    const step = (w - pad * 2) / (values.length - 1);
    const pts = values.map((v, i) => [pad + i * step, max === min ? h / 2 : h - pad - ((v - min) / range) * (h - pad * 2)]);
    const line = pts.map((pt, i) => `${i ? "L" : "M"}${pt[0].toFixed(1)},${pt[1].toFixed(1)}`).join("");
    const area = `${line}L${pts.at(-1)[0].toFixed(1)},${h}L${pts[0][0].toFixed(1)},${h}Z`;
    const [ex, ey] = pts.at(-1);
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" data-v="${values.join(",")}" role="img" aria-label="${board().unit} from ${nf.format(values[0])} to ${nf.format(values.at(-1))}">
      <path class="area" d="${area}"/><path class="line" d="${line}" vector-effect="non-scaling-stroke"/>
      <circle class="end" cx="${ex.toFixed(1)}" cy="${ey.toFixed(1)}" r="3"/></svg>`;
  }
  const tip = $("tip");
  document.addEventListener("pointermove", (ev) => {
    const svg = ev.target.closest && ev.target.closest("svg.spark[data-v]");
    if (!svg || !data()) { tip.hidden = true; return; }
    const vals = svg.dataset.v.split(",").map(Number);
    const box = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(vals.length - 1, Math.round(((ev.clientX - box.left) / box.width) * (vals.length - 1))));
    const dates = data().spark_dates.slice(-vals.length);
    const prev = i ? vals[i] - vals[i - 1] : null;
    tip.innerHTML = `<b>${nf.format(vals[i])}</b>${board().tipUnit} ${prev == null ? "" : `(${prev >= 0 ? "+" : "−"}${nf.format(Math.abs(prev))})`}<br>${esc(fmtDate(dates[i]))}`;
    tip.style.left = `${box.left + (i / (vals.length - 1)) * box.width}px`;
    tip.style.top = `${box.top}px`;
    tip.hidden = false;
  });
  document.addEventListener("scroll", () => { tip.hidden = true; }, { passive: true });

  /* ================================================================ board-specific pieces */
  function activityHTML(r) {
    const d = data();
    const stale = r.pushed && (Date.parse(d.date) - Date.parse(r.pushed)) / 864e5 > 180;
    const c = r.created ? `created ${MONTHS[+r.created.slice(5, 7) - 1]} ${r.created.slice(0, 4)}` : "";
    const u = r.pushed ? `<span${stale ? ' class="stale" title="No pushes in 6+ months"' : ""}>updated ${ago(r.pushed, d.date)}</span>` : "";
    const line = [c, u].filter(Boolean).join(" · ");
    return line ? `<p class="activity">${line}</p>` : "";
  }
  function repoTags(r) {
    const d = data();
    const gt = r.ght ? `<span class="tag ght" title="On today's GitHub Trending page, for the ${ordinal(r.ght)} time since ${fmtDate(d.gh_trending_since || d.tracking_start)}">GitHub Trending · ${ordinal(r.ght)}</span>` : "";
    const types = r.type.map((x) => `<button class="tag" data-type="${esc(x)}">${esc(TYPE_LABEL[x] || x)}</button>`).join("");
    const sk = r.skills ? `<button class="tag skills" data-goto-skills="${esc(r.name)}" title="Open this repo's skills on the Skills board">⬇ ${nf.format(r.skills.n)} skill${r.skills.n > 1 ? "s" : ""} · ${cf.format(r.skills.installs)}</button>` : "";
    return (r.new ? `<span class="tag new">new</span>` : "") + gt + types + sk;
  }
  function repoChips() {
    const d = data();
    const chip = (val, label, n) =>
      `<button class="chip" data-type="${esc(val)}" aria-pressed="${String(state.type === val)}">${esc(label)}<span class="n">${nf.format(n)}</span></button>`;
    return chip("all", "All types", d.count) + Object.entries(d.counts.type).map(([k, n]) => chip(k, TYPE_LABEL[k] || k, n)).join("");
  }

  const skillName = (s) => s.name || s.id;
  // skills.sh paths: /owner/repo/<id> for GitHub sources, /site/<domain>/<id> otherwise; "/" inside an id is %2F
  function skillURL(s) {
    return `https://skills.sh/${s.src.includes("/") ? "" : "site/"}${s.src.split("/").map(encodeURIComponent).join("/")}/${encodeURIComponent(s.id)}`;
  }
  function skillAvatar(s, size) { return s.gh ? avatar(s.src.split("/")[0], size) : letterAvatar(s.src, size); }
  function sameSource(src) { return state.source === "all" || src.toLowerCase() === state.source.toLowerCase(); }
  function matchesQ(q, ...fields) { return !q || fields.some((f) => f && f.toLowerCase().includes(q)); }
  function splitKey(k) { const i = k.indexOf("|"); return { src: k.slice(0, i), id: k.slice(i + 1) }; }
  function lookup(k) { return skillIndex.get(k) || { ...splitKey(k), gh: /^[A-Za-z0-9-]+\/[\w.-]+$/.test(splitKey(k).src) }; }
  function sourceHTML(s) {
    return s.gh
      ? `<a class="src" href="https://github.com/${esc(s.src)}" target="_blank" rel="noopener">${esc(s.src)}</a>`
      : `<span class="src">${esc(s.src)}</span>`;
  }
  function skillTags(s) {
    const d = data(), b = [];
    if (s.official) b.push(`<span class="tag official" title="Marked official on skills.sh">official</span>`);
    if (s.tr != null && s.ptr == null && d.moves.length) b.push(`<span class="tag in">entered trending</span>`);
    else if (s.tr != null && s.streak > 1 && !d.preview) b.push(`<span class="tag streak" title="Days in the trending top ${d.trend_cut}">trending · ${s.streak}d</span>`);
    if (s.tr == null && s.ptr != null) b.push(`<span class="tag out">left trending</span>`);
    if (s.repo) b.push(`<button class="tag link" data-goto-repo="${esc(s.repo)}" title="Open ${esc(s.repo)} on the Repos board">★ ${cf.format(s.stars ?? 0)}</button>`);
    return b.join("");
  }
  function sourceChips() {
    const d = data(), counts = new Map();
    d.skills.forEach((s) => { if (!s.x) counts.set(s.src, (counts.get(s.src) || 0) + 1); });
    const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12).map(([k]) => k);
    if (state.source !== "all" && !top.some((k) => k.toLowerCase() === state.source.toLowerCase())) top.unshift(state.source);
    const on = (v) => String(v.toLowerCase() === state.source.toLowerCase());
    return `<button class="chip" data-source="all" aria-pressed="${on("all")}">All sources<span class="n">${nf.format(d.skills.filter((s) => !s.x).length)}</span></button>` +
      top.map((k) => `<button class="chip" data-source="${esc(k)}" aria-pressed="${on(k)}">${esc(k)}${counts.get(k) ? `<span class="n">${counts.get(k)}</span>` : ""}</button>`).join("");
  }

  /* ================================================================ shared rendering */
  function visibleTabs() {
    const has = periods().length > 0;
    return board().tabs.filter((t) => has || !TABS[t].needsPeriod);
  }
  function rankChange(now, before) {
    if (now == null || !data().prev_collected_at) return "";
    if (before == null) return `<span class="rc new">new</span>`;
    const d = before - now;
    return d > 0 ? `<span class="rc up">▲${d}</span>` : d < 0 ? `<span class="rc down">▼${-d}</span>` : "";
  }
  function metricHTML(x, tab, p) {
    if (tab === "trending") return `${nf.format(x.t24)}<span class="sub">installs · 24h</span>`;
    const st = per(x, p), note = spanNote(st, p);
    if (tab === "rate") return `<span class="arrow up" aria-hidden="true">▲</span>${pct(st.r)}<span class="sub">+${nf.format(st.d)}${note ? ` · ${note}` : ""}</span>`;
    return `${deltaHTML(st.d)}${note ? `<span class="sub">${note}</span>` : ""}`;
  }
  function podiumBig(x, tab, p) {
    const b = board();
    if (tab === "trending") return `${cf.format(x.t24)}<small>installs · 24h</small>`;
    const st = per(x, p), label = p ? periodLabel(p) : "";
    if (tab === "alltime") return `${tab === "alltime" && state.view === "repos" ? "★ " : ""}${cf.format(b.total(x))}<small>${st.d ? `${deltaHTML(st.d)} · ${label}` : b.unit}</small>`;
    if (tab === "rate") return `${pct(st.r)}<small>growth · ${label}</small>`;
    return `${deltaHTML(st.d)}<small>${b.unit} · ${label}</small>`;
  }

  function renderBoard(tab, p) {
    const b = board(), T = TABS[tab];
    const q = state.q.trim().toLowerCase();
    const rows = b.items(data())
      .filter((x) => T.rank(x, p) != null && b.matches(x, q))
      .sort((x, y) => T.rank(x, p) - T.rank(y, p));
    const rankOf = (x) => T.rank(x, p);
    $("podium").innerHTML = (!q && rows.length >= 3 ? rows.slice(0, 3) : []).map((x) => `
      <a class="card" href="${esc(b.href(x))}" target="_blank" rel="noopener">
        <span class="rank-badge${rankOf(x) === 1 ? "" : " off"}">#${rankOf(x)}</span>
        <div class="card-head">${b.avatar(x, 28)}<span class="name">${b.name(x)}</span></div>
        <div class="big">${podiumBig(x, tab, p)}</div>
        <p class="desc">${b.cardDesc(x)}</p>
        ${spark(x.spark, 280, 44)}
      </a>`).join("");
    $("head-name").textContent = b.nameHead;
    $("head-total").textContent = b.totalHead;
    $("head-metric").textContent = tab === "trending" ? T.metric : p ? `${T.metric} (${periodLabel(p)})` : T.metric;
    $("list").innerHTML = rows.slice(0, state.limit).map((x) => `
      <li class="row">
        <span class="rank${rankOf(x) >= 1000 ? " long" : ""}">${rankOf(x)}${T.prev ? rankChange(rankOf(x), T.prev(x)) : ""}</span>
        <div class="repo">
          ${b.avatar(x, 32)}
          <div class="repo-body">
            <a class="name" href="${esc(b.href(x))}" target="_blank" rel="noopener">${b.name(x)}</a>
            ${b.sub(x)}
            <div class="tags">${b.tags(x)}</div>
            ${b.extra(x)}
          </div>
        </div>
        <span class="num stars">${b.totalHTML(x)}</span>
        <span class="num metric">${metricHTML(x, tab, p)}</span>
        <span class="trend">${spark(x.spark, 120, 32)}</span>
      </li>`).join("");
    $("empty").textContent = "Nothing matches these filters.";
    $("empty").hidden = rows.length > 0;
    $("more").hidden = rows.length <= state.limit;
    $("more").textContent = `Show more (${nf.format(rows.length - state.limit)} left)`;
  }

  function renderMoves(p) {
    const d = data(), box = $("moves");
    $("podium").innerHTML = "";
    $("more").hidden = true;
    if (!d.moves.length) {
      box.innerHTML = "";
      $("empty").hidden = false;
      $("empty").textContent = "Moves appear after the second daily run, once there is a previous day to compare with.";
      return;
    }
    const q = state.q.trim().toLowerCase();
    const days = d.moves.slice(0, p);
    const keep = (m) => { const s = lookup(m.k); return sameSource(s.src) && matchesQ(q, s.id, s.name, s.src); };
    const ins = days.flatMap((day) => day.in.filter(keep).map((m) => ({ ...m, date: day.date })));
    const outs = days.flatMap((day) => day.out.filter(keep).map((m) => ({ ...m, date: day.date })));
    const multi = p > 1;
    const item = (m, entered) => {
      const s = lookup(m.k);
      const sub = [m.t != null ? `${cf.format(m.t)} / 24h` : "", !entered && m.d ? `${m.d}d in` : "", multi ? fmtDate(m.date) : ""].filter(Boolean).join(" · ");
      return `<li>${skillAvatar(s, 24)}
        <div class="mv-body"><a class="name" href="${esc(skillURL(s))}" target="_blank" rel="noopener">${esc(skillName(s))}</a><span class="src">${esc(s.src)}</span></div>
        <div class="mv-num"><b>${entered ? `#${m.r}` : `was #${m.r}`}</b><span>${sub}</span></div></li>`;
    };
    box.innerHTML = `
      <p class="mv-range">Trending top ${d.trend_cut} · ${fmtDate(days.at(-1).from)} → ${fmtDate(days[0].date)}</p>
      <div class="mv-cols">
        <section class="mv in"><h3><span>Entered</span><span>+${nf.format(ins.length)}</span></h3>
          <ul>${ins.map((m) => item(m, true)).join("") || `<li class="none">None</li>`}</ul></section>
        <section class="mv out"><h3><span>Left</span><span>−${nf.format(outs.length)}</span></h3>
          <ul>${outs.map((m) => item(m, false)).join("") || `<li class="none">None</li>`}</ul></section>
      </div>`;
    $("empty").hidden = true;
  }

  function renderChrome(tabs, tab, p) {
    const d = data(), b = board();
    document.documentElement.dataset.view = state.view;
    document.querySelectorAll(".mode button").forEach((el) => el.setAttribute("aria-pressed", String(el.dataset.view === state.view)));
    $("title").innerHTML = b.title;
    $("lede").innerHTML = b.lede;
    $("q").placeholder = b.search;
    $("tabs").innerHTML = tabs.map((t) => `<button role="tab" data-tab="${t}" aria-selected="${String(t === tab)}">${TABS[t].label}</button>`).join("");
    $("type-chips").innerHTML = b.chips();
    // period chips open as history grows: 7 days after a week of data, 30 days after a month
    const ps = periods();
    $("period-chips").innerHTML = TABS[tab].periodic && ps.length
      ? Object.entries(PERIOD_LABEL).map(([k, label]) => {
        const n = +k, ok = ps.includes(n);
        return `<button class="chip" data-period="${n}" aria-pressed="${String(n === p)}"${ok ? "" : ` disabled title="Available after ${n} days of data"`}>${label}</button>`;
      }).join("")
      : "";
    $("meta").innerHTML = [
      `<span class="live">Updated <b>${esc(kst(d.collected_at))} KST</b></span>`,
      `<span>${b.tracked(d)}</span>`,
      b.source(d),
    ].join("");
    let msg = "";
    if (d.preview) msg = `Preview data: gains below come from two collections taken ${periodLabel(1)} apart. Daily collection runs around 00:00 KST.`;
    else if (!ps.length) msg = "Collecting the first baseline — growth rankings appear after the next daily run (around 00:00 KST). Showing all-time totals meanwhile.";
    else if (!ps.includes(7)) msg = `Tracking started ${fmtDate(d.tracking_start)}: the 7-day view opens after a week of data, the 30-day view after a month.`;
    $("notice").hidden = !msg;
    $("notice").textContent = msg;
  }

  function render() {
    if (!data()) return;
    const tabs = visibleTabs();
    if (!tabs.includes(state.tab)) state.tab = tabs.includes("gain") ? "gain" : "alltime";
    const tab = state.tab, p = period();
    renderChrome(tabs, tab, p);
    const moves = tab === "moves";
    $("moves").hidden = !moves;
    $("list").hidden = moves;
    $("head").hidden = moves;
    if (moves) renderMoves(p); else renderBoard(tab, p);
    syncURL(p);
  }

  function syncURL(p) {
    const u = new URLSearchParams();
    if (state.view === "skills") u.set("view", "skills");
    if (state.tab !== "gain") u.set("tab", state.tab);
    if (state.period && state.period === p) u.set("period", p);
    if (state.view === "repos" && state.type !== "all") u.set("type", state.type);
    if (state.view === "skills" && state.source !== "all") u.set("source", state.source);
    if (state.q) u.set("q", state.q);
    const qs = u.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  /* ================================================================ loading */
  function load(view) {
    if (loaded[view]) return Promise.resolve(loaded[view]);
    loading[view] ||= fetch(BOARDS[view].url, { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((d) => {
        loaded[view] = d;
        if (view === "skills") skillIndex = new Map(d.skills.map((s) => [s.k, s]));
        return d;
      })
      .catch((err) => { loading[view] = null; throw err; });
    return loading[view];
  }

  function switchView(view, patch = {}) {
    Object.assign(state, { view, tab: "gain", q: "", limit: PAGE }, patch);
    $("q").value = state.q;
    if (!loaded[view]) $("meta").textContent = "Loading…";
    load(view).then(() => { render(); window.scrollTo({ top: 0, behavior: "smooth" }); }).catch((err) => {
      if (view === "repos") { $("meta").textContent = `Could not load data (${err.message}).`; return; }
      switchView("repos");
      $("notice").hidden = false;
      $("notice").textContent = `Could not load skills data (${err.message}).`;
    });
  }

  /* ================================================================ events */
  document.querySelector(".mode").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-view]");
    if (b && b.dataset.view !== state.view) switchView(b.dataset.view);
  });
  $("tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (!b) return;
    state.tab = b.dataset.tab; state.limit = PAGE; render();
  });
  document.addEventListener("click", (e) => {
    const g = e.target.closest("[data-goto-skills],[data-goto-repo]");
    if (g) {
      e.preventDefault();
      // All-time lists every skill the badge counted (Top gains would hide the ones without gains)
      if (g.dataset.gotoSkills) switchView("skills", { source: g.dataset.gotoSkills, tab: "alltime" });
      else switchView("repos", { q: g.dataset.gotoRepo, tab: "alltime" });
      return;
    }
    const t = e.target.closest("[data-type],[data-source],[data-period]");
    if (!t || t.disabled) return;
    if (t.dataset.type) state.type = t.dataset.type === state.type && t.classList.contains("tag") ? "all" : t.dataset.type;
    if (t.dataset.source) state.source = t.dataset.source;
    if (t.dataset.period) state.period = +t.dataset.period;
    state.limit = PAGE; render();
    if (t.classList.contains("tag")) document.querySelector(".controls").scrollIntoView({ behavior: "smooth" });
  });
  let qTimer;
  $("q").value = state.q;
  $("q").addEventListener("input", (e) => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { state.q = e.target.value; state.limit = PAGE; render(); }, 120);
  });
  $("more").addEventListener("click", () => { state.limit += PAGE; render(); });

  /* ================================================================ boot */
  function renderFooter(d) {
    const cnt = (c) => `<span class="n">${nf.format(c)}</span>`;
    $("discovery").innerHTML = d.sources.discovery.map((s) =>
      `<li><a href="${esc(s.url)}" target="_blank" rel="noopener"${s.detail ? ` title="${esc(s.detail)}"` : ""}>${esc(s.label)}</a>${cnt(s.count)}</li>`).join("");
    $("curated-count").textContent = `(${d.sources.curated.length})`;
    $("sources").innerHTML = d.sources.curated.map((s) =>
      `<li><a href="https://github.com/${esc(s.repo)}" target="_blank" rel="noopener">${esc(s.repo)}</a>${cnt(s.count)}</li>`).join("");
  }

  load("repos")
    .then((d) => {
      renderFooter(d);
      if (state.view === "skills") {
        return load("skills").then(render).catch((err) => {
          switchView("repos");
          $("notice").hidden = false;
          $("notice").textContent = `Could not load skills data (${err.message}).`;
        });
      }
      render();
    })
    .catch((err) => { $("meta").textContent = `Could not load data (${err.message}).`; });
})();
