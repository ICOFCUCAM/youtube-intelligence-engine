import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
GOLDEN = os.path.join(FIX, "upstream_golden")


def fixture(name):
    return os.path.join(FIX, name)


def golden(name):
    with open(os.path.join(GOLDEN, name)) as fh:
        return json.load(fh)


def run_cli(module, *args, cwd=ROOT):
    """Run ``python -m module args`` and return the CompletedProcess."""
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    return subprocess.run([sys.executable, "-m", module, *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=60)


def run_skill(script, *args, cwd=ROOT):
    """Run a skill-folder entry point exactly as upstream documented: plain python3, isolated."""
    return subprocess.run([sys.executable, "-I", os.path.join(ROOT, "skills", script), *args],
                          cwd=cwd, capture_output=True, text=True, timeout=60)


@pytest.fixture
def write(tmp_path):
    def _write(name, content):
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return str(p)
    return _write
