"""Task 3 entries: world models of how the book reacts to a passive limit order.

Each entry is fit on rows whose labels resolved before the cutoff and predicts, for an action
at t0, the probability that the whole order fills within the horizon and the expected mid move
in the 5 minutes after a fill (cents, positive in the order's favour). Inputs are what was known
at t0: the book and the 30 minutes of flow before it.

- base-rate: the training fill frequency by distance to the best bid and size; the mean move by
  distance. Knows nothing about the market or the moment.
- copy: did anything trade at or through our price in the last 30 minutes? The training fill
  frequency given that bit; no move (the mid stays where it is, a martingale). The analogue of
  copying yesterday's high: it assumes the near future repeats the near past.
- queue: a queue-depletion model after Cont, Stoikov and Talreja (2010). Executions that reach
  our price arrive as a Poisson process (rate mu, mean size m) and each unit resting ahead of us
  cancels at rate theta, so the time for the queue ahead and then our own size to clear is a sum
  of exponentials with rates mu + theta * j (ahead) and mu (ours), read as a gamma with the same
  mean and variance. mu, m and theta come from the market's own last 30 minutes, shrunk to the
  training averages; mu's uncertainty is integrated out. No move: the queue model says nothing
  about information.
- queue-cal: the queue model's log-odds recalibrated on the training days (two parameters).
- logistic: an L2-penalised logistic regression on book and flow features for fills, and a
  ridge regression on the same features for the move, fit on earlier days.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import digamma, expit, polygamma
from scipy.stats import gamma

from . import fills

EPS = 1e-6
LOOKBACK_S = fills.LOOKBACK_MS / 1000
PRIOR_S = 1800.0  # the training averages count as this much of the market's own history
PRIOR_TRADES = 5.0


def log_score(y, p):
    """Log score of a binary outcome (higher is better)."""
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    return y * np.log(p) + (1 - y) * np.log(1 - p)


def brier(y, p):
    return (np.asarray(p, float) - np.asarray(y, float)) ** 2


def reliability(y, p, bins=10) -> dict:
    """Mean forecast and observed frequency in equal-width bins, and the expected calibration
    error (bin-weighted mean absolute gap)."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    b = np.minimum((p * bins).astype(int), bins - 1)
    table, ece = [], 0.0
    for k in range(bins):
        m = b == k
        if m.any():
            table.append({"bin": k, "n": int(m.sum()), "p": float(p[m].mean()), "freq": float(y[m].mean())})
            ece += m.sum() / len(y) * abs(p[m].mean() - y[m].mean())
    return {"ece": float(ece), "bins": table}


class BaseRate:
    name = "base-rate"

    def fit(self, d: pd.DataFrame):
        g = d.groupby(["level", "size"])["y"]
        self.p = ((g.sum() + 1) / (g.count() + 2)).to_dict()
        self.p0 = float((d["y"].sum() + 1) / (len(d) + 2))
        f = d[d["move"].notna()].groupby("level")["move"]
        self.mv = (f.mean() * f.count() / (f.count() + 20)).to_dict()
        return self

    def predict(self, d):
        return np.array([self.p.get(k, self.p0) for k in zip(d["level"], d["size"], strict=True)])

    def move(self, d):
        return d["level"].map(self.mv).fillna(0.0).to_numpy(float)


class Copy:
    name = "copy"

    def fit(self, d):
        g = d.groupby("crossed")["y"]
        self.p = ((g.sum() + 1) / (g.count() + 2)).to_dict()
        return self

    def predict(self, d):
        return d["crossed"].map(self.p).fillna(0.5).to_numpy(float)

    def move(self, d):
        return np.zeros(len(d))


