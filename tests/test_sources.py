from __future__ import annotations

import re

from tf import sources as s

CFG = {"skip_sections": ["sponsor", "license"]}
MD = """
# Awesome Agents

## MCP Servers
- [a](https://github.com/alice/server-a) great
- https://github.com/bob/tool.git
- [c](https://github.com/carol/repo/tree/main/docs)
- [self](https://github.com/me/awesome)

## Sponsors
- [s](https://github.com/sponsor/repo)

### Sub of sponsors
- [s2](https://github.com/sponsor/repo2)

## Skills
- [t](https://github.com/topics/mcp) and [u](https://github.com/orgs/foo) and [m](https://github.com/marketplace/x)
- [d](https://github.com/dave/skillz.) [dup](https://github.com/alice/server-a)

```
https://github.com/in/code
```
"""


def parse(src=None):
    return s.parse_readme(MD, "me/awesome", CFG, src or {})


def test_links_extracted_with_section():
    found = parse()
    assert found["alice/server-a"] == "mcp servers"
    assert found["carol/repo"] == "mcp servers"  # trailing paths dropped
    assert found["bob/tool"] == "mcp servers"    # .git stripped


def test_skip_sections_and_nested_headings_ignored():
    found = parse()
    assert not any(k.startswith("sponsor/") for k in found)


def test_reserved_owners_self_and_code_blocks_ignored():
    found = parse()
    assert not any(k.split("/")[0] in {"topics", "orgs", "marketplace", "in"} for k in found)
    assert "me/awesome" not in found


def test_trailing_dot_stripped_and_first_section_wins():
    found = parse()
    assert found["dave/skillz"] == "skills"
    assert found["alice/server-a"] == "mcp servers"


def test_per_source_skip_sections():
    found = parse({"skip_sections": ["^skills$"]})
    assert "dave/skillz" not in found and "alice/server-a" in found


def test_section_type_rules():
    rules = [(re.compile(r["match"], re.I), r["type"]) for r in
             [{"match": r"\bmcp\b", "type": "mcp"}, {"match": r"\bskills?\b", "type": "skill"}]]
    assert s.section_type("mcp servers", rules) == "mcp"
    assert s.section_type("skills", rules) == "skill"
    assert s.section_type("misc", rules) is None
    assert s.clean_heading("## [MCP](x) Servers 🚀") == "mcp servers"


def test_long_missing_needs_seven_straight_days(tmp_path):
    import json
    def snap(day, missing):
        (tmp_path / f"2026-11-{day:02d}.json").write_text(json.dumps({"missing": missing}))
    for day in range(1, 8):
        snap(day, ["R_gone", "R_flaky"] if day != 4 else ["R_gone"])
    assert s.long_missing(tmp_path) == {"R_gone"}          # R_flaky came back on day 4
    assert s.long_missing(tmp_path, days=8) == set()        # fewer than 8 snapshots: drop nothing
