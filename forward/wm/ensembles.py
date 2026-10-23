"""Ensemble trajectories from Open-Meteo's Ensemble API (free, no key), captured at the read.

A world-model entry is scored on joint futures, so the baselines it must beat are the
operational ensembles: every member's hourly trajectory for the next 7 days at each station.
Open-Meteo keeps no archive of past ensemble runs (`past_days` reaches back about four days),
so a run that was not captured at the read is gone; `scripts/capture_wm.py` writes them down.

Each capture also records each model's run metadata (initialisation and availability time), so
a scored trajectory can be shown to come from a run published before the read.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
META = "https://ensemble-api.open-meteo.com/data/{}/static/meta.json"

# name in the benchmark: (Ensemble API `models` value, metadata domain)
MODELS = {
    "aifs_ens": ("ecmwf_aifs025", "ecmwf_aifs025_ensemble"),  # ECMWF AIFS ENS, learned, 51 members
    "ifs_ens": ("ecmwf_ifs025", "ecmwf_ifs025_ensemble"),  # ECMWF IFS ENS, physics, 51
    "gefs": ("gfs025", "ncep_gefs025"),  # NOAA GEFS, physics, 31
    # Open-Meteo's ICON-EPS metadata file stopped updating on 2026-10-06 while the data stayed
    # current (checked against IFS ENS), so no run times are recorded for it.
    "icon_eps": ("icon_global", None),  # DWD ICON-EPS, physics, 40
    "geps": ("gem_global", "cmc_gem_geps"),  # Canada GEPS, physics, 21
    "mogreps_g": ("ukmo_global_ensemble_20km", "ukmo_global_ensemble_20km"),  # UK Met Office, 18
}
VARIABLES = ("temperature_2m", "precipitation")


def _get(url: str, params: dict | None = None, retries: int = 6):
    q = url + ("?" + urllib.parse.urlencode(params) if params else "")
    for i in range(retries):
        try:
            with urllib.request.urlopen(q, timeout=120) as r:
                return json.loads(r.read())
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(5 * 2**i)
    raise RuntimeError("unreachable")


def meta(domain: str | None) -> dict:
    """Run times of a model's latest run, as Unix seconds (Open-Meteo's metadata file)."""
    if domain is None:
        return {}
    d = _get(META.format(domain))
    return {k: d[k] for k in ("last_run_initialisation_time", "last_run_availability_time") if k in d}


def _frame(js: dict, station: str, model: str) -> pd.DataFrame:
    h = js["hourly"]
    valid = pd.to_datetime(h["time"], utc=True)
    parts = []
    for var in VARIABLES:
        # The control run is `<var>`, perturbed members `<var>_memberNN`.
        cols = sorted(k for k in h if k == var or k.startswith(var + "_member"))
        for c in cols:
            m = 0 if c == var else int(c.rsplit("member", 1)[1])
            parts.append(pd.DataFrame({"valid": valid, "member": m, "var": var, "value": h[c]}))
    d = pd.concat(parts, ignore_index=True)
    d = d.pivot_table(index=["valid", "member"], columns="var", values="value", dropna=False).reset_index()
    d.columns.name = None
    d.insert(0, "model", model)
    d.insert(0, "station", station)
    return d


def fetch(stations: dict, model: str, days: int = 7) -> pd.DataFrame:
    """Every member's hourly trajectory for one model at all stations (one request).

    Temperatures in deg F rounded to 0.1, precipitation in mm rounded to 0.1, so captures are
    small and exactly reproducible from the stored file.
    """
    keys = list(stations)
    js = _get(
        URL,
        {
            "latitude": ",".join(str(stations[k].lat) for k in keys),
            "longitude": ",".join(str(stations[k].lon) for k in keys),
            "hourly": ",".join(VARIABLES),
            "models": MODELS[model][0],
            "forecast_days": days,
            "temperature_unit": "fahrenheit",
            "timezone": "GMT",
        },
    )
    js = js if isinstance(js, list) else [js]
    d = pd.concat([_frame(j, k, model) for k, j in zip(keys, js, strict=True)], ignore_index=True)
    for v in VARIABLES:
        d[v] = d[v].astype("float32").round(1)
    d["member"] = d["member"].astype("int16")
    return d


def to_array(d: pd.DataFrame, var: str = "temperature_2m") -> tuple[np.ndarray, pd.DatetimeIndex, list]:
    """One model at one station as samples[member, hour], with the valid times and member ids."""
    w = d.pivot_table(index="member", columns="valid", values=var, dropna=False)
    return w.to_numpy(), pd.DatetimeIndex(w.columns), list(w.index)
