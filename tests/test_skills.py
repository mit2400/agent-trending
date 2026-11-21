from __future__ import annotations

import json

import httpx
import pytest

from tf import skills as sk

A = "o/skills|alpha"
B = "o/skills|beta"
C = "x.dev|gamma/sub"     # non-GitHub source, skillId with a slash


# ---------------------------------------------------------------- fetch
def api(pages: dict[tuple[str, int], list], total: dict[str, int], fail: dict | None = None):
    """Fake skills.sh: pages[(view, n)] = rows; fail[(view, n)] = list of status codes to return first."""
    fail = {k: list(v) for k, v in (fail or {}).items()}
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        _, _, _, view, page = req.url.path.split("/")
        k = (view, int(page))
        calls.append(k)
        if fail.get(k):
            code = fail[k].pop(0)
            return httpx.Response(code, headers={"retry-after": "7"} if code == 429 else {})
        rows = pages.get(k, [])
        more = (view, int(page) + 1) in pages
        return httpx.Response(200, json={"skills": rows, "total": total[view], "hasMore": more, "page": int(page)})

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def row(src, sid, n, **kw):
    return {"source": src, "skillId": sid, "name": kw.pop("name", sid), "installs": n, **kw}


def test_fetch_pages_dedupes_and_retries_429():
    pages = {("all-time", 0): [row("o/skills", "alpha", 50), row("o/skills", "beta", 40)],
             ("all-time", 1): [row("o/skills", "beta", 40), row("x.dev", "gamma/sub", 30)]}
    client, calls = api(pages, {"all-time": 3}, fail={("all-time", 1): [429, 503]})
    waits = []
    rows, total = sk.fetch_view(client, "all-time", delay=2, sleep=waits.append)
    assert [sk.key(r["source"], r["skillId"]) for r in rows] == [A, B, C]
    assert total == 3
    assert waits == [2, 7, sk.BACKOFF[1]]  # page gap, Retry-After header, then backoff
    assert calls == [("all-time", 0), ("all-time", 1), ("all-time", 1), ("all-time", 1)]


def test_fetch_fails_on_low_coverage():
    client, _ = api({("trending", 0): [row("o/skills", "alpha", 5)]}, {"trending": 100})
    with pytest.raises(RuntimeError, match="1 of 100"):
        sk.fetch_view(client, "trending", sleep=lambda s: None)


def test_fetch_gives_up_after_retries():
    client, _ = api({("trending", 0): []}, {"trending": 1}, fail={("trending", 0): [429] * 10})
    with pytest.raises(httpx.HTTPStatusError):
        sk.fetch_view(client, "trending", sleep=lambda s: None)


def test_collect_writes_one_skill_per_line_and_skips_existing(tmp_path):
    raw = tmp_path / "raw"
    pages = {("all-time", 0): [row("o/skills", "alpha", 50, isOfficial=True), row("o/skills", "beta", 40, name="Beta!")],
             ("trending", 0): [row("o/skills", "beta", 9), row("o/skills", "alpha", 3)]}
    client, calls = api(pages, {"all-time": 2, "trending": 2})
    sk.collect("2026-11-22", raw, client=client, sleep=lambda s: None)
    a_path = sk.raw_path(raw, "all-time", "2026-11-22")
    a = sk.read_raw(a_path)
    t = sk.read_raw(sk.raw_path(raw, "trending", "2026-11-22"))
    assert a["installs"] == {A: 50, B: 40} and a["official"] == [A] and a["names"] == {B: "Beta!"}
    assert t["order"] == [[B, 9], [A, 3]]
    assert a_path.read_text().splitlines()[1:3] == [f'"{A}":50,', f'"{B}":40']  # one skill per line
    sk.collect("2026-11-22", raw, client=client, sleep=lambda s: None)
    assert len(calls) == 2  # second run reuses today's files


