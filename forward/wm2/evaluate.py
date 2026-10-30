"""Score WM-2 forecasts on the cells whose truth exists, the same cells for every entry.

fc: {entry: [init, K, tile, lead, H, W]}; y: [init, tile, lead, H, W]. A pixel counts only if
its truth and every entry's every sample are finite (docs/WORLD_MODEL_TRACK.md, principle 2).
Per lead:

- fair CRPS on fields pooled to 1, 4 and 16 pixels (2, 8 and 32 km), mean over scored cells;
- fair energy score of each (init, tile) field pooled to 16 pixels (64 numbers), mean over rows;
- fractions skill score at 1 and 4 mm/h for neighbourhoods of 1, 5 and 17 pixels;
- the wet share of the truth (pixels at or above 0.1 mm/h), so a dry sample is visible.

Intervals resample whole init dates (forward/metrics.py `block_ci`).
"""

from __future__ import annotations

import numpy as np

from .. import metrics
from . import scores

POOLS = (1, 4, 16)
ENERGY_POOL = 16
THRESHOLDS = (1.0, 4.0)
NEIGHBOURHOODS = (1, 5, 17)
WET = 0.1


def common_mask(fc: dict[str, np.ndarray], y: np.ndarray) -> np.ndarray:
    ok = np.isfinite(y)
    for x in fc.values():
        ok &= np.isfinite(x).all(axis=1)
    return ok


def score(fc: dict[str, np.ndarray], y: np.ndarray, dates: list[str], leads) -> dict:
    ok = common_mask(fc, y)
    n_init, n_tile, n_lead = y.shape[:3]
    out = {"cells": int(ok.sum()), "leads": list(leads), "wet_share": [], "entries": {}}
    for li in range(n_lead):
        m = ok[:, :, li]
        out["wet_share"].append(float((y[:, :, li][m] >= WET).mean()) if m.any() else None)
    for name, x in fc.items():
        rec = {f"crps_{s}": [] for s in POOLS}
        rec.update({f"crps_{s}_ci": [] for s in POOLS})
        rec.update(energy=[], energy_ci=[])
        rec.update({f"fss_{t:g}_{n}": [] for t in THRESHOLDS for n in NEIGHBOURHOODS})
        for li in range(n_lead):
            xl = np.moveaxis(x[:, :, :, li], 1, 0)  # [K, init, tile, H, W]
            yl, ml = y[:, :, li], ok[:, :, li]
            for s in POOLS:
                c = scores.pooled_crps(xl, yl, ml, s)  # [init, tile, h, w]
                per = np.nanmean(np.where(np.isfinite(c), c, np.nan).reshape(n_init, -1), axis=1)
                good = np.isfinite(per)
                rec[f"crps_{s}"].append(float(np.nanmean(c)) if np.isfinite(c).any() else None)
                rec[f"crps_{s}_ci"].append(
                    metrics.block_ci(np.asarray(dates)[good], per[good]) if good.sum() > 1 else None
                )
            es = scores.pooled_energy(
                xl.reshape(xl.shape[0], -1, *xl.shape[-2:]),
                yl.reshape(-1, *yl.shape[-2:]),
                ml.reshape(-1, *ml.shape[-2:]),
                ENERGY_POOL,
            ).reshape(n_init, n_tile)
            good = np.isfinite(es)
            rec["energy"].append(float(es[good].mean()) if good.any() else None)
            d_rows = np.broadcast_to(np.asarray(dates)[:, None], es.shape)[good]
            rec["energy_ci"].append(metrics.block_ci(d_rows, es[good]) if good.sum() > 1 else None)
            for t in THRESHOLDS:
                for n in NEIGHBOURHOODS:
                    terms = [scores.fss_terms(xl[:, i], yl[i], ml[i], t, n) for i in range(n_init)]
                    rec[f"fss_{t:g}_{n}"].append(scores.fss(terms))
        out["entries"][name] = rec
    return out
