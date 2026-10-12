"""Inputs captured live at each read (scripts/capture.py), as the sealed rounds read them.

A capture counts only if it was taken before 22:00 UTC on D-1: two hours after the read, and
at least six hours before D starts at any of the stations (Eastern midnight is 04:00 or 05:00
UTC). A row that fails, or a station-day with no capture, is dropped for every entry.

A file holds the model runs under "rows". A live ladder entry (an outside model's ladder
probabilities, e.g. isotherm) adds its own block under its name, with its own "rows"; `load`
ignores those blocks and `load_ladder` reads one. Files without the block load as before.
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


def load_ladder(ledger_dir: pathlib.Path, name: str, start: str, end: str, accept=None) -> tuple[dict, dict]:
    """A live ladder entry's stored answers: {(station, day): row}, plus a log.

    Rows come from each file's `name` block. A row counts only if its block passes `accept` (the
    entry's own check, e.g. the served model is the one entered) and it was fetched before
    22:00 UTC on D-1 (its own `fetched_at`, else the file's `captured_at`). If a station-day has
    two, the earlier fetch counts.
    """
    out, log = {}, {"files": 0, "late": 0, "errors": 0, "rejected": 0}
    for f in sorted(pathlib.Path(ledger_dir).glob("*.json")):
        rec = json.loads(f.read_text())
        block = rec.get(name)
        if block is None:
            continue
        log["files"] += 1
        if accept is not None and not accept(block):
            log["rejected"] += len(block.get("rows", []))
            continue
        for r in block.get("rows", []):
            if "error" in r:
                log["errors"] += 1
                continue
            day = pd.Timestamp(r["day"])
            if not (pd.Timestamp(start) <= day <= pd.Timestamp(end)):
                continue
            fetched = pd.Timestamp(r.get("fetched_at", rec["captured_at"]))
            fetched = fetched.tz_convert("UTC").tz_localize(None)
            if fetched >= day - pd.Timedelta(days=1) + pd.Timedelta(hours=LATEST_HOUR_UTC):
                log["late"] += 1
                continue
            key = (r["station"], day)
            if key not in out or fetched < out[key][0]:
                out[key] = (fetched, r)
    return {k: r for k, (_, r) in out.items()}, log
