"""Run a frozen WM-1 entry at one init time, after checking its hashes, and write the forecast.

    x, rec = run(entry, init_time, stations, truth=..., captures=..., out=dir, sealed_by=deadline)

Steps, each of which refuses on failure:

1. `entry.verify()`: the code and weights hash as the manifest says (forward/wm/entry.py);
2. `entry.sealed_before(sealed_by)` when a deadline is given: every sealed file was committed,
   unchanged, before it (a sealed round passes the window's first init; a dry run passes none);
3. import entry.py and call `predict(init_time, stations, inputs)` under `access.guard()`, with
   an `Inputs` shim that serves only the declared sources and only what existed at init_time;
4. check the shape (K, stations, leads, variables) the manifest promises and that values are
   finite or NaN;
5. write `<entry id>/<init>.npy` (float32) and `<init>.json`: the forecast's own sha256, the
   entry's manifest, code and weights hashes, and the shim's log of what was read.
"""

from __future__ import annotations

import hashlib
import io
import json
import pathlib

import numpy as np
import pandas as pd

from .access import Inputs, guard
from .entry import Entry


class BadForecast(RuntimeError):
    pass


def init_name(init_time) -> str:
    return pd.Timestamp(init_time).strftime("%Y-%m-%dT%HZ")


def npy_bytes(x: np.ndarray) -> bytes:
    b = io.BytesIO()
    np.save(b, np.ascontiguousarray(x, dtype=np.float32), allow_pickle=False)
    return b.getvalue()


def run(
    entry: Entry,
    init_time,
    stations: list[str],
    truth: dict | None = None,
    captures=None,
    out: pathlib.Path | None = None,
    sealed_by=None,
) -> tuple[np.ndarray, dict]:
    entry.verify()
    sealed_at = entry.sealed_before(sealed_by) if sealed_by is not None else None
    inputs = Inputs(init_time, entry.manifest["inputs"], truth=truth, captures=captures)
    m = entry.manifest
    with guard():
        mod = entry.module()
        x = mod.predict(inputs.init_time, list(stations), inputs)
    x = np.asarray(x, dtype=np.float32)
    want = (m["K"], len(stations), m["leads"], len(m["variables"]))
    if x.shape != want:
        raise BadForecast(f"{entry.id}: shape {x.shape}, manifest promises {want}")
    if np.isinf(x).any():
        raise BadForecast(f"{entry.id}: infinite values")
    blob = npy_bytes(x)
    rec = {
        "entry": entry.id,
        "init_time": inputs.init_time.isoformat(),
        "stations": list(stations),
        "shape": list(x.shape),
        "variables": m["variables"],
        "forecast_sha256": hashlib.sha256(blob).hexdigest(),
        "manifest_sha256": entry.manifest_sha256,
        "code_sha256": entry.code_sha256,
        "weights_sha256": entry.weights_sha256,
        "sealed_at": None if sealed_at is None else sealed_at.isoformat(),
        "nan_share": float(np.isnan(x).mean()),
        "read": inputs.log,
    }
    if out is not None:
        d = pathlib.Path(out) / entry.id
        d.mkdir(parents=True, exist_ok=True)
        name = init_name(inputs.init_time)
        (d / f"{name}.npy").write_bytes(blob)
        (d / f"{name}.json").write_text(json.dumps(rec, indent=1) + "\n")
    return x, rec


def load_forecast(path: pathlib.Path) -> tuple[np.ndarray, dict]:
    """Read a written forecast, refusing it if its bytes no longer match the recorded sha256."""
    path = pathlib.Path(path)
    blob = path.with_suffix(".npy").read_bytes()
    rec = json.loads(path.with_suffix(".json").read_text())
    if hashlib.sha256(blob).hexdigest() != rec["forecast_sha256"]:
        raise BadForecast(f"{path.name}: forecast bytes changed since it was written")
    return np.load(io.BytesIO(blob), allow_pickle=False), rec
