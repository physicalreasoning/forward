"""Inputs captured live at each read (scripts/capture.py), as the sealed rounds read them.

A capture counts only if it was taken before 22:00 UTC on D-1: two hours after the read, and
at least six hours before D starts at any of the stations (Eastern midnight is 04:00 or 05:00
UTC). A row that fails, or a station-day with no capture, is dropped for every entry.
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

from .openmeteo import MODELS

LATEST_HOUR_UTC = 22


def load(ledger_dir: pathlib.Path, start: str, end: str) -> tuple[pd.DataFrame, dict]:
    rows, log = [], {"files": 0, "late": 0, "errors": 0}
    for f in sorted(pathlib.Path(ledger_dir).glob("*.json")):
        rec = json.loads(f.read_text())
        log["files"] += 1
        captured = pd.Timestamp(rec["captured_at"]).tz_convert("UTC").tz_localize(None)
        for r in rec["rows"]:
            if "error" in r:
                log["errors"] += 1
                continue
            day = pd.Timestamp(r["day"])
            if not (pd.Timestamp(start) <= day <= pd.Timestamp(end)):
                continue
            if captured >= day - pd.Timedelta(days=1) + pd.Timedelta(hours=LATEST_HOUR_UTC):
                log["late"] += 1
                continue
            rows.append({"station": r["station"], "day": day, **{m: r.get(m) for m in MODELS}})
    df = pd.DataFrame(rows, columns=["station", "day", *MODELS])
    # Two captures for one station-day (a manual rerun): keep the earlier, it is the stricter.
    return df.drop_duplicates(["station", "day"], keep="first").astype({m: float for m in MODELS}), log
