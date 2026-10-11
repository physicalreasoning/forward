"""Point forecasts from Open-Meteo (free, no key): the archive for fitting, live runs for the round.

Both paths read hourly 2 m temperature and take the maximum over the station's local calendar
day ourselves, so the training and the live numbers are built the same way.

- `archive`: the Previous Runs API's `temperature_2m_previous_day1`, the value each model
  forecast for that hour one day earlier. Used only to fit entries before a freeze.
- `live`: the current forecast, captured at the read (`scripts/capture.py`). This is what a
  round scores.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import pandas as pd

from . import DATA

MODELS = {
    # name in the benchmark: Open-Meteo model id
    "aifs": "ecmwf_aifs025_single",  # ECMWF AIFS, a learned (graph transformer) model
    "ifs": "ecmwf_ifs025",  # ECMWF IFS, physics
    "gfs": "gfs_global",  # NOAA GFS, physics
    "icon": "icon_global",  # DWD ICON, physics
    "nbm": "ncep_nbm_conus",  # NOAA National Blend, statistical post-processing
}
ARCHIVE = "https://previous-runs-api.open-meteo.com/v1/forecast"
LIVE = "https://api.open-meteo.com/v1/forecast"
CACHE = DATA / "openmeteo"


def _get(url: str, params: dict, retries: int = 6) -> dict:
    q = url + "?" + urllib.parse.urlencode(params)
    for i in range(retries):
        try:
            with urllib.request.urlopen(q, timeout=60) as r:
                return json.loads(r.read())
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(5 * 2**i)
    raise RuntimeError("unreachable")


def _daily_max(hourly: dict, key: str) -> pd.Series:
    s = pd.Series(hourly.get(key), index=pd.to_datetime(hourly["time"]), dtype=float)
    g = s.groupby(s.index.normalize())
    # A day needs most of its hours; a model that stops mid-day must not report a low max.
    return g.max().where(g.count() >= 20)


def archive(st, start: str, end: str) -> pd.DataFrame:
    """Daily local max (deg F) per model from the previous-day run, one row per date."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"archive_{st.icao}_{start}_{end}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    keys = ["temperature_2m_previous_day1"]
    d = _get(
        ARCHIVE,
        {
            "latitude": st.lat,
            "longitude": st.lon,
            "start_date": start,
            "end_date": end,
            "hourly": ",".join(keys),
            "models": ",".join(MODELS.values()),
            "temperature_unit": "fahrenheit",
            "timezone": st.tz,
        },
    )
    out = pd.DataFrame(
        {name: _daily_max(d["hourly"], "temperature_2m_previous_day1_" + mid) for name, mid in MODELS.items()}
    )
    out.index.name = "day"
    out = out.reset_index()
    if pd.Timestamp(end) < pd.Timestamp.now().normalize() - pd.Timedelta(days=3):
        out.to_parquet(f, index=False)
    return out


def live(st) -> dict:
    """Each model's forecast max for tomorrow (station-local), from the latest run now."""
    d = _get(
        LIVE,
        {
            "latitude": st.lat,
            "longitude": st.lon,
            "hourly": "temperature_2m",
            "models": ",".join(MODELS.values()),
            "temperature_unit": "fahrenheit",
            "timezone": st.tz,
            "forecast_days": 3,
        },
    )
    tomorrow = (pd.Timestamp.now(tz=st.tz).normalize() + pd.Timedelta(days=1)).tz_localize(None)
    out = {"day": str(tomorrow.date())}
    for name, mid in MODELS.items():
        v = _daily_max(d["hourly"], "temperature_2m_" + mid).get(tomorrow)
        out[name] = None if v is None or pd.isna(v) else round(float(v), 2)
    return out
