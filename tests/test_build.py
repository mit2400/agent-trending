import json

import pytest

from tf import build as b


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    snaps = data / "snapshots"
    snaps.mkdir(parents=True)
    reg = {
        "repos": {
            "R_old": {"name": "a/old", "created": "2020-01-01", "added": "2026-11-01",
                      "tags": {"type": ["mcp"], "scope": ["general"]}},
            "R_late": {"name": "a/late", "created": "2020-01-01", "added": "2026-11-09",
                       "tags": {"type": ["skill"], "scope": []}},
            "R_fresh": {"name": "a/fresh", "created": "2026-11-05", "added": "2026-11-01",
                        "tags": {"type": [], "scope": []}},
        }
    }
    (data / "registry.json").write_text(json.dumps(reg))
    (data / "sources.json").write_text(json.dumps({"sources": [{"repo": "x/awesome"}]}))
    monkeypatch.setattr(b, "DATA", data)

    def snap(date, stars):
        (snaps / f"{date}.json").write_text(json.dumps(
            {"date": date, "collected_at": f"{date}T00:00:00Z", "stars": stars}))
    return snaps, snap


def by_name(t):
    return {r["name"]: r for r in t["repos"]}


def test_single_snapshot_has_no_delta(env):
    snaps, snap = env
    snap("2026-11-01", {"R_old": 100})
    r = by_name(b.build(snaps))["a/old"]
    assert r["delta"] is None and r["window"] == 0


def test_short_history_uses_oldest_snapshot(env):
    snaps, snap = env
    snap("2026-11-01", {"R_old": 100})
    snap("2026-11-03", {"R_old": 130})
    r = by_name(b.build(snaps))["a/old"]
    assert (r["delta"], r["window"], r["rate"]) == (30, 2, 0.3)


def test_full_window_uses_date_minus_7(env):
    snaps, snap = env
    for i, n in enumerate([100, 110, 120, 130, 140, 150, 160, 170, 180, 190]):
        snap(f"2026-11-{i + 1:02d}", {"R_old": n})
    t = b.build(snaps)
    r = by_name(t)["a/old"]
    assert t["baseline_date"] == "2026-11-03"
    assert (r["delta"], r["window"], len(r["spark"])) == (70, 7, 8)


def test_late_joiner_gets_own_window_and_new_flag(env):
    snaps, snap = env
    snap("2026-11-01", {"R_old": 100})
    snap("2026-11-09", {"R_old": 120, "R_late": 50})
    snap("2026-11-10", {"R_old": 125, "R_late": 80})
    rs = by_name(b.build(snaps))
    assert (rs["a/late"]["delta"], rs["a/late"]["window"], rs["a/late"]["new"]) == (30, 1, True)
    assert rs["a/old"]["new"] is False


def test_sorted_by_delta(env):
    snaps, snap = env
    snap("2026-11-01", {"R_old": 100, "R_late": 10})
    snap("2026-11-02", {"R_old": 101, "R_late": 60})
    assert [r["name"] for r in b.build(snaps)["repos"]] == ["a/late", "a/old"]
