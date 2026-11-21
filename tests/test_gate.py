from __future__ import annotations

import json

import pytest

from tf import gate as g

DATE = "2026-11-21"
IDS = [f"R_kgDO{i:04d}" for i in range(100)]


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    snaps = data / "snapshots"
    repos = {i: {"name": f"o/r{n}", "tags": {"type": [], "scope": []}} for n, i in enumerate(IDS)}
    write(data / "registry.json", {"repos": repos})
    write(snaps / "2026-11-20.json", {"date": "2026-11-20", "stars": {i: 100 for i in IDS}})
    write(snaps / f"{DATE}.json", {"date": DATE, "stars": {i: 110 for i in IDS}})
    write(data / "trending.json", {"date": DATE, "count": len(IDS), "preview": False})
    porcelain = {"out": ""}

    def fake_git(*args):
        return porcelain["out"] if args[0] == "status" else ""

    monkeypatch.setattr(g, "DATA", data)
    monkeypatch.setattr(g, "SNAPSHOTS", snaps)
    monkeypatch.setattr(g, "git", fake_git)
    return data, snaps, porcelain


def test_healthy_run_passes(env):
    errors, warns = g.check(DATE)
    assert errors == [] and warns == []


def test_low_coverage_fails(env):
    data, snaps, _ = env
    write(snaps / f"{DATE}.json", {"date": DATE, "stars": {i: 110 for i in IDS[:90]}})
    errors, _ = g.check(DATE)
    assert any("coverage" in e for e in errors)


def test_mass_star_crash_fails(env):
    _, snaps, _ = env
    stars = {i: 110 for i in IDS}
    stars[IDS[0]] = stars[IDS[1]] = 10  # 2% of repos lost >50%
    write(snaps / f"{DATE}.json", {"date": DATE, "stars": stars})
    errors, _ = g.check(DATE)
    assert any("lost >50%" in e for e in errors)


def test_single_crash_only_warns(env):
    _, snaps, _ = env
    stars = {i: 110 for i in IDS}
    stars[IDS[0]] = 10
    write(snaps / f"{DATE}.json", {"date": DATE, "stars": stars})
    errors, warns = g.check(DATE)
    assert errors == [] and len(warns) == 1


def test_change_outside_data_fails(env):
    *_, porcelain = env
    porcelain["out"] = " M data/registry.json\n M tf/build.py\n"
    errors, _ = g.check(DATE)
    assert any("outside data/" in e for e in errors)


def test_changes_inside_data_pass(env):
    *_, porcelain = env
    porcelain["out"] = " M data/registry.json\n?? data/activity.json\n"
    assert g.check(DATE)[0] == []


def test_trending_wrong_date_fails(env):
    data, *_ = env
    write(data / "trending.json", {"date": "2026-11-20", "count": len(IDS), "preview": False})
    errors, _ = g.check(DATE)
    assert any("not built for today" in e for e in errors)


def test_trending_preview_fails(env):
    data, *_ = env
    write(data / "trending.json", {"date": DATE, "count": len(IDS), "preview": True})
    errors, _ = g.check(DATE)
    assert any("preview" in e for e in errors)
