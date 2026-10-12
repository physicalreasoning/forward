import json

import numpy as np
import pandas as pd
import pytest

from forward import entries
from forward.openmeteo import MODELS


def synthetic(n_days=600, seed=0):
    """Two stations. The truth is AIFS + 2 plus noise; the other models are noisier."""
    rng = np.random.default_rng(seed)
    days = pd.date_range("2025-01-01", periods=n_days, freq="D")
    rows = []
    for st in ("NY", "CHI"):
        season = 60 + 20 * np.sin(2 * np.pi * days.dayofyear / 365.25)
        truth = np.round(season + rng.normal(0, 3, n_days))
        aifs = truth - 2 + rng.normal(0, 1.0, n_days)
        d = {"station": st, "day": days, "high": truth, "aifs": aifs}
        for m in MODELS:
            if m != "aifs":
                d[m] = truth + rng.normal(0, 3.0, n_days)
        rows.append(pd.DataFrame(d))
    df = pd.concat(rows, ignore_index=True)
    df["prev_high"] = df.groupby("station")["high"].shift(1)
    return df


@pytest.fixture(scope="module")
def fitted():
    df = synthetic()
    return df, json.loads(json.dumps(entries.fit(df)))  # parameters are stored as JSON


def test_emos_recovers_the_bias(fitted):
    _, p = fitted
    e = p["NY"]["emos-aifs"]
    assert e["b"] == pytest.approx(1.0, abs=0.05)
    assert e["a"] == pytest.approx(2.0, abs=3.0)
    assert e["a"] + e["b"] * 60 == pytest.approx(62.0, abs=0.3)


def test_raw_spread_reflects_the_bias(fitted):
    _, p = fitted
    assert p["NY"]["raw-aifs"] > 2.0  # raw AIFS is 2 degrees off, so its RMSE is at least that
    assert p["NY"]["emos-aifs"]["sigma"]["7"] < p["NY"]["raw-aifs"]


def test_predict_shapes_and_baselines(fitted):
    df, p = fitted
    rows = df.tail(30).reset_index(drop=True)
    out = entries.predict(p, rows)
    assert set(out) == set(entries.ENTRIES)
    for mu, s in out.values():
        assert mu.shape == s.shape == (30,)
        assert np.isfinite(mu).all() and (s >= entries.SIGMA_FLOOR).all()
    assert np.array_equal(out["persistence"][0], rows["prev_high"].to_numpy())


def test_calibrated_beats_raw_and_copy_on_held_out_days(fitted):
    from forward import metrics

    _, p = fitted
    test = synthetic(seed=1).tail(200).reset_index(drop=True)
    out = entries.predict(p, test)
    y = test["high"].to_numpy()
    score = {e: metrics.log_score(y, *out[e]).mean() for e in ("emos-aifs", "raw-aifs", "persistence")}
    assert score["emos-aifs"] > score["raw-aifs"]
    assert score["emos-aifs"] > score["persistence"]


def test_unknown_station_and_missing_model_give_nan(fitted):
    _, p = fitted
    rows = pd.DataFrame(
        {"station": ["XXX", "NY"], "day": pd.to_datetime(["2026-01-05", "2026-01-05"]), "prev_high": [50, 50]}
        | {m: [60.0, np.nan if m == "gfs" else 60.0] for m in MODELS}
    )
    out = entries.predict(p, rows)
    assert np.isnan(out["climatology"][0][0])
    assert np.isnan(out["emos-gfs"][0][1]) and np.isnan(out["emos-all"][0][1])
    assert np.isfinite(out["emos-aifs"][0][1])
