import numpy as np
import pytest

from forward import metrics


def test_pmf_sums_to_one_over_the_grid():
    k = np.arange(-40, 131)
    p = metrics.cdf(k + 0.5, 70.0, 4.0) - metrics.cdf(k - 0.5, 70.0, 4.0)
    assert p.sum() == pytest.approx(1.0, abs=1e-9)


def test_log_score_is_log_of_the_integer_probability():
    y, mu, s = np.array([70.0]), np.array([70.0]), np.array([1.0])
    expected = np.log(metrics.cdf(70.5, 70, 1) - metrics.cdf(69.5, 70, 1))
    assert metrics.log_score(y, mu, s)[0] == pytest.approx(expected)


def test_log_score_is_floored_far_in_the_tail():
    assert metrics.log_score(np.array([0.0]), np.array([100.0]), np.array([1.0]))[0] == pytest.approx(
        np.log(metrics.EPS)
    )


def test_rps_is_near_zero_for_a_sharp_correct_forecast_and_grows_with_error():
    y = np.array([70.0, 70.0, 70.0])
    r = metrics.rps(y, np.array([70.0, 72.0, 80.0]), np.array([0.05, 0.05, 0.05]))
    assert r[0] < 1e-6
    assert r[0] < r[1] < r[2]
    # A point forecast off by d integer steps has RPS d.
    assert r[1] == pytest.approx(2.0, abs=1e-6)


def test_pit_is_uniform_for_a_calibrated_forecast():
    rng = np.random.default_rng(1)
    mu = rng.normal(60, 10, 20000)
    y = np.round(mu + rng.normal(0, 3, mu.size))
    u = metrics.pit(y, mu, np.full(mu.size, 3.0), rng)
    cal = metrics.calibration(u)
    assert cal["coverage"]["80"] == pytest.approx(0.8, abs=0.02)
    assert cal["pit_flatness_error"] < 0.02


def test_block_ci_resamples_whole_dates_and_brackets_the_mean():
    dates = np.repeat(np.arange(50), 19)
    vals = np.random.default_rng(0).normal(0.1, 1, dates.size)
    lo, hi = metrics.block_ci(dates, vals)
    assert lo < vals.mean() < hi
    assert metrics.block_ci(dates, vals) == [lo, hi]  # seeded, reproducible


def test_block_ci_is_wider_when_rows_within_a_date_move_together():
    rng = np.random.default_rng(0)
    dates = np.repeat(np.arange(50), 19)
    shared = rng.normal(0, 1, 50)[dates]  # every station on a date moves together
    ci_shared = np.diff(metrics.block_ci(dates, shared))[0]
    ci_indep = np.diff(metrics.block_ci(dates, rng.normal(0, 1, dates.size)))[0]
    assert ci_shared > 2 * ci_indep


def test_month_share():
    months = np.array(["a"] * 10 + ["b"] * 10)
    assert metrics.month_share(months, np.r_[np.zeros(10), np.ones(10)]) == pytest.approx(1.0)
    assert metrics.month_share(months, np.tile([0.0, 1.0], 10)) == pytest.approx(0.0)


def test_bucket_probs_partition_sums_to_one():
    edges = [(-np.inf, 65.5), (65.5, 67.5), (67.5, 69.5), (69.5, np.inf)]
    assert metrics.bucket_probs(edges, 67.0, 2.0).sum() == pytest.approx(1.0, abs=1e-6)


def test_market_probs_floors_empty_bids_and_normalises():
    bid = np.array([np.nan, 0.30, 0.50])
    ask = np.array([0.02, 0.35, 0.55])
    p = metrics.market_probs(bid, ask, "bid")
    assert p.sum() == pytest.approx(1.0)
    assert p[0] == pytest.approx(metrics.BID_FLOOR / (metrics.BID_FLOOR + 0.8))


@pytest.mark.parametrize(("price", "cents"), [(0.5, 2), (0.01, 1), (0.99, 1), (0.1, 1), (0.3, 2)])
def test_kalshi_taker_fee(price, cents):
    assert metrics.fee(price) == pytest.approx(cents / 100)


def test_taker_pnl_buys_yes_when_cheap_and_no_when_rich():
    # Bucket 0 is underpriced (p 0.6 vs ask 0.40) and wins; bucket 1 overpriced (p 0.1 vs bid 0.5).
    pnl, n = metrics.taker_pnl(
        p=np.array([0.6, 0.1]),
        bid=np.array([0.35, 0.50]),
        ask=np.array([0.40, 0.55]),
        yes=np.array([1.0, 0.0]),
    )
    assert n == 2
    assert pnl == pytest.approx((1 - 0.40 - 0.02) + (0.50 - 0 - 0.02))


def test_taker_pnl_trades_nothing_inside_fee_and_margin():
    pnl, n = metrics.taker_pnl(np.array([0.42]), np.array([0.38]), np.array([0.40]), np.array([1.0]))
    assert (pnl, n) == (0.0, 0)


def test_fmt():
    assert metrics.fmt({"diff": 0.1334, "ci": [0.0894, 0.178]}) == "+0.133 [+0.089, +0.178]"
