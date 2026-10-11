"""The fitting and scoring table: one row per station-day with truth, D-1 high and model inputs."""

from __future__ import annotations

import pandas as pd

from . import DATA
from .openmeteo import MODELS


def fit_table(cutoff: str) -> pd.DataFrame:
    truth = pd.read_parquet(max(DATA.glob("truth_*.parquet")))
    truth["day"] = pd.to_datetime(truth["day"])
    truth = truth[truth["day"] <= pd.Timestamp(cutoff)]
    fc = pd.read_parquet(DATA / "forecasts.parquet")
    fc["day"] = pd.to_datetime(fc["day"])
    d = truth.merge(fc, on=["station", "day"], how="left")
    prev = truth.assign(day=truth["day"] + pd.Timedelta(days=1)).rename(columns={"high": "prev_high"})
    d = d.merge(prev, on=["station", "day"], how="left")
    for m in MODELS:
        d.loc[d["day"] > pd.Timestamp(cutoff), m] = float("nan")
    return d
