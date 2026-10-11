#!/usr/bin/env python3
"""Freeze a round: fit every entry on data settled by the cutoff and record the hashes.

    uv run scripts/build_history.py && uv run scripts/freeze.py --round 1

Writes frozen/round<N>.json: the fitted parameters, their sha256, and the sha256 of the round's
spec and of every file that scoring runs. `score.py --round N` refuses to run if any hash differs.
Run once, before the round's first read, and commit the result.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json

from forward import ROOT, entries
from forward.history import fit_table

ROUNDS = {1: {"cutoff": "2026-10-30", "window": ["2026-11-01", "2026-12-26"], "spec": "ROUND1.md"}}
CODE = [
    "forward/entries.py",
    "forward/metrics.py",
    "forward/openmeteo.py",
    "forward/market.py",
    "forward/truth.py",
    "forward/history.py",
    "forward/stations.py",
    "scripts/score.py",
]


def sha(path) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    n = ap.parse_args().round
    r = ROUNDS[n]
    out = ROOT / "frozen" / f"round{n}.json"
    if out.exists():
        raise SystemExit(f"{out} exists: a round is frozen once")
    params = entries.fit(fit_table(r["cutoff"]))
    blob = json.dumps(params, sort_keys=True)
    rec = {
        "round": n,
        "frozen_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        **r,
        "spec_sha256": sha(r["spec"]),
        "code_sha256": {p: sha(p) for p in CODE},
        "params_sha256": hashlib.sha256(blob.encode()).hexdigest(),
        "params": json.loads(blob),
    }
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rec, indent=1))
    print(out, "params", rec["params_sha256"][:12], "spec", rec["spec_sha256"][:12])


if __name__ == "__main__":
    main()
