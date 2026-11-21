from __future__ import annotations

from tf import discover as d

TRENDING = """
<article class="Box-row">
  <h2 class="h3 lh-condensed">
    <a data-view-component="true" class="Link" href="/owner/repo">owner / repo</a>
  </h2>
</article>
<article class="Box-row">
  <h2 class="h3 lh-condensed">
    <a href="/Other-Org/my.repo_2">x</a>
  </h2>
</article>
<article class="Box-row">
  <h2 class="h3 lh-condensed">
    <a href="/owner/repo">dup</a>
  </h2>
</article>
<a href="/owner/not-a-heading">ignored</a>
"""

DEVS = """
<article>
  <div class="f6">Popular repo</div>
  <h1 class="h4 lh-condensed"><a class="css-truncate" href="/dev1/tool">tool</a></h1>
</article>
<article>
  <div class="f6">Popular repo</div>
  <h1 class="h4 lh-condensed"><a href="/dev2/other">other</a></h1>
</article>
<article>
  <div class="f6">Popular repo</div>
  <h1 class="h4 lh-condensed"><a href="/dev1/tool">dup</a></h1>
</article>
<h1 class="h4 lh-condensed"><a href="/nobody/skipped">no label</a></h1>
"""


def test_parse_trending_dedupes_in_order():
    assert d.parse_trending(TRENDING) == ["owner/repo", "Other-Org/my.repo_2"]


def test_parse_trending_devs_dedupes_in_order():
    assert d.parse_trending_devs(DEVS) == ["dev1/tool", "dev2/other"]


def test_parsers_return_empty_on_changed_markup():
    assert d.parse_trending("<div>new markup</div>") == []
    assert d.parse_trending_devs("<div>new markup</div>") == []
