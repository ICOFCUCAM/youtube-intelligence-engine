"""Waitlist: the server function (Node tests), and that page, function, SQL and notice agree."""
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

API = open(os.path.join(ROOT, "api", "waitlist.js"), encoding="utf-8").read()
SQL = open(os.path.join(ROOT, "supabase", "waitlist.sql"), encoding="utf-8").read()
PAGE = open(os.path.join(ROOT, "public", "index.html"), encoding="utf-8").read()
PRIVACY = open(os.path.join(ROOT, "public", "privacy.html"), encoding="utf-8").read()


def _js_set(name):
    m = re.search(rf"const {name} = new Set\(\[(.*?)\]\)", API)
    return set(re.findall(r'"([a-z0-9_]+)"', m.group(1)))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_function_tests_pass():
    p = subprocess.run(["node", "--test", os.path.join(ROOT, "tests", "waitlist.test.js")],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr


def test_form_offers_and_sizes_match_server_and_database():
    offers = set(re.findall(r'name="offer" value="([a-z_]+)"', PAGE))
    sizes = set(re.findall(r'<option value="([a-z0-9_]+)"', PAGE))
    assert offers == _js_set("OFFERS")
    assert sizes == _js_set("SIZES")
    platforms = set(re.findall(r'name="other_platforms" value="([a-z_]+)"', PAGE))
    assert platforms == _js_set("PLATFORMS")
    for v in offers | sizes | platforms:
        assert f"'{v}'" in SQL, v


def test_consent_version_matches_privacy_notice():
    v = re.search(r'const CONSENT_VERSION = "([^"]+)"', API).group(1)
    assert f"Version {v}" in PRIVACY


def test_database_is_insert_only_for_the_website():
    assert "enable row level security" in SQL
    assert "revoke all on public.yie_waitlist_signups from anon, authenticated" in SQL
    assert re.search(r"grant insert \(email, offer, channel_size, other_platforms, consent_version\) on public\.yie_waitlist_signups to anon;", SQL)
    assert not re.search(r"grant (select|update|delete|all)", SQL, re.I)


def test_privacy_page_is_self_contained_and_linked():
    assert "<script" not in PRIVACY and not re.search(r'src="http', PRIVACY)
    assert 'href="/privacy"' in PAGE
    for word in ("What we collect", "How long we keep it", "Your rights", "withdraw"):
        assert word in PRIVACY


def test_waitlist_is_closed_until_placeholders_are_filled():
    """While the notice still has placeholders it must say the waitlist is not open, and the
    function must default to closed (it needs WAITLIST_ENABLED=1)."""
    if "to be confirmed]" in PRIVACY:
        assert 'id="not-open"' in PRIVACY
    assert 'env.WAITLIST_ENABLED !== "1"' in API


def test_page_never_submits_natively():
    # JS sends JSON with fetch; CSP form-action 'none' stops a native submit if JS fails.
    import json
    cfg = json.load(open(os.path.join(ROOT, "vercel.json")))
    csp = {h["key"]: h["value"] for h in cfg["headers"][0]["headers"]}["Content-Security-Policy"]
    assert "form-action 'none'" in csp and "connect-src 'self'" in csp
    assert 'fetch("/api/waitlist"' in PAGE