# ---------------------------------------------------------------- build
@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "snapshots").mkdir(parents=True)
    (data / "registry.json").write_text(json.dumps({"repos": {"R_1": {"name": "O/Skills", "tags": {}}}}))
    (data / "snapshots" / "2026-11-22.json").write_text(json.dumps({"stars": {"R_1": 1234}}))
    monkeypatch.setattr(sk, "DATA", data)
    monkeypatch.setattr(sk, "SNAPSHOTS", data / "snapshots")
    monkeypatch.setattr(sk, "OUT", data / "skills.json")
    monkeypatch.setattr(sk, "TREND_CUT", 2)
    raw = data / "skills-raw"

    def day(date, installs, trending, root=raw):
        sk.write_raw(sk.raw_path(root, "all-time", date),
                     {"date": date, "collected_at": f"{date}T15:00:00Z", "installs": installs, "official": [A]}, "installs")
        sk.write_raw(sk.raw_path(root, "trending", date),
                     {"date": date, "collected_at": f"{date}T15:01:00Z", "order": trending}, "order")
    return raw, day


def by_key(t):
    return {r["k"]: r for r in t["skills"]}


def test_first_day_has_no_history(env):
    raw, day = env
    day("2026-11-20", {A: 100, B: 50}, [[B, 9], [A, 5], [C, 1]])
    t = sk.build(raw=raw, write=False)
    rs = by_key(t)
    assert t["has_history"] is False and t["moves"] == []
    assert rs[A]["delta"] is None and rs[A]["ar"] == 1 and rs[B]["tr"] == 1
    assert C not in rs  # rank 3 is outside the trending cut of 2


def test_deltas_ranks_moves_and_streaks(env):
    raw, day = env
    day("2026-11-20", {A: 100, B: 50}, [[B, 9], [A, 5], [C, 1]])
    day("2026-11-21", {A: 110, B: 80}, [[B, 9], [A, 5], [C, 2]])
    day("2026-11-22", {A: 115, B: 140}, [[C, 30], [B, 20], [A, 4]])
    t = sk.build(raw=raw, write=False)
    rs = by_key(t)
    assert (rs[A]["delta"], rs[A]["d1"], rs[A]["window"], rs[A]["spark"]) == (15, 5, 2, [100, 110, 115])
    assert (rs[B]["delta"], rs[B]["rate"]) == (90, 1.8)
    assert (rs[B]["ar"], rs[B]["par"], rs[A]["ar"], rs[A]["par"]) == (1, 2, 2, 1)
    # C: trending-only (not on the all-time board), entered the cut today
    assert rs[C]["tr"] == 1 and "ptr" not in rs[C] and rs[C]["installs"] is None and rs[C]["t24"] == 30
    assert rs[B]["streak"] == 3 and rs[C]["streak"] == 1
    assert (rs[A].get("tr"), rs[A]["ptr"]) == (None, 2)  # left trending today
    today = t["moves"][0]
    assert today["date"] == "2026-11-22" and today["from"] == "2026-11-21"
    assert today["in"] == [{"k": C, "r": 1, "t": 30}]
    assert today["out"] == [{"k": A, "r": 2, "t": 5, "d": 2}]
    assert t["moves"][1]["in"] == [] and t["moves"][1]["out"] == []
    assert rs[A]["official"] is True and rs[A]["repo"] == "O/Skills" and rs[A]["stars"] == 1234
    assert C in rs and not rs[C]["gh"] and rs[A]["gh"]
    assert t["by_repo"] == {"O/Skills": {"n": 2, "installs": 255}}
    assert t["totals"]["tracked"] == 3 and t["totals"]["window_installs"] == 105


def test_streak_breaks_on_missing_day(env):
    raw, day = env
    day("2026-11-19", {A: 1}, [[A, 5]])
    day("2026-11-21", {A: 2}, [[A, 5]])
    day("2026-11-22", {A: 3}, [[A, 5]])
    assert by_key(sk.build(raw=raw, write=False))[A]["streak"] == 2


def test_build_reads_only_the_last_30_days(env, monkeypatch):
    raw, day = env
    day("2026-10-01", {A: 1}, [[A, 5]])          # older than 30 days: kept on disk, never read
    day("2026-11-21", {A: 100}, [[B, 5]])
    day("2026-11-22", {A: 110}, [[A, 5]])
    read = []
    orig = sk.read_raw
    monkeypatch.setattr(sk, "read_raw", lambda p: read.append(p.stem) or orig(p))
    t = sk.build(raw=raw, write=False)
    assert "2026-10-01" not in read and sk.raw_path(raw, "all-time", "2026-10-01").exists()
    assert t["tracking_start"] == "2026-10-01" and len(t["moves"]) == 1


