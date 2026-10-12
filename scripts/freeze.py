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
import json

from forward import ROOT, entries
from forward.history import fit_table
from forward.seal import params_hash, sha256_file

STATION_CODE = [
    "forward/entries.py",
    "forward/metrics.py",
    "forward/openmeteo.py",
    "forward/market.py",
    "forward/truth.py",
    "forward/history.py",
    "forward/stations.py",
    "forward/ledger.py",
    "forward/seal.py",
    "scripts/score.py",
]
PRICE_CODE = [
    "forward/prices.py",
    "forward/tsfm.py",
    "forward/price_ladders.py",
    "scripts/score_prices.py",
]
ROUNDS = {
    1: {
        "cutoff": "2026-10-30",
        "window": ["2026-11-01", "2026-12-26"],
        "spec": "ROUND1.md",
        "code": STATION_CODE,
    },
    2: {
        "cutoff": "2027-01-02",
        "window": ["2027-01-04", "2027-02-28"],
        "spec": "ROUND2.md",
        "code": STATION_CODE + PRICE_CODE,
    },
}
CODE = STATION_CODE  # kept for scripts/rehearse.py


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
        **{k: v for k, v in r.items() if k != "code"},
        "spec_sha256": sha256_file(r["spec"]),
        "code_sha256": {p: sha256_file(p) for p in r["code"]},
        "params_sha256": params_hash(params),
        "params": json.loads(blob),
    }
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rec, indent=1))
    print(out, "params", rec["params_sha256"][:12], "spec", rec["spec_sha256"][:12])


if __name__ == "__main__":
    main()
