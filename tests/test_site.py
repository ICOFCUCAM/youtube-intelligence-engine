"""The landing page (public/index.html): self-contained, accurate links, honest claims."""
import os
import re
from html.parser import HTMLParser

from conftest import ROOT

PAGE = os.path.join(ROOT, "public", "index.html")
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


# --- Vercel deployment config ---------------------------------------------------------------------
def _vercel():
    import json
    return json.load(open(os.path.join(ROOT, "vercel.json")))


def test_vercel_serves_public_without_a_build():
    """The page lives in public/ - the folder Vercel serves for a static site even with no
    configuration - and there is no install or build step that could fail. Two earlier deploys
    failed on folder handling (STATIC_BUILD_NO_OUT_DIR, then "cp: cannot stat 'site'")."""
    cfg = _vercel()
    assert cfg["outputDirectory"] == "public" and cfg["framework"] is None
    assert "buildCommand" not in cfg and "installCommand" not in cfg
    assert os.path.isfile(os.path.join(ROOT, "public", "index.html"))


def test_csp_script_hash_matches_the_inline_script():
    """If the page's inline script changes, the CSP hash must change with it, or the live site's
    theme switch silently stops working."""
    import base64
    import hashlib
    scripts = re.findall(r"<script>(.*?)</script>", HTML, re.S)
    assert len(scripts) == 1
    want = "'sha256-" + base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode() + "'"
    hdrs = {h["key"]: h["value"] for h in _vercel()["headers"][0]["headers"]}
    csp = hdrs["Content-Security-Policy"]
    assert f"script-src {want}" in csp, "update vercel.json: the inline script changed"
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp and "unsafe-eval" not in csp
    assert hdrs["X-Content-Type-Options"] == "nosniff" and hdrs["X-Frame-Options"] == "DENY"
