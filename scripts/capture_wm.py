#!/usr/bin/env python3
"""Capture every ensemble member's 8-day trajectory at the 19 stations, at the read (20:00 UTC).

The world-model track's inputs (forward/wm/ensembles.py). Open-Meteo archives no past ensemble
runs, so this is the only record. A day is about 1 MB, too large to commit daily, so it is
written as two files:

- `wm-YYYY-MM-DD.parquet`: the trajectories, uploaded as an asset of the `wm-ledger` release;
- `wm/YYYY-MM-DD.json`: the manifest (capture time, each model's run times, the parquet's
  sha256), committed to the public `ledger-wm` branch. The commit time proves the inputs
  predate the outcomes, and the hash ties the asset to it.

    uv run scripts/capture_wm.py [--out DIR]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib

import pandas as pd

from forward import DATA
from forward.stations import STATIONS
from forward.wm import ensembles

# Open-Meteo serves whole UTC days from 00:00 on the read's day, so seven days end at lead 147
# after the 20:00 UTC read; eight reach WM-1's 168 h (docs/WM1_DRYRUN.md).
DAYS = 8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=DATA / "ledger-wm")
    a = ap.parse_args()
    now = dt.datetime.now(dt.UTC)
    man = {"captured_at": now.isoformat(timespec="seconds"), "models": {}, "errors": {}}
    parts = []
    for name, (mid, domain) in ensembles.MODELS.items():
        try:
            run = ensembles.meta(domain)  # before the data: the run read can only be this one or newer
            d = ensembles.fetch(STATIONS, name, days=DAYS)
            parts.append(d)
            man["models"][name] = {"open_meteo": mid, **run, "members": int(d.member.nunique())}
        except Exception as ex:  # noqa: BLE001 (one model failing must not lose the rest)
            man["errors"][name] = str(ex)[:200]
    d = pd.concat(parts, ignore_index=True).sort_values(["station", "model", "member", "valid"])
    (a.out / "wm").mkdir(parents=True, exist_ok=True)
    pq = a.out / f"wm-{now.date()}.parquet"
    d.to_parquet(pq, index=False, compression="zstd", compression_level=19)
    man.update(
        file=pq.name,
        sha256=hashlib.sha256(pq.read_bytes()).hexdigest(),
        rows=len(d),
        stations=sorted(d.station.unique()),
    )
    (a.out / "wm" / f"{now.date()}.json").write_text(json.dumps(man, indent=1))
    print(pq, len(d), "rows", len(man["models"]), "models", "errors:", list(man["errors"]))


if __name__ == "__main__":
    main()
