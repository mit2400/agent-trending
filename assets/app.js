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
    delta: { metric: "Gain" },
    rate: { metric: "Growth" },
    new: { metric: "Gain" },
    alltime: { metric: "Gain" },
  };

  const $ = (id) => document.getElementById(id);
  const nf = new Intl.NumberFormat("en-US");
  const cf = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const params = new URLSearchParams(location.search);
  const state = {
    tab: TABS[params.get("tab")] ? params.get("tab") : "delta",
    type: params.get("type") || "all",
    scope: params.get("scope") || "all",
    q: params.get("q") || "",
    limit: PAGE,
  };
  let data = null;
  let hasDeltas = false;

  /* ---------- theme ---------- */
  $("theme").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  });

  /* ---------- formatting ---------- */
  const curWindow = () => Math.round((Date.parse(data.date) - Date.parse(data.baseline_date)) / 864e5);
  function windowLabel(days) {
    if (!data) return "";
    if (data.preview) {
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
  function metricHTML(r) {
    const win = r.window && r.window !== curWindow() && !data.preview ? windowLabel(r.window) : "";
    if (state.tab === "rate") {
      return `<span class="arrow up" aria-hidden="true">▲</span>${pct(r.rate)}<span class="sub">+${nf.format(r.delta)}${win ? ` · ${win}` : ""}</span>`;
    }
    return `${deltaHTML(r.delta)}${win ? `<span class="sub">${win}</span>` : ""}`;
  }
  const avatar = (name, size) =>
    `<img class="avatar" src="https://github.com/${esc(name.split("/")[0])}.png?size=${size * 2}" alt="" width="${size}" height="${size}" loading="lazy" decoding="async">`;
  const nameHTML = (name) => {
    const [o, n] = name.split("/");
    return `<span class="owner">${esc(o)}/</span>${esc(n)}`;
  };

  /* ---------- sparkline ---------- */
  function spark(values, w, h, cls = "") {
    const pad = 3;
    if (!values || values.length < 2) {
      return `<svg class="spark ${cls}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><line class="flat" x1="${pad}" y1="${h / 2}" x2="${w - pad}" y2="${h / 2}"/></svg>`;
    }
    const min = Math.min(...values), max = Math.max(...values);
    const span = max - min || 1;
    const step = (w - pad * 2) / (values.length - 1);
    const pts = values.map((v, i) => [pad + i * step, max === min ? h / 2 : h - pad - ((v - min) / span) * (h - pad * 2)]);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
    const area = `${line}L${pts.at(-1)[0].toFixed(1)},${h}L${pts[0][0].toFixed(1)},${h}Z`;
    const [ex, ey] = pts.at(-1);
    return `<svg class="spark ${cls}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" data-v="${values.join(",")}" role="img" aria-label="Stars from ${nf.format(values[0])} to ${nf.format(values.at(-1))}">
      <path class="area" d="${area}"/><path class="line" d="${line}" vector-effect="non-scaling-stroke"/>
      <circle class="end" cx="${ex.toFixed(1)}" cy="${ey.toFixed(1)}" r="3"/></svg>`;
  }

  // hover: nearest point -> date + stars
  const tip = $("tip");
  document.addEventListener("pointermove", (ev) => {
    const svg = ev.target.closest && ev.target.closest("svg.spark[data-v]");
    if (!svg) { tip.hidden = true; return; }
    const vals = svg.dataset.v.split(",").map(Number);
    const box = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(vals.length - 1, Math.round(((ev.clientX - box.left) / box.width) * (vals.length - 1))));
    const dates = data.window_dates.slice(-vals.length);
    const prev = i ? vals[i] - vals[i - 1] : null;
    tip.innerHTML = `<b>${nf.format(vals[i])}</b> ★ ${prev == null ? "" : `(${prev >= 0 ? "+" : "−"}${nf.format(Math.abs(prev))})`}<br>${esc(fmtDate(dates[i]))}`;
    tip.style.left = `${box.left + (i / (vals.length - 1)) * box.width}px`;
    tip.style.top = `${box.top}px`;
    tip.hidden = false;
  });
  document.addEventListener("scroll", () => { tip.hidden = true; }, { passive: true });
  const fmtDate = (d) => new Date(`${d}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });

  /* ---------- filtering ---------- */
  function filtered() {
    const q = state.q.trim().toLowerCase();
    let rs = data.repos.filter((r) =>
      (state.type === "all" || r.type.includes(state.type)) &&
      (state.scope === "all" || r.scope.includes(state.scope)) &&
      (!q || r.name.toLowerCase().includes(q) || (r.desc || "").toLowerCase().includes(q)));
    const byDelta = (a, b) => (b.delta ?? -Infinity) - (a.delta ?? -Infinity) || b.stars - a.stars;
    if (!hasDeltas || state.tab === "alltime") return rs.sort((a, b) => b.stars - a.stars);
    if (state.tab === "rate") return rs.filter((r) => r.rate > 0 && r.base >= data.rate_min_base).sort((a, b) => b.rate - a.rate || byDelta(a, b));
    if (state.tab === "new") return rs.filter((r) => r.new).sort(byDelta);
    return rs.filter((r) => r.delta != null).sort(byDelta);
  }

  /* ---------- render ---------- */
  function tagsHTML(r) {
    const t = r.type.map((x) => `<button class="tag" data-type="${esc(x)}">${esc(TYPE_LABEL[x] || x)}</button>`);
    const s = r.scope.filter((x) => x !== "general").map((x) => `<button class="tag scope" data-scope="${esc(x)}">${esc(SCOPE_LABEL[x] || x)}</button>`);
    return (r.new ? `<span class="tag new">new</span>` : "") + t.join("") + s.join("");
  }

  function podiumBig(r) {
    if (state.tab === "alltime") return `★ ${cf.format(r.stars)}<small>${r.delta ? `${deltaHTML(r.delta)} · ${windowLabel(r.window)}` : "stars"}</small>`;
    if (state.tab === "rate") return `${pct(r.rate)}<small>growth · ${windowLabel(r.window)}</small>`;
    return `${deltaHTML(r.delta)}<small>stars · ${windowLabel(r.window)}</small>`;
  }

  function renderPodium(top) {
    $("podium").innerHTML = top.map((r, i) => `
      <a class="card" href="https://github.com/${esc(r.name)}" target="_blank" rel="noopener">
        <span class="rank-badge">#${i + 1}</span>
        <div class="card-head">${avatar(r.name, 28)}<span class="name">${nameHTML(r.name)}</span></div>
        <div class="big">${podiumBig(r)}</div>
        <p class="desc">${esc(r.desc)}</p>
        ${spark(r.spark, 280, 44)}
      </a>`).join("");
  }

  function render() {
    const rs = filtered();
    const podium = (hasDeltas || state.tab === "alltime") && !state.q && rs.length >= 3 ? rs.slice(0, 3) : [];
    renderPodium(podium);
    const rest = rs.slice(podium.length);
    const shown = rest.slice(0, state.limit);
    const offset = podium.length;

    $("head-metric").textContent = hasDeltas ? `${TABS[state.tab].metric} (${windowLabel(curWindow())})` : "Gain";
    $("list").innerHTML = shown.map((r, i) => `
      <li class="row">
        <span class="rank">${offset + i + 1}</span>
        <div class="repo">
          ${avatar(r.name, 32)}
          <div class="repo-body">
            <a class="name" href="https://github.com/${esc(r.name)}" target="_blank" rel="noopener">${nameHTML(r.name)}</a>
            ${r.desc ? `<p class="desc" title="${esc(r.desc)}">${esc(r.desc)}</p>` : ""}
            <div class="tags">${tagsHTML(r)}</div>
          </div>
        </div>
        <span class="num stars">★ ${cf.format(r.stars)}</span>
        <span class="num metric">${metricHTML(r)}</span>
        <span class="trend">${spark(r.spark, 120, 32)}</span>
      </li>`).join("");
    $("empty").hidden = rs.length > 0;
    $("more").hidden = rest.length <= state.limit;
    $("more").textContent = `Show more (${nf.format(rest.length - state.limit)} left)`;

    document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
    document.querySelectorAll("#type-chips .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.type === state.type)));
    document.querySelectorAll("#scope-chips .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.scope === state.scope)));
    syncURL();
  }

  function syncURL() {
    const p = new URLSearchParams();
    if (state.tab !== "delta") p.set("tab", state.tab);
    if (state.type !== "all") p.set("type", state.type);
    if (state.scope !== "all") p.set("scope", state.scope);
    if (state.q) p.set("q", state.q);
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  function renderChrome() {
    const chip = (attr, val, label, n) =>
      `<button class="chip" data-${attr}="${esc(val)}" aria-pressed="false">${esc(label)}${n != null ? `<span class="n">${nf.format(n)}</span>` : ""}</button>`;
    $("type-chips").innerHTML = chip("type", "all", "All types", data.count) +
      Object.entries(data.counts.type).map(([k, n]) => chip("type", k, TYPE_LABEL[k] || k, n)).join("");
    $("scope-chips").innerHTML = chip("scope", "all", "All ecosystems") +
      Object.keys(data.counts.scope).map((k) => chip("scope", k, SCOPE_LABEL[k] || k)).join("");

    const updated = new Date(data.latest_collected_at);
    const when = updated.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Seoul", hour12: false });
    $("meta").innerHTML = [
      `<span class="live">Updated <b>${esc(when)} KST</b></span>`,
      `<span><b>${nf.format(data.count)}</b> repos tracked</span>`,
      `<span>Window <b>${esc(windowLabel(curWindow()))}</b></span>`,
      `<span><b>${data.sources.curated.length}</b> curated lists + GitHub Trending</span>`,
    ].join("");

    const n = $("notice");
    if (data.preview) {
      n.hidden = false;
      n.textContent = `Preview data: rankings below come from two test snapshots taken ${windowLabel(1)} apart. Daily collection starts at 08:30 KST.`;
    } else if (!hasDeltas) {
      n.hidden = false;
      n.textContent = "Collecting the first baseline — growth rankings appear after the next daily run (08:30 KST). Showing all-time stars meanwhile.";
    } else if (curWindow() < data.window_max) {
      n.hidden = false;
      n.textContent = `Tracking started ${fmtDate(data.tracking_start)}: growth is measured over the ${curWindow()} day(s) collected so far until a full 7-day window exists.`;
    }

    const cnt = (c) => `<span class="n">${nf.format(c)}</span>`;
    $("discovery").innerHTML = data.sources.discovery.map((d) =>
      `<li><a href="${esc(d.url)}" target="_blank" rel="noopener"${d.detail ? ` title="${esc(d.detail)}"` : ""}>${esc(d.label)}</a>${cnt(d.count)}</li>`).join("");
    $("curated-count").textContent = `(${data.sources.curated.length})`;
    $("sources").innerHTML = data.sources.curated.map((s) =>
      `<li><a href="https://github.com/${esc(s.repo)}" target="_blank" rel="noopener">${esc(s.repo)}</a>${cnt(s.count)}</li>`).join("");
  }

  /* ---------- events ---------- */
  $("tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (!b) return;
    state.tab = b.dataset.tab; state.limit = PAGE; render();
  });
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-type],[data-scope]");
    if (!t || t.closest("#tabs")) return;
    if (t.dataset.type) state.type = t.dataset.type === state.type && t.classList.contains("tag") ? "all" : t.dataset.type;
    if (t.dataset.scope) state.scope = t.dataset.scope === state.scope && t.classList.contains("tag") ? "all" : t.dataset.scope;
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
  fetch("data/trending.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((d) => {
      data = d;
      hasDeltas = d.repos.some((r) => r.delta);
      if (!hasDeltas) {
        state.tab = "alltime";
        document.querySelectorAll("#tabs button:not([data-tab=alltime])").forEach((b) => { b.hidden = true; });
      }
      renderChrome();
      render();
    })
    .catch((err) => {
      $("meta").textContent = `Could not load data (${err.message}).`;
    });
})();
