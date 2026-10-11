"""Ground truth: the NWS CLI daily high at each station (what Kalshi's ladders settle on)."""

from __future__ import annotations

import pandas as pd
from isotherm import iem

from . import DATA


def highs(st, years) -> pd.Series:
    """CLI high (integer deg F) by local date. Closed years are cached by isotherm's client."""
    parts = []
    for y in years:
        df = iem.cli(st.icao, y)
        if len(df):
            parts.append(df.set_index("valid")["high"])
    s = pd.concat(parts).dropna() if parts else pd.Series(dtype=float)
    s.index = pd.to_datetime(s.index).normalize()
    return s[~s.index.duplicated(keep="last")].sort_index().rename("high")


def all_highs(stations, years) -> pd.DataFrame:
    f = DATA / f"truth_{min(years)}_{max(years)}.parquet"
    rows = [highs(st, years).to_frame().assign(station=k) for k, st in stations.items()]
    df = pd.concat(rows).rename_axis("day").reset_index()
    DATA.mkdir(parents=True, exist_ok=True)
    df.to_parquet(f, index=False)
    return df
