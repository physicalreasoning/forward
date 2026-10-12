"""Sealing: the hashes a round is frozen with, and the check every sealed score runs first.

A frozen round records the sha256 of its spec, of every file its scoring runs, and of its fitted
parameters (`scripts/freeze.py`). `check_frozen` refuses to score if any of them changed, so a
result can only come from the code and parameters that were public before the outcomes were.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

from . import ROOT


def sha256_file(path, root: pathlib.Path = ROOT) -> str:
    return hashlib.sha256((pathlib.Path(root) / path).read_bytes()).hexdigest()


def params_hash(params: dict) -> str:
    """Hash of parameters as stored: JSON with sorted keys."""
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()


def check_frozen(n: int, root: pathlib.Path = ROOT) -> dict:
    """Load frozen/round<n>.json; raise SystemExit naming anything changed since the freeze."""
    fz = json.loads((pathlib.Path(root) / "frozen" / f"round{n}.json").read_text())
    files = {fz["spec"]: fz["spec_sha256"], **fz["code_sha256"]}
    changed = [p for p, h in files.items() if sha256_file(p, root) != h]
    if params_hash(fz["params"]) != fz["params_sha256"]:
        changed.append("params")
    if changed:
        raise SystemExit(f"changed since the freeze: {changed}")
    return fz
