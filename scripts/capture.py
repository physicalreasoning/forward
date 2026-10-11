#!/usr/bin/env python3
"""Capture every model's live forecast at the read (20:00 UTC, the day before the target day).

Open-Meteo's live API serves only the latest run, so the inputs a sealed round scores must be
written down when they exist. One JSON file per read goes to ledger/YYYY-MM-DD.json (the read's
UTC date); the runner commits it to the public `ledger` branch, whose commit time is the proof
that the inputs predate the outcome.

    uv run scripts/capture.py [--out DIR]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

from forward import ROOT, openmeteo
from forward.stations import STATIONS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "ledger")
    a = ap.parse_args()
    now = dt.datetime.now(dt.UTC)
    rec = {"captured_at": now.isoformat(timespec="seconds"), "models": openmeteo.MODELS, "rows": []}
    for k, st in STATIONS.items():
        try:
            rec["rows"].append({"station": k, **openmeteo.live(st)})
        except Exception as ex:  # noqa: BLE001 (one station failing must not lose the rest)
            rec["rows"].append({"station": k, "error": str(ex)[:200]})
    a.out.mkdir(parents=True, exist_ok=True)
    f = a.out / f"{now.date()}.json"
    f.write_text(json.dumps(rec, indent=1))
    print(f, sum("error" not in r for r in rec["rows"]), "stations")


if __name__ == "__main__":
    main()
