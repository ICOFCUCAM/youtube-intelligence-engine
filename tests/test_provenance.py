"""Provenance and repository hygiene: upstream text preserved, attribution intact, no secrets."""
import hashlib
import json
import os
import re
import subprocess

import pytest

from conftest import ROOT

MANIFEST = json.load(open(os.path.join(ROOT, "docs", "upstream-manifest.json")))
MARK = MANIFEST["skill_marker"]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(rel):
    with open(os.path.join(ROOT, rel), "rb") as fh:
        return fh.read()


def test_manifest_covers_all_24_upstream_files():
    assert MANIFEST["upstream_commit"] == "a2feb2104981a375ffd4f87ee04f4f5344ac43c6"
    assert len(MANIFEST["files"]) == 24
    skills = [f for f in MANIFEST["files"] if f["upstream_path"].endswith("SKILL.md")]
    assert len(skills) == 11


@pytest.mark.parametrize("entry", [f for f in MANIFEST["files"] if f["status"] == "imported-verbatim"],
                         ids=lambda e: e["upstream_path"])
def test_verbatim_imports_are_byte_identical(entry):
    for dest in entry["destinations"]:
        assert sha(read(dest)) == entry["upstream_sha256"], dest


@pytest.mark.parametrize("entry", [f for f in MANIFEST["files"] if f["status"] == "adapted-append-only"],
                         ids=lambda e: e["upstream_path"])
def test_skill_instructions_preserved_above_marker(entry):
    text = read(entry["upstream_path"]).decode("utf-8")
    assert text.count(MARK) == 1
    original = text.split("\n" + MARK, 1)[0]
    assert sha(original.encode("utf-8")) == entry["upstream_sha256"]
    assert "**ship it, or change it?**" in original


def test_licence_and_attribution():
    lic = read("LICENSE").decode()
    assert "Copyright (c) 2026 Jake Schincariol" in lic and "MIT License" in lic
    assert "THE SOFTWARE IS PROVIDED \"AS IS\"" in lic
    up = read("UPSTREAM.md").decode()
    assert "Jake Schincariol" in up and MANIFEST["upstream_commit"] in up
    assert "https://github.com/Jakeschincariol/youtube-agent-skill" in read("README.md").decode()


def test_every_adapted_python_file_credits_upstream():
    for e in MANIFEST["files"]:
        if e["upstream_path"].endswith(".py"):
            for dest in e["destinations"]:
                assert "Jake Schincariol" in read(dest).decode(), dest


def _tracked():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [f for f in out.splitlines() if f]


def test_no_env_or_credential_files_tracked():
    bad = re.compile(r"(^|/)(\.env(\..*)?|.*\.pem|.*\.key|client_secret.*\.json|token.*\.json|credentials.*\.json)$")
    assert [f for f in _tracked() if bad.search(f) and not f.endswith(".env.example")] == []


SECRET = re.compile(r"(AIza[0-9A-Za-z_\-]{35}|ya29\.[0-9A-Za-z_\-]{20,}|GOCSPX-[0-9A-Za-z_\-]{20,}|"
                    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[0-9A-Za-z]{36}|sk-[A-Za-z0-9]{32,})")


def test_no_secret_shaped_strings_tracked():
    hits = []
    for f in _tracked():
        try:
            if SECRET.search(read(f).decode("utf-8", "ignore")):
                hits.append(f)
        except (IsADirectoryError, FileNotFoundError):
            pass
    assert hits == []
