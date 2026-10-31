#!/usr/bin/env python3
"""WM-2 prototype capture: MRMS rain-rate tiles around chosen stations, every 10 minutes.

Reads NOAA MRMS PrecipRate from the public bucket (no credentials), decodes it, averages it to
0.02 deg and keeps a 256 x 256 box around each station (forward/wm2/mrms.py); writes one
compressed file and a manifest per UTC day under data/wm2/tiles (forward/wm2/store.py).
A prototype, run by hand: no schedule, no ledger.

    uv run scripts/capture_wm2.py --start 2026-10-14T00:00 --end 2026-10-15T00:00 \
        [--stations NY,CHI,MIA,OKC,SEA,LAX] [--every 10] [--out data/wm2/tiles]
"""

from __future__ import annotations

import argparse
import pathlib
import time

import pandas as pd

from forward import DATA
from forward.stations import STATIONS
from forward.wm2 import mrms
from forward.wm2.store import Store

DEFAULT_STATIONS = "NY,CHI,MIA,OKC,SEA,LAX"


def store_for(stations: list[str], out: pathlib.Path) -> Store:
    return Store(out, mrms.tiles({k: STATIONS[k] for k in stations}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True, help="inclusive")
    ap.add_argument("--every", type=int, default=10, help="minutes")
    ap.add_argument("--stations", default=DEFAULT_STATIONS)
    ap.add_argument("--out", type=pathlib.Path, default=DATA / "wm2" / "tiles")
    a = ap.parse_args()
    st = store_for(a.stations.split(","), a.out)
    times = pd.date_range(a.start, a.end, freq=f"{a.every}min")
    t = time.time()
    s = st.capture(times)
    print(
        f"{s['fetched']} frames fetched of {s['requested']} requested, {len(s['missing'])} missing, "
        f"{s['bytes'] / 1e6:.1f} MB downloaded in {time.time() - t:.0f} s"
    )


if __name__ == "__main__":
    main()
