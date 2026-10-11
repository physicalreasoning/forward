"""Seeded entries for the station-high task. Each maps a fit table to frozen parameters, and
parameters plus one day's inputs to a Gaussian (mu, sigma) on the latent CLI high.

Inputs at the read (D-1, 20:00 UTC): the station's CLI highs through D-2 (and D-1's, which is
near-final by then; see ROUND1.md), the day of year, and each model's live forecast max for D.

Entries are deliberately simple, so the comparison is between sources of information:
  climatology        station mean and spread for the time of year
  persistence        D-1's high, spread from history: the copy baseline
  raw-<model>        the model's number as is, spread = its past RMSE at the station
  emos-<model>       a + b * model, spread by station and month (Gneiting et al. 2005, without
                     the ensemble-spread term, since these are single runs)
  emos-all           a + sum b_m * model_m, ridge, all five models
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .openmeteo import MODELS

SIGMA_FLOOR = 1.0
RIDGE = 1.0


def _doy_dist(a, b):
    d = np.abs(a - b) % 365.25
    return np.minimum(d, 365.25 - d)


def _sigma_by_month(resid: pd.Series, month: pd.Series) -> dict:
    """Residual SD by calendar month, each month pooled with its neighbours."""
    out = {}
    for m in range(1, 13):
        near = {(m - 2) % 12 + 1, m, m % 12 + 1}
        r = resid[month.isin(near)]
        out[str(m)] = float(max(np.sqrt(np.mean(r**2)) if len(r) > 20 else resid.std(), SIGMA_FLOOR))
    return out


def fit(train: pd.DataFrame) -> dict:
    """train: rows (station, day, high, prev_high, <model>...) that settled before the cutoff."""
    params = {}
    for st, g in train.groupby("station"):
        g = g.dropna(subset=["high"])
        doy = g["day"].dt.dayofyear.to_numpy()
        clim = {}
        for d in range(1, 367):
            w = g["high"][_doy_dist(doy, d) <= 10]
            clim[str(d)] = [float(w.mean()), float(max(w.std(), SIGMA_FLOOR))]
        p = {"climatology": clim}
        gp = g.dropna(subset=["prev_high"])
        p["persistence"] = _sigma_by_month(gp["high"] - gp["prev_high"], gp["day"].dt.month)
        # Every model entry is fit on the same days (all five models present), so no model
        # gains from a longer archive and the learned-vs-physics comparison is like for like.
        common = g.dropna(subset=list(MODELS))
        for name in MODELS:
            gm = common
            if len(gm) < 120:
                continue
            x, y = gm[name].to_numpy(), gm["high"].to_numpy()
            p["raw-" + name] = float(max(np.sqrt(np.mean((y - x) ** 2)), SIGMA_FLOOR))
            b, a = np.polyfit(x, y, 1)
            p["emos-" + name] = {
                "a": float(a),
                "b": float(b),
                "sigma": _sigma_by_month(pd.Series(y - (a + b * x), gm.index), gm["day"].dt.month),
            }
        ga = common
        if len(ga) >= 120:
            X = np.column_stack([np.ones(len(ga)), ga[list(MODELS)].to_numpy()])
            pen = RIDGE * np.eye(X.shape[1])
            pen[0, 0] = 0
            w = np.linalg.solve(X.T @ X + pen, X.T @ ga["high"].to_numpy())
            r = pd.Series(ga["high"].to_numpy() - X @ w, ga.index)
            p["emos-all"] = {"w": [float(v) for v in w], "sigma": _sigma_by_month(r, ga["day"].dt.month)}
        params[st] = p
    return params


ENTRIES = (
    ["climatology", "persistence"]
    + ["raw-" + m for m in MODELS]
    + ["emos-" + m for m in MODELS]
    + ["emos-all"]
)


def predict(params: dict, rows: pd.DataFrame) -> dict:
    """{entry: (mu, sigma) arrays} for rows (station, day, prev_high, <model>...); NaN where missing."""
    n = len(rows)
    out = {e: (np.full(n, np.nan), np.full(n, np.nan)) for e in ENTRIES}
    for i, r in enumerate(rows.itertuples(index=False)):
        p = params.get(r.station)
        if p is None:
            continue
        mo, doy = r.day.month, r.day.dayofyear
        out["climatology"][0][i], out["climatology"][1][i] = p["climatology"][str(doy)]
        if not pd.isna(r.prev_high):
            out["persistence"][0][i] = r.prev_high
            out["persistence"][1][i] = _month(p["persistence"], mo)
        for name in MODELS:
            x = getattr(r, name)
            if pd.isna(x) or "raw-" + name not in p:
                continue
            out["raw-" + name][0][i], out["raw-" + name][1][i] = x, p["raw-" + name]
            e = p["emos-" + name]
            out["emos-" + name][0][i] = e["a"] + e["b"] * x
            out["emos-" + name][1][i] = _month(e["sigma"], mo)
        xs = [getattr(r, m) for m in MODELS]
        if "emos-all" in p and not any(pd.isna(v) for v in xs):
            w = p["emos-all"]["w"]
            out["emos-all"][0][i] = w[0] + float(np.dot(w[1:], xs))
            out["emos-all"][1][i] = _month(p["emos-all"]["sigma"], mo)
    return out


def _month(d: dict, m: int) -> float:
    return d[str(m)]  # JSON keys: parameters are stored and hashed as JSON
