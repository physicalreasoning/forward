"""Hourly truth for the world-model track: ASOS 2 m temperature at each station (IEM archive).

The ensembles forecast the temperature at the top of each hour; ASOS reports routine METARs at
about :51 plus specials. The rule, fixed before any round: the truth for hour H is the report
nearest to H:00 within 10 minutes either side. No report in that window means no truth for that
hour, and the hour is dropped for every entry alike; nothing is interpolated.
"""

from __future__ import annotations

import pandas as pd
from isotherm import iem

WINDOW = pd.Timedelta(minutes=10)


def match_hours(obs: pd.DataFrame) -> pd.Series:
    """Hourly truth from raw reports (columns valid, tmpf), indexed by the hour (UTC)."""
    o = obs.dropna(subset=["tmpf"]).sort_values("valid")
    if o.empty:
        return pd.Series(dtype=float, name="tmpf")
    hours = pd.date_range(o.valid.min().ceil("h"), o.valid.max().floor("h"), freq="h", tz="UTC")
    m = pd.merge_asof(
        pd.DataFrame({"hour": hours}),
        o[["valid", "tmpf"]],
        left_on="hour",
        right_on="valid",
        direction="nearest",
        tolerance=WINDOW,
    )
    return m.set_index("hour").tmpf.dropna()


def hourly(icao: str, years) -> pd.Series:
    """Hourly 2 m temperature (deg F) at a station over whole calendar years."""
    obs = pd.concat([iem.asos(icao[1:], y) for y in years], ignore_index=True)
    return match_hours(obs).rename(icao)
