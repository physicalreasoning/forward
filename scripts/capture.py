#!/usr/bin/env python3
"""Capture every model's live forecast at the read (20:00 UTC, the day before the target day).

Open-Meteo's live API serves only the latest run, so the inputs a sealed round scores must be
written down when they exist. One JSON file per read goes to ledger/YYYY-MM-DD.json (the read's
UTC date); the runner commits it to the public `ledger` branch, whose commit time is the proof
that the inputs predate the outcome.

Live ladder entries (`forward/registry.py`; isotherm) are asked next, for each station's next
day, and stored under their own key in the same file. The model runs are written first, so a
slow or failing outside service can never cost them.

    uv run scripts/capture.py [--out DIR]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

import pandas as pd

from forward import ROOT, openmeteo, registry
from forward.stations import STATIONS


def tomorrow(st) -> str:
    """The target day at the read: the station's next local calendar day (as openmeteo.live)."""
    return str((pd.Timestamp.now(tz=st.tz).normalize() + pd.Timedelta(days=1)).date())


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
    days = {k: tomorrow(st) for k, st in STATIONS.items()}
    for e in registry.entries("station-highs", "ladder", "live"):
        try:
            rec[e.name] = e.load().capture(days)
        except Exception as ex:  # noqa: BLE001
            rec[e.name] = {"error": str(ex)[:200], "rows": []}
        f.write_text(json.dumps(rec, indent=1))
        print(e.name, sum("response" in r for r in rec[e.name].get("rows", [])), "ladders")


if __name__ == "__main__":
    main()
