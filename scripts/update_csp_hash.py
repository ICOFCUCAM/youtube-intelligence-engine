"""Recompute the CSP script hashes in vercel.json after editing an inline script in public/*.html.

    python scripts/update_csp_hash.py

tests/test_site.py fails until this has been run, so an edited script can never be silently
blocked on the live site. One hash per inline script; public/index.html's comes first.
"""
import base64
import glob
import hashlib
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def page_hashes():
    pages = sorted(glob.glob(os.path.join(ROOT, "public", "*.html")),
                   key=lambda p: (os.path.basename(p) != "index.html", p))
    out = []
    for page in pages:
        for script in re.findall(r"<script>(.*?)</script>", open(page, encoding="utf-8").read(), re.S):
            h = "'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'"
            if h not in out:
                out.append(h)
    return out


if __name__ == "__main__":
    hashes = " ".join(page_hashes())
    path = os.path.join(ROOT, "vercel.json")
    cfg = json.load(open(path))
    for h in cfg["headers"][0]["headers"]:
        if h["key"] == "Content-Security-Policy":
            h["value"] = re.sub(r"script-src [^;]*", f"script-src {hashes}", h["value"])
            if "connect-src" not in h["value"]:
                h["value"] = h["value"].replace("; img-src", "; connect-src 'self'; img-src")
            print(h["value"])
    open(path, "w").write(json.dumps(cfg, indent=2) + "\n")
