import os
import subprocess
import sys

from conftest import ROOT


def test_library_example_runs():
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    p = subprocess.run([sys.executable, os.path.join(ROOT, "examples", "library_usage.py")],
                       capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
    assert p.returncode == 0, p.stderr
    assert "24 cues, 90.0s -> 75.5s after 10 cuts" in p.stdout
    assert "youtube-intelligence/edl@1" in p.stdout


def test_module_dispatch():
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    run = lambda *a: subprocess.run([sys.executable, "-m", "youtube_intelligence", *a],
                                    capture_output=True, text=True, env=env, cwd=ROOT)
    assert run().returncode == 1
    assert run("nope").returncode == 1
    assert run("title", "--title", "Short title").returncode == 0
