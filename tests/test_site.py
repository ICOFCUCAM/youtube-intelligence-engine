"""The landing page (site/index.html): self-contained, accurate links, honest claims."""
import os
import re
from html.parser import HTMLParser

from conftest import ROOT

PAGE = os.path.join(ROOT, "site", "index.html")
HTML = open(PAGE, encoding="utf-8").read()


class Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.hrefs, self.srcs, self.links = set(), [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a" and "href" in a:
            self.hrefs.append(a["href"])
        if "src" in a:
            self.srcs.append(a["src"])
        if tag == "link":
            self.links.append(a.get("href", ""))


P = Collect()
P.feed(HTML)


def test_no_external_resources_or_trackers():
    assert P.srcs == []                                          # no external scripts or images
    assert all(h.startswith("data:") for h in P.links)           # only the inline favicon
    assert not re.search(r"googletagmanager|google-analytics|facebook\.net|<iframe", HTML)


def test_internal_anchors_resolve():
    for h in P.hrefs:
        if h.startswith("#"):
            assert h[1:] in P.ids, h


def test_external_links_point_where_they_should():
    ext = [h for h in P.hrefs if h.startswith("http")]
    assert all(h.startswith(("https://github.com/ICOFCUCAM/youtube-intelligence-engine",
                             "https://github.com/Jakeschincariol/youtube-agent-skill")) for h in ext)
    for doc in re.findall(r"blob/main/([\w./-]+)", HTML):
        assert os.path.exists(os.path.join(ROOT, doc)), doc


def test_attribution_and_disclaimer():
    assert "Jake Schincariol" in HTML and "youtube-agent-skill" in HTML
    assert "Not affiliated with, endorsed by or sponsored by YouTube or Google" in HTML


def test_examples_are_real_tool_output():
    from youtube_intelligence.packaging.title import check
    r = check("The ULTIMATE guide to growing on YouTube", "ULTIMATE GUIDE")
    assert f"score {r['score']}/100" in HTML and r["score"] == 80
    from youtube_intelligence.core.transcript import load_cues
    from youtube_intelligence.editing.deadair import analyse
    d = analyse(load_cues(os.path.join(ROOT, "tests", "fixtures", "sample.srt")))
    assert f"{len(d['cuts'])} cuts, {d['removed']:.2f}s removed, {d['out']:.2f}s out" in HTML


def test_install_commands_match_the_project():
    import json
    mk = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")))
    assert f"/plugin install {mk['plugins'][0]['name']}" in HTML
    py = open(os.path.join(ROOT, "pyproject.toml")).read()
    assert 'requires-python = ">=3.10"' in py and "Python 3.10 or newer" in HTML


def test_no_unsupported_claims():
    low = HTML.lower()
    for phrase in ("guarantee", "go viral", "10x", "trusted by", "thousands of creators", "testimonial", "#1 "):
        assert phrase not in low, phrase