class Queue:
    """Cont, Stoikov and Talreja (2010): the queue ahead of us as a death process.

    Executions that reach our price (at it, or through it) arrive as a Poisson process with
    rate mu and mean size m; each unit ahead of us cancels at rate theta. The time to fill is
    T = sum_j Exp(mu + theta j) over the units ahead, plus Exp(mu) for each of our own units,
    read as a gamma with T's mean and variance (exact when nobody is ahead). mu is uncertain:
    a gamma posterior from the market's last 30 minutes (n executions in LOOKBACK_S) and a
    prior worth PRIOR_S at the training rate for that distance to the best bid; the fill
    probability is averaged over the posterior.
    """

    name = "queue"
    nodes = (np.arange(16) + 0.5) / 16  # posterior quantiles of mu

    def __init__(self, h_ms: int):
        self.h = h_ms / 1000

    def fit(self, d):
        g = d.groupby("level")
        self.mu = (g["n_exec_at"].sum() / (g.size() * LOOKBACK_S)).clip(lower=1e-7).to_dict()
        self.mu0 = max(d["n_exec_at"].sum() / (len(d) * LOOKBACK_S), 1e-7)
        n, v = d["n_exec"].to_numpy(float), d["v_exec"].to_numpy(float)
        self.m = max(v.sum() / max(n.sum(), 1), 1e-3)
        depth = d["depth"].to_numpy(float)
        self.theta = max(d["v_cancel"].sum() / max((depth * LOOKBACK_S).sum(), 1e-9), 1e-9)
        return self

    def rates(self, d):
        n, v = d["n_exec_at"].to_numpy(float), d["v_exec_at"].to_numpy(float)
        prior = d["level"].map(self.mu).fillna(self.mu0).to_numpy(float)
        shape, rate = n + prior * PRIOR_S, LOOKBACK_S + PRIOR_S
        mu = gamma.ppf(self.nodes[None, :], a=shape[:, None], scale=1 / rate)
        m = (v + self.m * PRIOR_TRADES) / (n + PRIOR_TRADES)
        depth = np.maximum(d["depth"].to_numpy(float), 1.0)
        theta = (d["v_cancel"].to_numpy(float) + self.theta * depth * PRIOR_S) / (
            depth * (LOOKBACK_S + PRIOR_S)
        )
        return np.maximum(mu, 1e-9), m, np.maximum(theta, 1e-9)

    def predict(self, d):
        mu, m, theta = self.rates(d)
        x = (d["queue"].to_numpy(float) / m)[:, None]  # units ahead at our price
        u = (d["size"].to_numpy(float) / m)[:, None]  # our own units, which never cancel
        th = theta[:, None]
        c = mu / th
        s1 = (digamma(x + 1 + c) - digamma(1 + c)) / th  # sum of 1 / (mu + theta j), j = 1..x
        s2 = (polygamma(1, 1 + c) - polygamma(1, x + 1 + c)) / th**2
        mean = s1 + u / mu
        var = np.maximum(s2 + u / mu**2, 1e-12)
        p = gamma.cdf(self.h, a=mean**2 / var, scale=var / mean).mean(1)
        return np.clip(p, EPS, 1 - EPS)

    def move(self, d):
        return np.zeros(len(d))


class QueueCal(Queue):
    """The queue model's log-odds, recalibrated on the training days (Platt 1999): a + b * logit(p).
    Separates whether the queue model ranks orders well from whether its probabilities are right,
    as task 1 does with raw and EMOS-calibrated weather models."""

    name = "queue-cal"

    def fit(self, d):
        super().fit(d)
        z = _logit(super().predict(d))
        y = d["y"].to_numpy(float)

        def loss(w):
            s = w[0] + w[1] * z
            return np.sum(np.logaddexp(0, s) - y * s), np.array(
                [np.sum(expit(s) - y), np.sum((expit(s) - y) * z)]
            )

        self.ab = minimize(loss, np.array([0.0, 1.0]), jac=True, method="L-BFGS-B").x
        return self

    def predict(self, d):
        z = _logit(super().predict(d))
        return np.clip(expit(self.ab[0] + self.ab[1] * z), EPS, 1 - EPS)


def _logit(p):
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def features(d: pd.DataFrame) -> np.ndarray:
    lv = d["level"].to_numpy()
    cols = [
        *(lv == k for k in fills.LEVELS[1:]),  # distance to best, one-hot (first level dropped)
        np.log1p(d["size"]),
        np.log1p(d["queue"]),
        np.log1p(d["better"]),
        np.log1p(d["depth"]),
        np.log1p(d["depth_other"]),
        d["spread"],
        np.abs(d["mid"] - 50) / 50,
        np.log1p(d["n_exec"]),
        np.log1p(d["v_exec"]),
        np.log1p(d["v_cancel"]),
        np.log1p(d["n_exec_all"]),
        np.log1p(d["n_exec_at"]),
        np.log1p(d["v_exec_at"]),
        d["crossed"],
        d["side"],
        d["series"].isin(fills.COMMODITIES),
    ]
    return np.column_stack([np.asarray(c, float) for c in cols])


class Logistic:
    name = "logistic"
    l2 = 1.0  # on standardised features
    ridge = 10.0

    def fit(self, d):
        X = features(d)
        self.mu_x, self.sd_x = X.mean(0), X.std(0) + 1e-9
        Z = np.column_stack([np.ones(len(X)), (X - self.mu_x) / self.sd_x])
        y = d["y"].to_numpy(float)

        def loss(w):
            z = Z @ w
            nll = np.sum(np.logaddexp(0, z) - y * z) + 0.5 * self.l2 * w[1:] @ w[1:]
            g = Z.T @ (expit(z) - y)
            g[1:] += self.l2 * w[1:]
            return nll, g

        self.w = minimize(loss, np.zeros(Z.shape[1]), jac=True, method="L-BFGS-B").x
        f = d["move"].notna().to_numpy()
        if f.sum() > Z.shape[1]:
            A, b = Z[f], d["move"].to_numpy(float)[f]
            reg = self.ridge * np.eye(Z.shape[1])
            reg[0, 0] = 0
            self.beta = np.linalg.solve(A.T @ A + reg, A.T @ b)
        else:
            self.beta = np.zeros(Z.shape[1])
        return self

    def _z(self, d):
        X = features(d)
        return np.column_stack([np.ones(len(X)), (X - self.mu_x) / self.sd_x])

    def predict(self, d):
        return np.clip(expit(self._z(d) @ self.w), EPS, 1 - EPS)

    def move(self, d):
        return self._z(d) @ self.beta


def entries(h: str):
    return [BaseRate(), Copy(), Queue(fills.HORIZONS[h]), QueueCal(fills.HORIZONS[h]), Logistic()]
