(() => {
  "use strict";

  const PAGE = 50;
  const TYPE_LABEL = {
    mcp: "MCP", skill: "Skills", plugin: "Plugins", marketplace: "Marketplaces", subagent: "Subagents",
    agent: "Agents", framework: "Frameworks", client: "Clients", tool: "Tools", list: "Lists", learning: "Learning",
  };
  const SCOPE_LABEL = {
    general: "General", "claude-code": "Claude Code", codex: "Codex", cursor: "Cursor", "gemini-cli": "Gemini CLI",
  };
  const TABS = {
    repos: {
      delta: { label: "🔥 Top gains", metric: "Gain" },
      rate: { label: "📈 Fastest growing", metric: "Growth" },
      new: { label: "✨ New", metric: "Gain" },
      alltime: { label: "⭐ All-time", metric: "Gain" },
    },
    skills: {
      gain: { label: "🔥 Top gains", metric: "Installs" },
      trending: { label: "⚡ Trending 24h", metric: "24h" },
      moves: { label: "🔀 In & out" },
      rate: { label: "📈 Fastest growing", metric: "Growth" },
      alltime: { label: "⭐ All-time", metric: "Gain" },
    },
  };
  const DEFAULT_TAB = { repos: "delta", skills: "gain" };
  const INTRO = {
    repos: {
      title: `What's rising in the<br><span class="hl">AI agent ecosystem</span>`,
      lede: "Agents, MCP servers, skills, plugins, marketplaces &amp; AI tools — ranked by GitHub star growth, refreshed daily.",
      search: "Search repos",
    },
    skills: {
      title: `What agents are<br><span class="hl">installing</span>`,
      lede: "Agent skills from skills.sh — ranked by install growth, with daily moves in and out of the trending top 300. Refreshed daily.",
      search: "Search skills",
    },
  };

  const $ = (id) => document.getElementById(id);
  const nf = new Intl.NumberFormat("en-US");
  const cf = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // The page always opens on Repos; only an explicit ?view=skills link lands on Skills.
  const params = new URLSearchParams(location.search);
  const view0 = params.get("view") === "skills" ? "skills" : "repos";
  const state = {
    view: view0,
    tab: TABS[view0][params.get("tab")] ? params.get("tab") : DEFAULT_TAB[view0],
    type: params.get("type") || "all",
    scope: params.get("scope") || "all",
    source: params.get("source") || "all",
    days: [1, 7, 30].includes(+params.get("days")) ? +params.get("days") : 1,
    q: params.get("q") || "",
    limit: PAGE,
  };
  let data = null;      // repos (trending.json)
  let sdata = null;     // skills (skills.json)
  let hasDeltas = false;
  let skillsLoading = null;
  const cur = () => (state.view === "skills" ? sdata : data);

  /* ---------- theme ---------- */
  $("theme").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  });

  /* ---------- formatting ---------- */
  const span = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 864e5);
  const curWindow = () => span(data.baseline_date, data.date);
  const skillWindow = () => span(sdata.baseline_date, sdata.date);
  // preview data = two manual collections minutes apart, labelled by the real time between them
  const skillWin = (days) => sdata.preview
    ? `${Math.round((Date.parse(sdata.collected_at) - Date.parse(sdata.baseline_collected_at)) / 60000)}m`
    : `${days}d`;
  function windowLabel(days) {
    if (state.view === "repos" && data && data.preview) {
      const mins = Math.round((Date.parse(data.latest_collected_at) - Date.parse(data.baseline_collected_at)) / 60000);
      return `${mins}m`;
    }
    return `${days}d`;
  }
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
  function rankChange(now, before) {
    if (now == null || !sdata.moves.length) return "";
    if (before == null) return `<span class="rc new">new</span>`;
    const d = before - now;
    return d > 0 ? `<span class="rc up">▲${d}</span>` : d < 0 ? `<span class="rc down">▼${-d}</span>` : "";
  }
  const avatar = (owner, size) =>
    `<img class="avatar" src="https://github.com/${esc(owner)}.png?size=${size * 2}" alt="" width="${size}" height="${size}" loading="lazy" decoding="async">`;
  const letterAvatar = (label, size) =>
    `<span class="avatar letter" style="width:${size}px;height:${size}px" aria-hidden="true">${esc(label.replace(/^www\./, "")[0].toUpperCase())}</span>`;
  const nameHTML = (name) => {
    const [o, n] = name.split("/");
    return `<span class="owner">${esc(o)}/</span>${esc(n)}`;
  };
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const fmtDate = (d) => new Date(`${d}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const ago = (d, ref) => {
    const n = Math.max(0, Math.round((Date.parse(ref) - Date.parse(d)) / 864e5));
    return n < 1 ? "today" : n < 30 ? `${n}d ago` : n < 365 ? `${Math.floor(n / 30)}mo ago` : `${Math.floor(n / 365)}y ago`;
  };

  /* ---------- sparkline ---------- */
  function spark(values, w, h, cls = "") {
    const pad = 3;
    if (!values || values.length < 2) {
      return `<svg class="spark ${cls}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><line class="flat" x1="${pad}" y1="${h / 2}" x2="${w - pad}" y2="${h / 2}"/></svg>`;
    }
    const min = Math.min(...values), max = Math.max(...values);
    const range = max - min || 1;
    const step = (w - pad * 2) / (values.length - 1);
    const pts = values.map((v, i) => [pad + i * step, max === min ? h / 2 : h - pad - ((v - min) / range) * (h - pad * 2)]);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
    const area = `${line}L${pts.at(-1)[0].toFixed(1)},${h}L${pts[0][0].toFixed(1)},${h}Z`;
    const [ex, ey] = pts.at(-1);
    const unit = state.view === "skills" ? "Installs" : "Stars";
    return `<svg class="spark ${cls}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" data-v="${values.join(",")}" role="img" aria-label="${unit} from ${nf.format(values[0])} to ${nf.format(values.at(-1))}">
      <path class="area" d="${area}"/><path class="line" d="${line}" vector-effect="non-scaling-stroke"/>
      <circle class="end" cx="${ex.toFixed(1)}" cy="${ey.toFixed(1)}" r="3"/></svg>`;
  }

  // hover: nearest point -> date + value
  const tip = $("tip");
  document.addEventListener("pointermove", (ev) => {
    const svg = ev.target.closest && ev.target.closest("svg.spark[data-v]");
    if (!svg || !cur()) { tip.hidden = true; return; }
    const vals = svg.dataset.v.split(",").map(Number);
    const box = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(vals.length - 1, Math.round(((ev.clientX - box.left) / box.width) * (vals.length - 1))));
    const dates = cur().window_dates.slice(-vals.length);
    const prev = i ? vals[i] - vals[i - 1] : null;
    const unit = state.view === "skills" ? " installs" : " ★";
    tip.innerHTML = `<b>${nf.format(vals[i])}</b>${unit} ${prev == null ? "" : `(${prev >= 0 ? "+" : "−"}${nf.format(Math.abs(prev))})`}<br>${esc(fmtDate(dates[i]))}`;
    tip.style.left = `${box.left + (i / (vals.length - 1)) * box.width}px`;
    tip.style.top = `${box.top}px`;
    tip.hidden = false;
  });
  document.addEventListener("scroll", () => { tip.hidden = true; }, { passive: true });

  /* ================================================================ repos */
  function activityHTML(r) {
    const stale = r.pushed && (Date.parse(data.date) - Date.parse(r.pushed)) / 864e5 > 180;
    const c = r.created ? `created ${MONTHS[+r.created.slice(5, 7) - 1]} ${r.created.slice(0, 4)}` : "";
    const u = r.pushed ? `<span${stale ? ' class="stale" title="No pushes in 6+ months"' : ""}>updated ${ago(r.pushed, data.date)}</span>` : "";
    const line = [c, u].filter(Boolean).join(" · ");
    return line ? `<p class="activity">${line}</p>` : "";
  }
  function repoMetricHTML(r) {
    const win = r.window && r.window !== curWindow() && !data.preview ? windowLabel(r.window) : "";
    if (state.tab === "rate") {
      return `<span class="arrow up" aria-hidden="true">▲</span>${pct(r.rate)}<span class="sub">+${nf.format(r.delta)}${win ? ` · ${win}` : ""}</span>`;
    }
    return `${deltaHTML(r.delta)}${win ? `<span class="sub">${win}</span>` : ""}`;
  }
  function filteredRepos() {
    const q = state.q.trim().toLowerCase();
    const rs = data.repos.filter((r) =>
      (state.type === "all" || r.type.includes(state.type)) &&
      (state.scope === "all" || r.scope.includes(state.scope)) &&
      (!q || r.name.toLowerCase().includes(q) || (r.desc || "").toLowerCase().includes(q)));
    const byDelta = (a, b) => (b.delta ?? -Infinity) - (a.delta ?? -Infinity) || b.stars - a.stars;
    if (!hasDeltas || state.tab === "alltime") return rs.sort((a, b) => b.stars - a.stars);
    if (state.tab === "rate") return rs.filter((r) => r.rate > 0 && r.base >= data.rate_min_base).sort((a, b) => b.rate - a.rate || byDelta(a, b));
    if (state.tab === "new") return rs.filter((r) => r.new).sort(byDelta);
    return rs.filter((r) => r.delta != null).sort(byDelta);
  }
  function repoTagsHTML(r) {
    const t = r.type.map((x) => `<button class="tag" data-type="${esc(x)}">${esc(TYPE_LABEL[x] || x)}</button>`);
    const s = r.scope.filter((x) => x !== "general").map((x) => `<button class="tag scope" data-scope="${esc(x)}">${esc(SCOPE_LABEL[x] || x)}</button>`);
    const sk = r.skills ? `<button class="tag skills" data-goto-skills="${esc(r.name)}" title="Open this repo's skills on the Skills board">⬇ ${nf.format(r.skills.n)} skill${r.skills.n > 1 ? "s" : ""} · ${cf.format(r.skills.installs)}</button>` : "";
    return (r.new ? `<span class="tag new">new</span>` : "") + t.join("") + s.join("") + sk;
  }
  function repoPodiumBig(r) {
    if (state.tab === "alltime") return `★ ${cf.format(r.stars)}<small>${r.delta ? `${deltaHTML(r.delta)} · ${windowLabel(r.window)}` : "stars"}</small>`;
    if (state.tab === "rate") return `${pct(r.rate)}<small>growth · ${windowLabel(r.window)}</small>`;
    return `${deltaHTML(r.delta)}<small>stars · ${windowLabel(r.window)}</small>`;
  }
  function renderRepos() {
    const rs = filteredRepos();
    const podium = (hasDeltas || state.tab === "alltime") && !state.q && rs.length >= 3 ? rs.slice(0, 3) : [];
    $("podium").innerHTML = podium.map((r, i) => `
      <a class="card" href="https://github.com/${esc(r.name)}" target="_blank" rel="noopener">
        <span class="rank-badge">#${i + 1}</span>
        <div class="card-head">${avatar(r.name.split("/")[0], 28)}<span class="name">${nameHTML(r.name)}</span></div>
        <div class="big">${repoPodiumBig(r)}</div>
        <p class="desc">${esc(r.desc)}</p>
        ${spark(r.spark, 280, 44)}
      </a>`).join("");
    const shown = rs.slice(0, state.limit);
    setHead("Repository", "Stars", hasDeltas ? `${TABS.repos[state.tab].metric} (${windowLabel(curWindow())})` : "Gain");
    $("list").innerHTML = shown.map((r, i) => `
      <li class="row">
        <span class="rank">${i + 1}</span>
        <div class="repo">
          ${avatar(r.name.split("/")[0], 32)}
          <div class="repo-body">
            <a class="name" href="https://github.com/${esc(r.name)}" target="_blank" rel="noopener">${nameHTML(r.name)}</a>
            ${r.desc ? `<p class="desc" title="${esc(r.desc)}">${esc(r.desc)}</p>` : ""}
            <div class="tags">${repoTagsHTML(r)}</div>
            ${activityHTML(r)}
          </div>
        </div>
        <span class="num stars">★ ${cf.format(r.stars)}</span>
        <span class="num metric">${repoMetricHTML(r)}</span>
        <span class="trend">${spark(r.spark, 120, 32)}</span>
      </li>`).join("");
    finishList(rs.length);
  }
  function renderReposChrome() {
    const chip = (attr, val, label, n) =>
      `<button class="chip" data-${attr}="${esc(val)}" aria-pressed="${String(state[attr] === val)}">${esc(label)}${n != null ? `<span class="n">${nf.format(n)}</span>` : ""}</button>`;
    $("type-chips").innerHTML = chip("type", "all", "All types", data.count) +
      Object.entries(data.counts.type).map(([k, n]) => chip("type", k, TYPE_LABEL[k] || k, n)).join("");
    $("scope-chips").innerHTML = chip("scope", "all", "All ecosystems") +
      Object.keys(data.counts.scope).map((k) => chip("scope", k, SCOPE_LABEL[k] || k)).join("");
    $("meta").innerHTML = [
      `<span class="live">Updated <b>${esc(kst(data.latest_collected_at))} KST</b></span>`,
      `<span><b>${nf.format(data.count)}</b> repos tracked</span>`,
      `<span>Window <b>${esc(windowLabel(curWindow()))}</b></span>`,
      `<span><b>${data.sources.curated.length}</b> curated lists + GitHub Trending</span>`,
    ].join("");
    let msg = "";
    if (data.preview) msg = `Preview data: rankings below come from two test snapshots taken ${windowLabel(1)} apart. Daily collection runs around 00:00 KST.`;
    else if (!hasDeltas) msg = "Collecting the first baseline — growth rankings appear after the next daily run (around 00:00 KST). Showing all-time stars meanwhile.";
    else if (curWindow() < data.window_max) msg = `Tracking started ${fmtDate(data.tracking_start)}: growth is measured over the ${curWindow()} day(s) collected so far until a full 7-day window exists.`;
    notice(msg);
    $("pulse").hidden = true;
  }

  /* ================================================================ skills */
  const skillName = (s) => s.name || s.id;
  const skillURL = (s) => `https://skills.sh/${s.src}/${s.id}`.replace(/[^\w/:.\-~%&]/g, encodeURIComponent);
  const skillAvatar = (s, size) => (s.gh ? avatar(s.src.split("/")[0], size) : letterAvatar(s.src, size));
  const hasMoves = () => sdata.moves.length > 0;
  const sameSource = (src) => state.source === "all" || src.toLowerCase() === state.source.toLowerCase();
  const matchesQ = (q, ...fields) => !q || fields.some((f) => f && f.toLowerCase().includes(q));
  let skillIndex = null;
  const splitKey = (k) => { const i = k.indexOf("|"); return { src: k.slice(0, i), id: k.slice(i + 1) }; };
  const lookup = (k) => skillIndex.get(k) || { ...splitKey(k), gh: /^[A-Za-z0-9-]+\/[\w.-]+$/.test(splitKey(k).src) };

  function filteredSkills() {
    const q = state.q.trim().toLowerCase();
    const rs = sdata.skills.filter((s) => sameSource(s.src) && matchesQ(q, s.id, s.name, s.src));
    const has = sdata.has_history;
    const tab = !has && (state.tab === "gain" || state.tab === "rate") ? "alltime" : state.tab;
    if (tab === "trending") return rs.filter((s) => s.tr != null).sort((a, b) => a.tr - b.tr);
    if (tab === "rate") return rs.filter((s) => s.rate > 0 && s.base >= sdata.rate_min_base).sort((a, b) => b.rate - a.rate);
    if (tab === "alltime") return rs.filter((s) => s.ar != null).sort((a, b) => a.ar - b.ar);
    return rs.filter((s) => s.delta != null && s.delta > 0).sort((a, b) => b.delta - a.delta || (a.ar ?? 1e9) - (b.ar ?? 1e9));
  }
  function skillBadges(s) {
    const b = [];
    if (s.official) b.push(`<span class="tag official" title="Marked official on skills.sh">official</span>`);
    if (s.tr != null && s.ptr == null && hasMoves()) b.push(`<span class="tag in">entered trending</span>`);
    else if (s.tr != null && s.streak > 1 && !sdata.preview) b.push(`<span class="tag streak" title="Days in the trending top ${sdata.trend_cut}">trending · ${s.streak}d</span>`);
    if (s.tr == null && s.ptr != null) b.push(`<span class="tag out">left trending</span>`);
    if (s.repo) b.push(`<button class="tag link" data-goto-repo="${esc(s.repo)}" title="Open ${esc(s.repo)} on the Repos board">★ ${cf.format(s.stars ?? 0)}</button>`);
    return b.join("");
  }
  function sourceHTML(s) {
    return s.gh
      ? `<a class="src" href="https://github.com/${esc(s.src)}" target="_blank" rel="noopener">${esc(s.src)}</a>`
      : `<span class="src">${esc(s.src)}</span>`;
  }
  function skillMetricHTML(s, tab) {
    const win = s.window && s.window !== skillWindow() && !sdata.preview ? skillWin(s.window) : "";
    if (tab === "trending") return `${nf.format(s.t24)}<span class="sub">installs · 24h</span>`;
    if (tab === "rate") return `<span class="arrow up" aria-hidden="true">▲</span>${pct(s.rate)}<span class="sub">+${nf.format(s.delta)}${win ? ` · ${win}` : ""}</span>`;
    const sub = s.d1 != null && tab === "gain" && !sdata.preview ? `+${nf.format(s.d1)} today${win ? ` · ${win}` : ""}` : win;
    return `${deltaHTML(s.delta)}${sub ? `<span class="sub">${sub}</span>` : ""}`;
  }
  function skillRank(s, i, tab) {
    if (tab === "trending") return `${s.tr}${rankChange(s.tr, s.ptr)}`;
    if (tab === "alltime") return `${s.ar}${rankChange(s.ar, s.par)}`;
    return `${i + 1}`;
  }
  function skillPodiumBig(s, tab) {
    if (tab === "trending") return `${cf.format(s.t24)}<small>installs · 24h</small>`;
    if (tab === "alltime") return `${cf.format(s.installs)}<small>${s.delta ? `${deltaHTML(s.delta)} · ${skillWin(s.window)}` : "installs"}</small>`;
    if (tab === "rate") return `${pct(s.rate)}<small>growth · ${skillWin(s.window)}</small>`;
    return `${deltaHTML(s.delta)}<small>installs · ${skillWin(s.window)}</small>`;
  }
  function renderSkills() {
    const tab = !sdata.has_history && (state.tab === "gain" || state.tab === "rate") ? "alltime" : state.tab;
    if (tab === "moves") return renderMoves();
    $("moves").hidden = true;
    $("list").hidden = false;
    $("head").hidden = false;
    const rs = filteredSkills();
    const podium = !state.q && rs.length >= 3 ? rs.slice(0, 3) : [];
    $("podium").innerHTML = podium.map((s, i) => `
      <a class="card" href="${esc(skillURL(s))}" target="_blank" rel="noopener">
        <span class="rank-badge">#${i + 1}</span>
        <div class="card-head">${skillAvatar(s, 28)}<span class="name">${esc(skillName(s))}</span></div>
        <div class="big">${skillPodiumBig(s, tab)}</div>
        <p class="desc">${esc(s.src)}${s.official ? " · official" : ""}</p>
        ${spark(s.spark, 280, 44)}
      </a>`).join("");
    const metric = tab === "trending" ? "24h installs" : `${TABS.skills[tab].metric} (${skillWin(skillWindow())})`;
    setHead("Skill", "Installs", sdata.has_history || tab === "trending" ? metric : "Gain");
    $("list").innerHTML = rs.slice(0, state.limit).map((s, i) => `
      <li class="row">
        <span class="rank">${skillRank(s, i, tab)}</span>
        <div class="repo">
          ${skillAvatar(s, 32)}
          <div class="repo-body">
            <a class="name" href="${esc(skillURL(s))}" target="_blank" rel="noopener">${esc(skillName(s))}</a>
            <p class="desc">${sourceHTML(s)}</p>
            <div class="tags">${skillBadges(s)}</div>
          </div>
        </div>
        <span class="num stars"${s.installs == null ? ' title="Not on the skills.sh all-time board yet"' : ""}>${s.installs == null ? "—" : cf.format(s.installs)}</span>
        <span class="num metric">${skillMetricHTML(s, tab)}</span>
        <span class="trend">${spark(s.spark, 120, 32)}</span>
      </li>`).join("");
    finishList(rs.length);
  }

  function renderMoves() {
    $("podium").innerHTML = "";
    $("list").hidden = true;
    $("head").hidden = true;
    $("more").hidden = true;
    const box = $("moves");
    box.hidden = false;
    if (!hasMoves()) {
      box.innerHTML = "";
      $("empty").hidden = false;
      $("empty").textContent = "Moves appear after the second daily run, once there is a previous day to compare with.";
      return;
    }
    const q = state.q.trim().toLowerCase();
    const days = sdata.moves.slice(0, state.days);
    const keep = (m) => { const s = lookup(m.k); return sameSource(s.src) && matchesQ(q, s.id, s.name, s.src); };
    const ins = days.flatMap((d) => d.in.filter(keep).map((m) => ({ ...m, date: d.date })));
    const outs = days.flatMap((d) => d.out.filter(keep).map((m) => ({ ...m, date: d.date })));
    const multi = state.days > 1;
    const item = (m, entered) => {
      const s = lookup(m.k);
      const right = entered ? `#${m.r}` : `was #${m.r}`;
      const sub = [m.t != null ? `${cf.format(m.t)} / 24h` : "", !entered && m.d ? `${m.d}d in` : "", multi ? fmtDate(m.date) : ""].filter(Boolean).join(" · ");
      return `<li>${skillAvatar(s, 24)}
        <div class="mv-body"><a class="name" href="${esc(skillURL(s))}" target="_blank" rel="noopener">${esc(skillName(s))}</a><span class="src">${esc(s.src)}</span></div>
        <div class="mv-num"><b>${right}</b><span>${sub}</span></div></li>`;
    };
    const range = multi ? `${fmtDate(days.at(-1).from)} → ${fmtDate(days[0].date)}` : `${fmtDate(days[0].from)} → ${fmtDate(days[0].date)}`;
    box.innerHTML = `
      <p class="mv-range">Trending top ${sdata.trend_cut} · ${range}</p>
      <div class="mv-cols">
        <section class="mv in"><h3><span>Entered</span><span>+${nf.format(ins.length)}</span></h3>
          <ul>${ins.map((m) => item(m, true)).join("") || `<li class="none">None</li>`}</ul></section>
        <section class="mv out"><h3><span>Left</span><span>−${nf.format(outs.length)}</span></h3>
          <ul>${outs.map((m) => item(m, false)).join("") || `<li class="none">None</li>`}</ul></section>
      </div>`;
    $("empty").hidden = true;
  }

  function renderPulse() {
    const today = sdata.moves[0];
    const riser = sdata.skills.filter((s) => s.rate > 0 && s.base >= sdata.rate_min_base).sort((a, b) => b.rate - a.rate)[0];
    const names = (xs) => xs.slice(0, 3).map((m) => esc(skillName(lookup(m.k)))).join(", ");
    const cards = [];
    if (today) {
      cards.push(`<button class="stat in" data-go="moves"><span class="k">Entered trending</span><span class="v">+${today.in.length}</span><span class="s">${names(today.in) || "none today"}</span></button>`);
      cards.push(`<button class="stat out" data-go="moves"><span class="k">Left trending</span><span class="v">−${today.out.length}</span><span class="s">${names(today.out) || "none today"}</span></button>`);
    }
    if (riser) {
      cards.push(`<button class="stat" data-go="rate"><span class="k">Fastest growing</span><span class="v small">${esc(skillName(riser))}</span><span class="s">▲${pct(riser.rate)} in ${skillWin(riser.window)}</span></button>`);
    }
    $("pulse").innerHTML = cards.join("");
    $("pulse").hidden = !cards.length;
  }

  function renderSkillsChrome() {
    const counts = new Map();
    sdata.skills.forEach((s) => counts.set(s.src, (counts.get(s.src) || 0) + 1));
    const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12).map(([k]) => k);
    if (state.source !== "all" && !top.some((k) => k.toLowerCase() === state.source.toLowerCase())) top.unshift(state.source);
    const on = (v) => String(v.toLowerCase() === state.source.toLowerCase());
    $("type-chips").innerHTML = `<button class="chip" data-source="all" aria-pressed="${on("all")}">All sources<span class="n">${nf.format(sdata.skills.length)}</span></button>` +
      top.map((k) => `<button class="chip" data-source="${esc(k)}" aria-pressed="${on(k)}">${esc(k)}${counts.get(k) ? `<span class="n">${counts.get(k)}</span>` : ""}</button>`).join("");
    $("scope-chips").innerHTML = state.tab === "moves"
      ? [[1, "Today"], [7, "7 days"], [30, "30 days"]].map(([d, l]) => `<button class="chip" data-days="${d}" aria-pressed="${String(state.days === d)}">${l}</button>`).join("")
      : "";
    $("meta").innerHTML = [
      `<span class="live">Updated <b>${esc(kst(sdata.collected_at))} KST</b></span>`,
      `<span><b>${nf.format(sdata.totals.tracked)}</b> skills tracked</span>`,
      sdata.has_history ? `<span>Window <b>${skillWin(skillWindow())}</b></span>` : "",
      `<span>Data from <a href="https://skills.sh" target="_blank" rel="noopener"><b>skills.sh</b></a></span>`,
    ].join("");
    let msg = "";
    if (sdata.preview) msg = `Preview data: gains below come from two skills.sh collections taken ${skillWin(skillWindow())} apart. Daily collection runs around 00:00 KST.`;
    else if (!sdata.has_history) msg = "Collecting the first baseline — install gains appear after the next daily run (around 00:00 KST). Showing all-time installs meanwhile.";
    else if (skillWindow() < sdata.window_max) msg = `Tracking started ${fmtDate(sdata.tracking_start)}: gains are measured over the ${skillWindow()} day(s) collected so far until a full 7-day window exists.`;
    if (sdata.partial) msg = `${msg ? msg + " " : ""}Today's full skills.sh list was unavailable; numbers come from a partial snapshot.`;
    notice(msg);
    renderPulse();
  }

  /* ================================================================ shared */
  const kst = (iso) => new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Seoul", hour12: false });
  function notice(msg) { $("notice").hidden = !msg; $("notice").textContent = msg; }
  function setHead(name, total, metric) {
    $("head-name").textContent = name;
    $("head-total").textContent = total;
    $("head-metric").textContent = metric;
  }
  function finishList(n) {
    $("empty").hidden = n > 0;
    $("empty").textContent = "Nothing matches these filters.";
    $("more").hidden = n <= state.limit;
    $("more").textContent = `Show more (${nf.format(n - state.limit)} left)`;
  }
  function renderTabs() {
    const tabs = TABS[state.view];
    const hidden = (k) => (state.view === "repos" && !hasDeltas && k !== "alltime") ||
      (state.view === "skills" && !sdata.has_history && (k === "gain" || k === "rate"));
    if (hidden(state.tab)) state.tab = "alltime";
    $("tabs").innerHTML = Object.entries(tabs).filter(([k]) => !hidden(k))
      .map(([k, t]) => `<button role="tab" data-tab="${k}" aria-selected="${String(k === state.tab)}">${t.label}</button>`).join("");
  }

  function render() {
    if (!cur()) return;
    document.documentElement.dataset.view = state.view;
    document.querySelectorAll(".mode button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === state.view)));
    $("title").innerHTML = INTRO[state.view].title;
    $("lede").innerHTML = INTRO[state.view].lede;
    $("q").placeholder = INTRO[state.view].search;
    renderTabs();
    if (state.view === "skills") {
      renderSkillsChrome();
      renderSkills();
    } else {
      renderReposChrome();
      $("moves").hidden = true; $("list").hidden = false; $("head").hidden = false;
      renderRepos();
    }
    syncURL();
  }

  function syncURL() {
    const p = new URLSearchParams();
    if (state.view === "skills") {
      p.set("view", "skills");
      if (state.tab !== "gain") p.set("tab", state.tab);
      if (state.source !== "all") p.set("source", state.source);
      if (state.tab === "moves" && state.days !== 1) p.set("days", state.days);
    } else {
      if (state.tab !== "delta") p.set("tab", state.tab);
      if (state.type !== "all") p.set("type", state.type);
      if (state.scope !== "all") p.set("scope", state.scope);
    }
    if (state.q) p.set("q", state.q);
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  function loadSkills() {
    if (sdata) return Promise.resolve(sdata);
    skillsLoading ||= fetch("data/skills.json", { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((d) => {
        sdata = d;
        skillIndex = new Map(d.skills.map((s) => [s.k, s]));
        return d;
      })
      .catch((err) => { skillsLoading = null; throw err; });
    return skillsLoading;
  }

  function switchView(view, patch = {}) {
    state.view = view;
    state.tab = DEFAULT_TAB[view];
    state.q = "";
    state.limit = PAGE;
    Object.assign(state, patch);
    $("q").value = state.q;
    if (view === "skills" && !sdata) {
      $("meta").textContent = "Loading skills…";
      loadSkills().then(render).catch((err) => {
        state.view = "repos";
        state.tab = DEFAULT_TAB.repos;
        render();
        notice(`Could not load skills data (${err.message}).`);
      });
      return;
    }
    render();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  /* ---------- events ---------- */
  document.querySelector(".mode").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-view]");
    if (b && b.dataset.view !== state.view) switchView(b.dataset.view);
  });
  $("tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (!b) return;
    state.tab = b.dataset.tab; state.limit = PAGE; render();
  });
  $("pulse").addEventListener("click", (e) => {
    const b = e.target.closest("[data-go]");
    if (!b) return;
    state.tab = b.dataset.go; state.limit = PAGE; render();
    document.querySelector(".controls").scrollIntoView({ behavior: "smooth" });
  });
  document.addEventListener("click", (e) => {
    const g = e.target.closest("[data-goto-skills],[data-goto-repo]");
    if (g) {
      e.preventDefault();
      if (g.dataset.gotoSkills) switchView("skills", { source: g.dataset.gotoSkills });
      else switchView("repos", { q: g.dataset.gotoRepo });
      return;
    }
    const t = e.target.closest("[data-type],[data-scope],[data-source],[data-days]");
    if (!t || t.closest("#tabs")) return;
    if (t.dataset.type) state.type = t.dataset.type === state.type && t.classList.contains("tag") ? "all" : t.dataset.type;
    if (t.dataset.scope) state.scope = t.dataset.scope === state.scope && t.classList.contains("tag") ? "all" : t.dataset.scope;
    if (t.dataset.source) state.source = t.dataset.source;
    if (t.dataset.days) state.days = +t.dataset.days;
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

  /* ---------- boot ---------- */
  function renderFooter() {
    const cnt = (c) => `<span class="n">${nf.format(c)}</span>`;
    $("discovery").innerHTML = data.sources.discovery.map((d) =>
      `<li><a href="${esc(d.url)}" target="_blank" rel="noopener"${d.detail ? ` title="${esc(d.detail)}"` : ""}>${esc(d.label)}</a>${cnt(d.count)}</li>`).join("");
    $("curated-count").textContent = `(${data.sources.curated.length})`;
    $("sources").innerHTML = data.sources.curated.map((s) =>
      `<li><a href="https://github.com/${esc(s.repo)}" target="_blank" rel="noopener">${esc(s.repo)}</a>${cnt(s.count)}</li>`).join("");
  }

  fetch("data/trending.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => {
      data = d;
      if (Array.isArray(d.sources)) d.sources = { discovery: [], curated: d.sources.map((repo) => ({ repo, count: 0 })) };
      hasDeltas = d.repos.some((r) => r.delta);
      if (!hasDeltas && state.view === "repos") state.tab = "alltime";
      renderFooter();
      if (state.view === "skills") {
        return loadSkills().then(render).catch((err) => { switchView("repos"); notice(`Could not load skills data (${err.message}).`); });
      }
      render();
    })
    .catch((err) => {
      $("meta").textContent = `Could not load data (${err.message}).`;
    });
})();
