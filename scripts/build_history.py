#!/usr/bin/env python3
"""Fitting data for the station-high task: CLI truth since 2010, model archives since 2024.

Only data that settled before a round's freeze may be used to fit its entries; `freeze.py`
enforces the cutoff, this script just gathers everything.

    uv run scripts/build_history.py
"""

from __future__ import annotations

import pandas as pd

from forward import DATA, openmeteo, truth
from forward.stations import STATIONS

END = str((pd.Timestamp.now() - pd.Timedelta(days=1)).date())


def main():
    t = truth.all_highs(STATIONS, range(2010, pd.Timestamp.now().year + 1))
    print("truth", len(t), "station-days", flush=True)
    parts = []
    for k, st in STATIONS.items():
        for y in (2024, 2025, 2026):
            a, b = f"{y}-01-01", min(f"{y}-12-31", END)
            parts.append(openmeteo.archive(st, a, b).assign(station=k))
        print(k, flush=True)
    fc = pd.concat(parts, ignore_index=True)
    fc.to_parquet(DATA / "forecasts.parquet", index=False)
    print(fc.drop(columns=["day", "station"]).notna().mean().round(3).to_dict())


if __name__ == "__main__":
    main()
