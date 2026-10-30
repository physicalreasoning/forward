"""Score WM-1 forecasts on the hours whose truth exists, the same rows for every entry.

Forecasts are arrays [K, station, lead, variable] per init (forward/wm/runner.py); truth is
[init, station, lead]. A cell counts only if its truth exists and every entry has a forecast
for it (docs/WORLD_MODEL_TRACK.md, principle 2). Scores (forward/wm/scores.py):

- fair CRPS per hour, pooled over every common cell;
- energy score (primary) and variogram score (p = 0.5) on each window of the first W hours,
  for the (init, station) rows with a forecast from every entry at all W hours and truth at
  no fewer than MIN_COVERAGE of them, scored on the hours with truth only (the same hours for
  every entry, so the comparison stays proper if missingness does not depend on the forecasts).
  A 168 h window needs a week of truth after its init, so early in a round only the shorter
  windows have rows;
- PIT per hour, pooled, summarised as central-interval coverage and a flatness error.

Intervals resample whole init dates (forward/metrics.py `block_ci`): stations on one init share
a weather pattern and a model run, so they are not independent.
"""

from __future__ import annotations

import numpy as np

from .. import metrics
from . import scores

WINDOWS = (24, 48, 72, 96, 120, 144, 168)
LEAD_BIN = 6
MIN_COVERAGE = 0.95  # share of a window's hours that must be common cells (docs/WM1_DRYRUN.md, finding 4)


def common_mask(fc: dict[str, np.ndarray], y: np.ndarray) -> np.ndarray:
    """[init, station, lead] cells with truth and a forecast from every entry."""
    return np.isfinite(y) & forecast_mask(fc)


def forecast_mask(fc: dict[str, np.ndarray]) -> np.ndarray:
    """[init, station, lead] cells with a forecast from every entry."""
    ok = None
    for x in fc.values():
        f = np.isfinite(x).all(axis=1)
        ok = f if ok is None else ok & f
    return ok


def window_rows(mask: np.ndarray, w: int, fmask: np.ndarray | None = None) -> np.ndarray:
    """[init, station] rows whose first w leads are at least MIN_COVERAGE common cells.

    The allowance covers missing truth only: if `fmask` is given, a row also needs a forecast
    from every entry at every one of its w leads, so no entry can choose which hours are scored.
    """
    if mask.shape[-1] < w:
        return np.zeros(mask.shape[:2], dtype=bool)
    rows = mask[:, :, :w].mean(axis=-1) >= MIN_COVERAGE - 1e-9
    if fmask is not None:
        rows &= fmask[:, :, :w].all(axis=-1)
    return rows


def _window_scores(xx: np.ndarray, yy: np.ndarray, mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Energy and variogram score per row on its observed hours. xx [K, row, w], yy and mm [row, w]."""
    es = np.empty(len(yy))
    vs = np.empty(len(yy))
    for r in range(len(yy)):
        h = mm[r]
        es[r] = scores.energy(xx[:, r : r + 1, h], yy[r : r + 1, h])[0]
        vs[r] = scores.variogram(xx[:, r : r + 1, h], yy[r : r + 1, h], p=0.5)[0]
    return es, vs


def score(fc: dict[str, np.ndarray], y: np.ndarray, inits: list[str], rng_seed: int = 0) -> dict:
    """fc: {entry: [init, K, station, lead]}; y: [init, station, lead]; inits: date labels."""
    fmask = forecast_mask(fc)
    mask = np.isfinite(y) & fmask
    dates_cell = np.broadcast_to(np.asarray(inits)[:, None, None], mask.shape)[mask]
    out = {"cells": int(mask.sum()), "entries": {}, "windows": {}}
    leads = np.broadcast_to(np.arange(1, y.shape[-1] + 1), mask.shape)[mask]
    for name, x in fc.items():
        xs = np.moveaxis(x, 1, 0)  # [K, init, station, lead]
        c = scores.crps(xs, y)[mask]
        u = scores.pit(xs, y, np.random.default_rng(rng_seed))[mask]
        bins = (leads - 1) // LEAD_BIN
        by_lead = [
            float(c[bins == b].mean()) if (bins == b).any() else None
            for b in range(-(-y.shape[-1] // LEAD_BIN))
        ]
        out["entries"][name] = {
            "crps": float(c.mean()),
            "crps_ci": metrics.block_ci(dates_cell, c),
            "crps_by_lead": by_lead,
            "pit_hist": np.histogram(u, bins=10, range=(0, 1))[0].tolist(),
            **metrics.calibration(u),
        }
    for w in WINDOWS:
        rows = window_rows(mask, w, fmask)
        n_inits = int(rows.any(axis=1).sum())
        complete = int((rows & mask[:, :, :w].all(axis=-1)).sum()) if rows.any() else 0
        rec = {"rows": int(rows.sum()), "rows_complete": complete, "inits": n_inits, "entries": {}}
        if rows.any():
            ii, ss = np.nonzero(rows)
            dates = np.asarray(inits)[ii]
            yy = y[ii, ss, :w]
            mm = mask[ii, ss, :w]
            per = {}
            for name, x in fc.items():
                xx = np.moveaxis(x[ii, :, ss, :w], 1, 0)  # [K, row, w]
                es, vs = _window_scores(xx, yy, mm)
                per[name] = es
                rec["entries"][name] = {
                    "energy": float(es.mean()),
                    "energy_ci": metrics.block_ci(dates, es),
                    "variogram": float(vs.mean()),
                    "variogram_ci": metrics.block_ci(dates, vs),
                }
            if "climatology" in per:
                for name, es in per.items():
                    if name != "climatology":
                        rec["entries"][name]["energy_minus_climatology"] = metrics.diff(
                            dates, es, per["climatology"]
                        )
        out["windows"][str(w)] = rec
    return out
