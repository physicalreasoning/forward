import numpy as np
from scipy.stats import norm

from forward.wm import scores


def _crps_brute(x, y):
    k = len(x)
    return np.abs(x - y).mean() - np.abs(x[:, None] - x[None, :]).sum() / (2 * k * (k - 1))


def test_fair_crps_matches_brute_force():
    rng = np.random.default_rng(1)
    for k in (2, 5, 50):
        x, y = rng.normal(size=k), rng.normal()
        assert np.isclose(scores.crps(x, y), _crps_brute(x, y))


def test_crps_vectorised_over_hours():
    rng = np.random.default_rng(2)
    x, y = rng.normal(size=(20, 7)), rng.normal(size=7)
    want = [_crps_brute(x[:, j], y[j]) for j in range(7)]
    assert np.allclose(scores.crps(x, y), want)


def test_crps_approaches_gaussian_closed_form():
    # CRPS of N(0, 1) at y (Gneiting and Raftery 2007): y(2 Phi(y) - 1) + 2 phi(y) - 1/sqrt(pi).
    x = np.random.default_rng(3).normal(size=20000)
    y = 0.7
    exact = y * (2 * norm.cdf(y) - 1) + 2 * norm.pdf(y) - 1 / np.sqrt(np.pi)
    assert abs(scores.crps(x, y) - exact) < 0.01


def test_energy_reduces_to_crps_in_one_dimension():
    rng = np.random.default_rng(4)
    x, y = rng.normal(size=(30, 1)), rng.normal(size=1)
    assert np.isclose(scores.energy(x, y), scores.crps(x[:, 0], y[0]))


def test_energy_batched_matches_loop():
    rng = np.random.default_rng(5)
    x, y = rng.normal(size=(10, 4, 6)), rng.normal(size=(4, 6))
    want = [scores.energy(x[:, i], y[i]) for i in range(4)]
    assert np.allclose(scores.energy(x, y), want)


def test_variogram_prefers_correct_correlation():
    # Truth moves all hours together; samples with the same marginals but independent hours
    # must score worse on the variogram score than perfectly correlated samples.
    rng = np.random.default_rng(6)
    d, k, n = 8, 50, 200
    corr, ind = [], []
    for _ in range(n):
        y = np.full(d, rng.normal())
        corr.append(scores.variogram(np.repeat(rng.normal(size=(k, 1)), d, axis=1), y))
        ind.append(scores.variogram(rng.normal(size=(k, d)), y))
    assert np.mean(corr) < np.mean(ind)


def test_tw_crps_ignores_the_body():
    # Below the threshold every forecast is equal, so the score is zero when truth is below too.
    x = np.array([1.0, 2.0, 3.0])
    assert scores.tw_crps(x, 2.5, t=10.0) == 0.0


def test_pit_is_uniform_when_calibrated():
    rng = np.random.default_rng(7)
    x, y = rng.normal(size=(19, 5000)), rng.normal(size=5000)
    h, _ = np.histogram(scores.pit(x, y, rng), bins=10, range=(0, 1))
    assert h.min() > 400 and h.max() < 600
