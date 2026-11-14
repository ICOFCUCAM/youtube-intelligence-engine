"""Evaluation dataset format and loader.

A dataset is one JSON file; transcript paths are relative to it::

    {
      "name": "synthetic-v1",
      "synthetic": true,                       # REQUIRED: say whether this is real footage
      "label_source": "how the labels were made",
      "cases": [
        {
          "id": "clean-tutorial",
          "transcript": "clean-tutorial.srt",
          "labels": {                          # every task is optional per case
            "cuts":     [{"start": 6.9, "end": 7.4, "kind": "FILLER"}],
            "keep":     [{"start": 40.0, "end": 41.2, "why": "pause for emphasis"}],
            "chapters": [31.4, 60.1],          # section starts; 0:00 is implied
            "shorts":   [{"start": 0.0, "end": 28.6}]
          }
        }
      ]
    }

``kind`` is one of DEAD, FILLER, REPEAT, OTHER. Labels are untrusted input like any other file:
they are validated, never executed.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List

from ..core.errors import InputError

KINDS = {"DEAD", "FILLER", "REPEAT", "OTHER"}


def _spans(items, where: str, need_kind: bool = False) -> List[Dict]:
    if not isinstance(items, list):
        raise InputError(f"{where} must be a list")
    out = []
    for n, it in enumerate(items):
        if not isinstance(it, dict):
            raise InputError(f"{where}[{n}] must be an object")
        try:
            s, e = float(it["start"]), float(it["end"])
        except KeyError as exc:
            raise InputError(f"{where}[{n}] has no {exc.args[0]!r}") from None
        except (TypeError, ValueError):
            raise InputError(f"{where}[{n}] has a non-numeric start/end") from None
        if e <= s:
            raise InputError(f"{where}[{n}] ends before it starts")
        row = dict(it, start=s, end=e)
        if need_kind:
            k = str(it.get("kind", "OTHER")).upper()
            if k not in KINDS:
                raise InputError(f"{where}[{n}] has unknown kind {k!r}")
            row["kind"] = k
        out.append(row)
    return out


def load(path: str) -> Dict:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except FileNotFoundError:
        raise InputError(f"file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise InputError(f"{path} is not valid JSON ({exc.msg} at line {exc.lineno})") from None
    if not isinstance(d, dict) or not isinstance(d.get("cases"), list) or not d["cases"]:
        raise InputError(f"{path}: expected an object with a non-empty 'cases' list")
    if not isinstance(d.get("synthetic"), bool):
        raise InputError(f"{path}: 'synthetic' must be true or false - say whether the data is real")
    base = os.path.dirname(os.path.abspath(path))
    seen = set()
    for n, c in enumerate(d["cases"]):
        where = f"cases[{n}]"
        if not isinstance(c, dict) or "id" not in c or "transcript" not in c:
            raise InputError(f"{where} needs 'id' and 'transcript'")
        if c["id"] in seen:
            raise InputError(f"{where}: duplicate id {c['id']!r}")
        seen.add(c["id"])
        rel = str(c["transcript"])
        full = os.path.normpath(os.path.join(base, rel))
        if os.path.isabs(rel) or not full.startswith(base + os.sep):
            raise InputError(f"{where}: transcript must be a relative path inside the dataset folder")
        c["transcript_path"] = full
        lab = c.get("labels") or {}
        if not isinstance(lab, dict):
            raise InputError(f"{where}.labels must be an object")
        if "cuts" in lab:
            lab["cuts"] = _spans(lab["cuts"], f"{where}.labels.cuts", need_kind=True)
        if "keep" in lab:
            lab["keep"] = _spans(lab["keep"], f"{where}.labels.keep")
        if "shorts" in lab:
            lab["shorts"] = _spans(lab["shorts"], f"{where}.labels.shorts")
        if "chapters" in lab:
            try:
                lab["chapters"] = [float(t) for t in lab["chapters"]]
            except (TypeError, ValueError):
                raise InputError(f"{where}.labels.chapters must be a list of seconds") from None
        c["labels"] = lab
    return d
