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
    (data / "sources.json").write_text(json.dumps({
        "min_stars": 5000, "sources": [{"repo": "x/awesome"}],
        "discovery": {"topics": {"ai-agents": {}}}}))
    monkeypatch.setattr(b, "DATA", data)

    def snap(date, stars):
        (snaps / f"{date}.json").write_text(json.dumps(
            {"date": date, "collected_at": f"{date}T00:00:00Z", "stars": stars}))
    return snaps, snap


def by_name(t):
    return {r["name"]: r for r in t["repos"]}


def test_single_snapshot_has_no_periods(env):
    snaps, snap = env
    snap("2026-11-01", {"R_old": 100})
    t = b.build(snaps)
    r = by_name(t)["a/old"]
    assert t["periods"] == [] and r["p"] == {} and r["ar"] == 1


def test_periods_open_as_history_grows(env):
    snaps, snap = env
    snap("2026-11-01", {"R_old": 100})
    snap("2026-11-03", {"R_old": 130})
    t = b.build(snaps)
    r = by_name(t)["a/old"]
    assert t["periods"] == [1]                      # 2 days of history: Today only, no 7d yet
    assert r["p"] == {}                             # no snapshot yesterday: nothing to compare for Today
    snap("2026-11-04", {"R_old": 135})
    r = by_name(b.build(snaps))["a/old"]
    assert r["p"]["1"] == {"d": 5, "b": 130, "w": 1, "r": 0.03846, "g": 1, "q": 1}


def test_seven_day_period_uses_date_minus_7(env):
    snaps, snap = env
    for i, n in enumerate([100, 110, 120, 130, 140, 150, 160, 170, 180, 190]):
        snap(f"2026-11-{i + 1:02d}", {"R_old": n})
    t = b.build(snaps)
    r = by_name(t)["a/old"]
    assert t["periods"] == [1, 7]
    assert (r["p"]["7"]["d"], r["p"]["7"]["w"], r["p"]["1"]["d"]) == (70, 7, 10)
    assert len(r["spark"]) == 8 and t["spark_dates"][0] == "2026-11-03"


def test_late_joiner_gets_own_span_and_new_rank(env):
    snaps, snap = env
    snap("2026-11-01", {"R_old": 100})
    snap("2026-11-09", {"R_old": 120, "R_late": 50})
    snap("2026-11-10", {"R_old": 125, "R_late": 80})
    rs = by_name(b.build(snaps))
    assert (rs["a/late"]["p"]["7"]["d"], rs["a/late"]["p"]["7"]["w"], rs["a/late"]["new"]) == (30, 1, True)
    assert rs["a/late"]["p"]["7"]["n"] == 1 and "n" not in rs["a/old"]["p"]["7"]
    assert rs["a/old"]["new"] is False


def test_ranks_per_board(env):
    snaps, snap = env
    snap("2026-11-01", {"R_old": 1000, "R_late": 10})
    snap("2026-11-02", {"R_old": 1100, "R_late": 60})
    t = b.build(snaps)
    rs = by_name(t)
    assert (rs["a/old"]["p"]["1"]["g"], rs["a/late"]["p"]["1"]["g"]) == (1, 2)   # by gain
    assert "q" not in rs["a/late"]["p"]["1"]                                    # base 10 < 100 stars
    assert (rs["a/old"]["ar"], rs["a/late"]["ar"], rs["a/late"]["par"]) == (1, 2, 2)
    assert [r["name"] for r in t["repos"]] == ["a/old", "a/late"]               # all-time order


def test_pushed_flows_from_activity(env):
    snaps, snap = env
    snap("2026-11-01", {"R_old": 100, "R_late": 50})
    assert by_name(b.build(snaps, write=False))["a/old"]["pushed"] is None
    (b.DATA / "activity.json").write_text(json.dumps({"updated": "x", "pushed": {"R_old": "2026-10-30"}}))
    t = by_name(b.build(snaps, write=False))
    assert t["a/old"]["pushed"] == "2026-10-30" and t["a/late"]["pushed"] is None


def test_gh_trending_count_only_when_on_trending_that_day(env):
    snaps, snap = env
    snap("2026-11-01", {"R_old": 100, "R_late": 50})
    snap("2026-11-03", {"R_old": 110, "R_late": 60})
    (b.DATA / "gh-trending.json").write_text(json.dumps({"repos": {
        "R_old": ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04"], "R_late": ["2026-11-02"]}}))
    t = b.build(snaps, write=False)
    rs = by_name(t)
    assert rs["a/old"]["ght"] == 3          # 4th day is after the snapshot date
    assert "ght" not in rs["a/late"]        # not on trending on 2026-11-03
    assert t["gh_trending_since"] == "2026-10-30"
