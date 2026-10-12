import numpy as np
import pandas as pd
import pytest
from scipy.stats import gamma

from forward import fill_entries as fe
from forward import fills


def rows(n=4000, seed=0):
    """Synthetic actions: fills are likelier near the best bid and after recent trading."""
    rng = np.random.default_rng(seed)
    d = pd.DataFrame(
        {
            "level": rng.choice(fills.LEVELS, n),
            "size": rng.choice(fills.SIZES, n),
            "queue": rng.exponential(50, n),
            "better": rng.exponential(20, n),
            "depth": rng.exponential(500, n) + 1,
            "depth_other": rng.exponential(500, n) + 1,
            "spread": rng.integers(1, 6, n).astype(float),
            "mid": rng.uniform(5, 95, n),
            "n_exec": rng.poisson(3, n),
            "v_exec": rng.exponential(30, n),
            "v_cancel": rng.exponential(300, n),
            "n_exec_all": rng.poisson(10, n),
            "n_exec_at": rng.poisson(1, n),
            "v_exec_at": rng.exponential(10, n),
            "side": rng.integers(0, 2, n),
            "series": rng.choice(["KXHIGHNY", "KXWTI"], n),
        }
    )
    d["crossed"] = d["n_exec_at"] > 0
    z = -1.5 + 0.8 * d["level"] + 1.5 * d["crossed"]
    d["y"] = (rng.uniform(size=n) < 1 / (1 + np.exp(-z))).astype(int)
    d["move"] = np.where(d["y"] == 1, rng.normal(-0.3, 2, n), np.nan)
    return d


def test_binary_scores():
    assert fe.log_score([1, 0], [0.8, 0.8]) == pytest.approx(np.log([0.8, 0.2]))
    assert fe.brier([1, 0], [0.8, 0.8]) == pytest.approx([0.04, 0.64])
    assert np.isfinite(fe.log_score([1], [0.0])[0])  # floored, never -inf


def test_reliability_of_a_calibrated_forecast_is_near_zero():
    rng = np.random.default_rng(0)
    p = rng.uniform(size=50000)
    y = rng.uniform(size=p.size) < p
    r = fe.reliability(y, p)
    assert r["ece"] < 0.01 and len(r["bins"]) == 10
    assert fe.reliability(y, np.full(p.size, 0.9))["ece"] > 0.3


def test_base_rate_is_the_smoothed_frequency_by_level_and_size():
    d = rows()
    m = fe.BaseRate().fit(d)
    g = d[(d["level"] == 0) & (d["size"] == 10)]
    assert m.predict(g)[0] == pytest.approx((g["y"].sum() + 1) / (len(g) + 2))


def test_copy_uses_only_whether_the_price_traded():
    d = rows()
    p = fe.Copy().fit(d).predict(d)
    assert len(np.unique(p)) == 2
    assert p[d["crossed"].to_numpy()].mean() > p[~d["crossed"].to_numpy()].mean()


def test_queue_model_with_nobody_ahead_is_the_poisson_waiting_time():
    d = rows(5)
    d["queue"] = 0.0
    d["n_exec_at"], d["v_exec_at"] = 5000, 5000.0 * 2  # a sharp rate posterior, mean size 2
    m = fe.Queue(2_000).fit(d)  # rate about 2.8 a second: a 2 s horizon is informative
    m.m = 2.0
    mu = (5000 + m.mu[0] * fe.PRIOR_S) / (fe.LOOKBACK_S + fe.PRIOR_S)
    size = (5000 * 2 + 2 * fe.PRIOR_TRADES) / (5000 + fe.PRIOR_TRADES)
    p = m.predict(d.iloc[:1].assign(level=0, size=10))
    exact = gamma.cdf(2, a=10 / size, scale=1 / mu)
    assert 0.2 < exact < 0.8
    assert p[0] == pytest.approx(exact, abs=0.01)


def test_queue_model_is_slower_with_a_longer_queue_and_likelier_over_longer_horizons():
    d = rows(3).assign(level=0, size=10, n_exec_at=6, v_exec_at=60.0, v_cancel=100.0, depth=500.0)
    d["queue"] = [0.0, 50.0, 500.0]
    m = fe.Queue(1_800_000).fit(rows())
    p = m.predict(d)
    assert p[0] > p[1] > p[2]
    m.h = 7200
    assert (m.predict(d) > p).all()


def test_learned_entries_beat_the_base_rate_out_of_sample():
    train, test = rows(seed=1), rows(seed=2)
    y = test["y"].to_numpy()
    base = fe.log_score(y, fe.BaseRate().fit(train).predict(test)).mean()
    logit = fe.log_score(y, fe.Logistic().fit(train).predict(test)).mean()
    cal = fe.log_score(y, fe.QueueCal(1_800_000).fit(train).predict(test)).mean()
    assert logit > base
    assert np.isfinite(cal)


def test_every_entry_returns_probabilities_and_moves():
    d = rows(500)
    for e in fe.entries("30m"):
        p = e.fit(d).predict(d)
        assert p.shape == (len(d),) and ((p > 0) & (p < 1)).all()
        assert np.isfinite(e.move(d)).all()
