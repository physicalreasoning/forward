import numpy as np
import pandas as pd
import pytest

from forward import prices
from forward.tsfm import Z90, _to_lognormal


def ladder(kind="partition"):
    if kind == "partition":
        lo, hi = np.array([-np.inf, 99.0, 101.0]), np.array([99.0, 101.0, np.inf])
        y = np.array([0, 1, 0])
    else:
        lo, hi = np.array([99.0, 101.0]), np.array([np.inf, np.inf])
        y = np.array([1, 0])  # settled between the strikes
    return {
        "kind": kind,
        "lo": lo,
        "hi": hi,
        "y": y,
        "bid": np.full(len(lo), 0.3),
        "ask": np.full(len(lo), 0.4),
    }


def test_to_buckets_is_a_distribution_even_if_quotes_are_not_monotone():
    p = prices.to_buckets(np.array([0.8, 0.85, 0.2]))
    assert p.sum() == pytest.approx(1.0) and (p > 0).all()


@pytest.mark.parametrize("kind", ["partition", "threshold"])
def test_from_cdf_and_outcome_agree_across_ladder_kinds(kind):
    pr = ladder(kind)
    p = prices.from_cdf(pr, prices.lognormal_cdf(100.0, 0.01))
    assert p.sum() == pytest.approx(1.0)
    assert prices.outcome(pr) == 1
    assert p[prices.outcome(pr)] == pytest.approx(0.68, abs=0.02)  # +/- 1 sigma


def test_copy_baseline_centres_on_the_last_close():
    ts = np.arange(0, 90 * 86400, 3600)
    cl = 100 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.002, ts.size)))
    pr = ladder() | {"read_ts": int(ts[-1]) - 86400 + 3600, "close_ts": int(ts[-1]) + 3600}
    n = prices.bars_before(ts, pr["read_ts"])
    last = cl[n - 1]
    pr["lo"], pr["hi"] = (
        np.array([-np.inf, last * 0.999, last * 1.001]),
        np.array([last * 0.999, last * 1.001, np.inf]),
    )
    p = prices.copy_baseline(pr, ts, cl)
    assert p[0] == pytest.approx(p[2], rel=0.05)  # symmetric around the last close, no drift


def test_bars_before_uses_only_bars_closed_by_the_read():
    ts = np.array([0, 3600, 7200])
    assert prices.bars_before(ts, 3600) == 1  # the bar starting at 0 closes at 3600
    assert prices.bars_before(ts, 3599) == 0


def test_horizon_counts_bars_in_the_window():
    ts = np.arange(0, 40 * 86400, 3600)
    pr = {"close_ts": 39 * 86400, "read_ts": 39 * 86400 - 6 * 3600}
    assert prices.horizon_bars(pr, ts) == 6


def test_market_bid_floor():
    pr = ladder() | {"bid": np.array([0.0, 0.5, 0.3])}
    p = prices.market(pr, "bid")
    assert p.sum() == pytest.approx(1.0) and p[0] > 0


def test_problems_need_two_two_sided_quotes():
    df = pd.DataFrame(
        {
            "event": ["E"] * 3,
            "strike_type": ["less", "between", "greater"],
            "floor": [None, 99.0, 101.0],
            "cap": [99.0, 101.0, None],
            "result": [0, 1, 0],
            "close_ts": [1_800_000_000] * 3,
            "bid_24h": [0.1, 0.5, 0.2],
            "ask_24h": [0.15, 0.6, 0.3],
            "bid_6h": [0.0, 0.5, np.nan],
            "ask_6h": [0.05, 0.6, np.nan],
        }
    )
    probs = prices.problems("KXWTI", df)
    assert [p["lead"] for p in probs] == ["24h"]
    assert probs[0]["kind"] == "partition"


def test_quantiles_to_lognormal():
    c, s = _to_lognormal(np.array([90.0]), np.array([100.0]), np.array([110.0]))
    assert c[0] == 100.0
    assert s[0] == pytest.approx((np.log(110) - np.log(90)) / Z90)