# ---------------------------------------------------------------- gate
@pytest.fixture
def gated(env, monkeypatch):
    from tf import gate as g
    raw, day = env
    porcelain = {"out": ""}
    monkeypatch.setattr(g, "git", lambda *a: porcelain["out"] if a[0] == "status" else "")
    many = {f"o/s|k{i}": 1000 for i in range(200)}
    day("2026-11-21", many, [["o/s|k1", 5]])
    return raw, day, many, porcelain


def test_gate_passes_healthy_run(gated):
    raw, day, many, _ = gated
    day("2026-11-22", {k: n + 10 for k, n in many.items()}, [["o/s|k1", 5]])
    sk.build(raw=raw)
    assert sk.check("2026-11-22", raw) == ([], [])


def test_gate_fails_on_shrunk_list_and_outside_changes(gated):
    raw, day, many, porcelain = gated
    day("2026-11-22", dict(list(many.items())[:150]), [["o/s|k1", 5]])
    sk.build(raw=raw)
    porcelain["out"] = "?? data/skills-raw/all-time/2026-11-22.json\n M tf/skills.py\n"
    errors, _ = sk.check("2026-11-22", raw)
    assert any("count fell 200 -> 150" in e for e in errors)
    assert any("outside data/" in e for e in errors)


def test_gate_fails_without_todays_list_or_on_preview(gated):
    raw, day, many, _ = gated
    errors, _ = sk.check("2026-11-22", raw)
    assert any("all-time list for 2026-11-22" in e for e in errors)
    day("2026-11-22", many, [["o/s|k1", 5]])
    sk.build(raw=raw, preview=True)
    errors, _ = sk.check("2026-11-22", raw)
    assert any("preview" in e for e in errors)


def test_preview_until_two_production_days(env, tmp_path):
    raw, day = env
    prev_dir = tmp_path / "preview"
    day("2026-11-20", {A: 100}, [[A, 5]], root=prev_dir)
    day("2026-11-21", {A: 130}, [[A, 5]], root=prev_dir)
    assert sk.use_preview(raw, None) is False
    day("2026-11-22", {A: 140}, [[A, 5]])
    assert sk.use_preview(raw, prev_dir) is True      # production has 1 day
    t = sk.build(raw=prev_dir, write=False, preview=True)
    assert t["preview"] and t["baseline_collected_at"] == "2026-11-20T15:00:00Z" and by_key(t)[A]["delta"] == 30
    day("2026-11-23", {A: 150}, [[A, 5]])
    assert sk.use_preview(raw, prev_dir) is False     # production takes over


def test_tracked_repo_skills_ship_as_extras(env, monkeypatch):
    raw, day = env
    monkeypatch.setattr(sk, "TOP", 1)
    D = "o/skills|delta"                          # from the tracked repo O/Skills, off every board
    day("2026-11-21", {A: 100, B: 50, D: 5, "z/z|q": 1}, [[B, 9]])
    day("2026-11-22", {A: 120, B: 51, D: 5, "z/z|q": 1}, [[B, 9]])
    rs = by_key(sk.build(raw=raw, write=False))
    assert D in rs and rs[D]["x"] == 1               # listed for the repo's "N skills" link
    assert "x" not in rs[A] and "x" not in rs[B]      # on a board
    assert "z/z|q" not in rs                          # untracked source, off every board


def test_each_tab_has_its_own_rank_over_all_skills(env, monkeypatch):
    raw, day = env
    D = "o/skills|delta"
    day("2026-11-21", {A: 100_000, B: 2_000, D: 1_000}, [[B, 9]])
    day("2026-11-22", {A: 100_500, B: 3_000, D: 1_400}, [[B, 9]])
    rs = by_key(sk.build(raw=raw, write=False))
    assert [rs[k]["gr"] for k in (B, A, D)] == [1, 2, 3]        # by installs gained
    assert [rs[k]["rr"] for k in (B, D, A)] == [1, 2, 3]        # by % growth
    assert [rs[k]["ar"] for k in (A, B, D)] == [1, 2, 3]        # by total installs
