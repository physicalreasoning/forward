"""Proper scores for sampled futures: what a world-model entry is scored with.

An entry submits K sample trajectories; every score here takes them as an array whose first
axis is the sample. The estimators are the standard unbiased ("fair") ones, so an entry with
few samples is not penalised for small K alone:

- fair CRPS for one quantity (Ferro 2014; Zamo and Naveau 2018), proper for the predictive
  distribution the samples are drawn from;
- energy score for a whole trajectory (Gneiting and Raftery 2007; fair form as in
  Ferro 2014), which rewards getting the joint evolution right, not only each hour;
- variogram score of order p (Scheuerer and Hamill 2015), sensitive to the correlation between
  hours that the energy score is known to miss;
- threshold-weighted CRPS (Gneiting and Ranjan 2011; Allen et al. 2023 for the sample form),
  for claims about tails, with the threshold fixed before a round;
- randomised PIT of the truth among the samples, for calibration.

Lower is better for every score. Missing truth is never scored: callers drop the row for every
entry alike.
"""

from __future__ import annotations

import numpy as np


def _pairwise_mean_abs(x: np.ndarray) -> np.ndarray:
    """Mean |x_i - x_j| over i != j along axis 0 (fair form), via sorting: O(K log K)."""
    k = x.shape[0]
    s = np.sort(x, axis=0)
    w = (2 * np.arange(1, k + 1) - k - 1).reshape((k,) + (1,) * (x.ndim - 1))
    return 2 * (w * s).sum(axis=0) / (k * (k - 1))


def crps(samples, y) -> np.ndarray:
    """Fair CRPS of samples[K, ...] against y[...], elementwise over the trailing axes."""
    x = np.asarray(samples, dtype=float)
    y = np.asarray(y, dtype=float)
    return np.abs(x - y).mean(axis=0) - 0.5 * _pairwise_mean_abs(x)


def energy(samples, y) -> float | np.ndarray:
    """Fair energy score of samples[K, D] against y[D] (or batched: samples[K, N, D], y[N, D])."""
    x = np.asarray(samples, dtype=float)
    y = np.asarray(y, dtype=float)
    k = x.shape[0]
    d1 = np.linalg.norm(x - y, axis=-1).mean(axis=0)
    diff = x[:, None] - x[None, :]
    d2 = np.linalg.norm(diff, axis=-1).sum(axis=(0, 1)) / (k * (k - 1))
    return d1 - 0.5 * d2


def variogram(samples, y, p: float = 0.5, weights=None) -> float | np.ndarray:
    """Variogram score of order p for samples[K, D] against y[D] (batched as energy).

    Compares |y_i - y_j|^p with its expectation under the samples for every pair of hours.
    Not fair in K, so a round fixes K for every entry.
    """
    x = np.asarray(samples, dtype=float)
    y = np.asarray(y, dtype=float)
    obs = np.abs(y[..., :, None] - y[..., None, :]) ** p
    exp = (np.abs(x[..., :, None] - x[..., None, :]) ** p).mean(axis=0)
    w = 1.0 if weights is None else np.asarray(weights, dtype=float)
    return (w * (obs - exp) ** 2).sum(axis=(-1, -2))


def tw_crps(samples, y, t: float, upper: bool = True) -> np.ndarray:
    """Threshold-weighted CRPS with the chaining function max(x, t) (or min for lower tails)."""
    f = np.maximum if upper else np.minimum
    return crps(f(np.asarray(samples, dtype=float), t), f(np.asarray(y, dtype=float), t))


def pit(samples, y, rng=None) -> np.ndarray:
    """Randomised PIT of y among samples[K, ...]: uniform on [0, 1] if calibrated."""
    x = np.asarray(samples, dtype=float)
    y = np.asarray(y, dtype=float)
    rng = np.random.default_rng(0) if rng is None else rng
    k = x.shape[0]
    below = (x < y).sum(axis=0)
    ties = (x == y).sum(axis=0)
    u = rng.uniform(size=np.shape(below))
    return (below + u * (ties + 1)) / (k + 1)
