"""Recompute the CSP script hash in vercel.json after editing the inline script in public/index.html.

    python scripts/update_csp_hash.py

tests/test_site.py fails until this has been run, so an edited script can never be silently
blocked on the live site.
"""
import base64
import hashlib
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
html = open(os.path.join(ROOT, "public", "index.html"), encoding="utf-8").read()
scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
assert len(scripts) == 1, "expected exactly one inline script"
digest = "'sha256-" + base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode() + "'"
path = os.path.join(ROOT, "vercel.json")
cfg = json.load(open(path))
for h in cfg["headers"][0]["headers"]:
    if h["key"] == "Content-Security-Policy":
        h["value"] = re.sub(r"script-src '[^']*'", f"script-src {digest}", h["value"])
        if "connect-src" not in h["value"]:
            h["value"] = h["value"].replace("; img-src", "; connect-src 'self'; img-src")
        print(h["value"])
open(path, "w").write(json.dumps(cfg, indent=2) + "\n")
