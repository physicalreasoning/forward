#!/usr/bin/env python3
"""Rehearse a sealed round on the Round 0 window: a ledger rebuilt from the archive, a throwaway
freeze (round 99), then the real sealed scorer. It must reproduce the dry run exactly.

    uv run scripts/rehearse.py /tmp/fake-ledger
"""

import hashlib
import json
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "scripts")
import freeze
import score

from forward import DATA, ROOT, entries
from forward.history import fit_table
from forward.openmeteo import MODELS

S, E = "2026-07-01", "2026-10-09"
# cached ladders predate the settle column
for f in (DATA / "ladders").glob(f"*_{S}_{E}.parquet"):
    d = pd.read_parquet(f)
    if "settle" not in d:
        d.assign(settle=np.nan).to_parquet(f, index=False)
# fake ledger from the archive, captured at 20:00 UTC on D-1
led = pathlib.Path(sys.argv[1])
led.mkdir(parents=True, exist_ok=True)
fc = pd.read_parquet(DATA / "forecasts.parquet")
fc["day"] = pd.to_datetime(fc["day"])
fc = fc[(fc.day >= S) & (fc.day <= E)]
for day, g in fc.groupby("day"):
    read = day - pd.Timedelta(days=1)
    rows = [
        {
            "station": r.station,
            "day": str(day.date()),
            **{m: (None if pd.isna(getattr(r, m)) else float(getattr(r, m))) for m in MODELS},
        }
        for r in g.itertuples()
    ]
    (led / f"{read.date()}.json").write_text(
        json.dumps({"captured_at": f"{read.date()}T20:05:00+00:00", "rows": rows})
    )
# throwaway freeze, round 99
cut = str((pd.Timestamp(S) - pd.Timedelta(days=2)).date())
params = entries.fit(fit_table(cut))
blob = json.dumps(params, sort_keys=True)
fz = {
    "round": 99,
    "cutoff": cut,
    "window": [S, E],
    "spec": "ROUND1.md",
    "spec_sha256": freeze.sha("ROUND1.md"),
    "code_sha256": {p: freeze.sha(p) for p in freeze.CODE},
    "params_sha256": hashlib.sha256(blob.encode()).hexdigest(),
    "params": json.loads(blob),
}
p = ROOT / "frozen" / "round99.json"
p.parent.mkdir(exist_ok=True)
p.write_text(json.dumps(fz))
try:
    res = score.sealed(99, led)
finally:
    p.unlink()
    if not any(p.parent.iterdir()):
        p.parent.rmdir()
print(
    "rows",
    res["rows"],
    "ledger",
    res["ledger"],
    "kalshi truth",
    res["truth_from_kalshi"],
    "complete",
    res["complete"],
)
for k, v in res["tests"].items():
    print(
        k,
        {kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in v.items()}
        if "verdict" in v
        else "",
    )
