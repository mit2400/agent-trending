from tf.probe import marketplace_size
from tf.publish import week_label


def test_week_label_covers_previous_seven_days():
    # Monday Nov 30 run -> window Nov 23..29 (ISO week 48)
    assert week_label("2026-11-30") == ("2026-W48", "Nov 23", "Nov 29")


def test_marketplace_size():
    assert marketplace_size('{"plugins": [{}, {}, {}]}') == 3
    assert marketplace_size('{"plugins": {}}') == 0
    assert marketplace_size("not json") == 0
    assert marketplace_size(None) == 0


def test_feed_and_digest_use_period_boards(tmp_path, monkeypatch):
    import json
    from tf import build as b, publish as pub
    data, snaps = tmp_path / "data", tmp_path / "data" / "snapshots"
    snaps.mkdir(parents=True)
    (data / "registry.json").write_text(json.dumps({"repos": {
        "R_a": {"name": "o/a", "created": "2020-01-01", "added": "2026-11-01", "tags": {"type": ["mcp"]}},
        "R_b": {"name": "o/b", "created": "2020-01-01", "added": "2026-11-01", "tags": {"type": []}}}}))
    (data / "sources.json").write_text(json.dumps({"min_stars": 5000, "sources": [], "discovery": {"topics": {"t": {}}}}))
    for i in range(9):
        d = (__import__("datetime").date(2026, 11, 22) + __import__("datetime").timedelta(days=i)).isoformat()
        (snaps / f"{d}.json").write_text(json.dumps({"date": d, "collected_at": f"{d}T15:00:00Z",
                                                     "stars": {"R_a": 1000 + 10 * i, "R_b": 500 + 50 * i}}))
    for m in (b, pub):
        monkeypatch.setattr(m, "DATA", data)
    monkeypatch.setattr(pub, "SNAPSHOTS", snaps)
    pub.feed(tmp_path / "feed.xml")
    xml = (tmp_path / "feed.xml").read_text()
    assert "2026-11-30: o/b leads with +350 stars (7d)" in xml       # 7-day period once available
    assert "2026-11-23: o/b leads with +50 stars (1d)" in xml        # Today before that
    out = pub.digest("2026-11-30")
    text = out.read_text()
    assert "| 1 | [o/b](https://github.com/o/b) | +350 |" in text and "**MCP servers** — [o/a]" in text
