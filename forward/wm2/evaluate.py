"""Score WM-2 forecasts on the cells whose truth exists, the same cells for every entry.

Forecasts are scored one init at a time (`init_stats`, which keeps sums, not fields, so a round
never holds every forecast in memory) and pooled over inits (`combine`). For one init, fc is
{entry: [K, tile, lead, H, W]} and y is [tile, lead, H, W]. A pixel counts only if its truth and
every entry's every sample are finite (docs/WORLD_MODEL_TRACK.md, principle 2). Per lead:

- fair CRPS on fields average-pooled to 1, 4 and 16 pixels (2, 8 and 32 km), mean over cells;
- fair energy score of each tile's field pooled to 16 pixels (64 numbers), mean over rows;
- fair CRPS at each station's own pixel;
- fractions skill score at 1 and 4 mm/h for neighbourhoods of 1, 5 and 17 pixels (2, 10 and
  34 km), accumulated over inits before the ratio;
- the wet share of the truth (pixels at or above 0.1 mm/h), so a dry sample is visible.

Intervals resample whole init dates (forward/metrics.py `block_ci`).
"""

from __future__ import annotations

import numpy as np

from .. import metrics
from ..wm import scores as wm_scores
from . import scores

POOLS = (1, 4, 16)
ENERGY_POOL = 16
THRESHOLDS = (1.0, 4.0)
NEIGHBOURHOODS = (1, 5, 17)
WET = 0.1


def common_mask(fc: dict[str, np.ndarray], y: np.ndarray) -> np.ndarray:
    ok = np.isfinite(y)
    for x in fc.values():
        ok &= np.isfinite(x).all(axis=0)
    return ok


def init_stats(fc: dict[str, np.ndarray], y: np.ndarray, points=None) -> dict:
    """Sums for one init. points: per tile, the station's (row, col) in the scored box, or None."""
    ok = common_mask(fc, y)
    n_tile, n_lead = y.shape[:2]
    out = {
        "cells": int(ok.sum()),
        "wet": [[int((y[:, li][ok[:, li]] >= WET).sum()), int(ok[:, li].sum())] for li in range(n_lead)],
        "entries": {},
    }
    for name, x in fc.items():
        rec = {}
        for li in range(n_lead):
            xl, yl, ml = x[:, :, li], y[:, li], ok[:, li]
            for s in POOLS:
                c = scores.pooled_crps(xl, yl, ml, s)
                rec.setdefault(f"crps_{s}", []).append([float(np.nansum(c)), int(np.isfinite(c).sum())])
            es = scores.pooled_energy(xl, yl, ml, ENERGY_POOL)
            rec.setdefault("energy", []).append([None if not np.isfinite(e) else float(e) for e in es])
            st = []
            for t in range(n_tile):
                p = None if points is None else points[t]
                if p is None or not ml[t][p]:
                    st.append(None)
                else:
                    st.append(float(wm_scores.crps(xl[:, t][(slice(None), *p)], yl[t][p])))
            rec.setdefault("station", []).append(st)
            for th in THRESHOLDS:
                for n in NEIGHBOURHOODS:
                    rec.setdefault(f"fss_{th:g}_{n}", []).append(list(scores.fss_terms(xl, yl, ml, th, n)))
        out["entries"][name] = rec
    return out


def _mean_ci(dates, rows) -> tuple[float | None, list | None, int]:
    """Mean and date-block CI of per-row values (None rows dropped)."""
    d = [a for a, v in zip(dates, rows, strict=True) if v is not None]
    v = [v for v in rows if v is not None]
    if not v:
        return None, None, 0
    ci = metrics.block_ci(d, v) if len(set(d)) > 1 else None
    return float(np.mean(v)), ci, len(v)


def combine(stats: list[dict], dates: list[str], leads) -> dict:
    """Pool per-init sums into per-lead scores. dates: each init's date (the resampling block)."""
    n_lead = len(leads)
    first = stats[0]["entries"]
    out = {
        "inits": len(stats),
        "cells": sum(s["cells"] for s in stats),
        "leads": list(leads),
        "wet_share": [],
        "entries": {},
    }
    for li in range(n_lead):
        w = sum(s["wet"][li][0] for s in stats)
        n = sum(s["wet"][li][1] for s in stats)
        out["wet_share"].append(w / n if n else None)
    for name in first:
        rec: dict[str, list] = {}
        for li in range(n_lead):
            per = [s["entries"][name] for s in stats]
            for p in POOLS:
                k = f"crps_{p}"
                tot = sum(e[k][li][0] for e in per)
                cnt = sum(e[k][li][1] for e in per)
                rec.setdefault(k, []).append(tot / cnt if cnt else None)
                init_means = [e[k][li][0] / e[k][li][1] if e[k][li][1] else None for e in per]
                rec.setdefault(k + "_ci", []).append(_mean_ci(dates, init_means)[1])
            for k in ("energy", "station"):
                d = [dd for dd, e in zip(dates, per, strict=True) for _ in e[k][li]]
                v = [x for e in per for x in e[k][li]]
                m, ci, nrow = _mean_ci(d, v)
                rec.setdefault(k, []).append(m)
                rec.setdefault(k + "_ci", []).append(ci)
                rec.setdefault(k + "_rows", []).append(nrow)
            for th in THRESHOLDS:
                for n in NEIGHBOURHOODS:
                    k = f"fss_{th:g}_{n}"
                    f = scores.fss([tuple(e[k][li]) for e in per])
                    rec.setdefault(k, []).append(None if np.isnan(f) else f)
        out["entries"][name] = rec
    return out
