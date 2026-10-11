"""The mandatory columns. Every entry is reported on all of them; none can be dropped.

Distributions are Gaussian (mu, sigma) on the latent high, discretised to the integer CLI value:
P(k) = Phi((k + 0.5 - mu) / sigma) - Phi((k - 0.5 - mu) / sigma). Ladders use Kalshi's bucket
edges on the same latent scale, so an entry's ladder probabilities are its own integer
probabilities summed over the bucket.

1. proper scores: log score and ranked probability score (Epstein 1969) on the integer value
2. calibration: randomised PIT (Czado, Gneiting and Held 2009) and central-interval coverage
3. skill against copy (persistence) and climatology, the trivial solutions
4. skill against the bid-priced market on Kalshi ladders (isotherm FINDINGS §41)
5. decision value: a fixed taker policy's paper P&L after Kalshi fees, with and without 1c slippage
6. variance split by month, so a lucky regime is not read as skill (Market-1T, arXiv 2610.09048)

Confidence intervals resample whole dates (a date-block bootstrap), because every station on a
date shares the same weather pattern and the same model run.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm

EPS = 1e-6
BID_FLOOR = 0.005  # a bucket with no bid is priced at half a cent, as in isotherm §41


def cdf(x, mu, sigma):
    return norm.cdf((np.asarray(x, float) - mu) / sigma)


def pmf_at(k, mu, sigma):
    """P(CLI high == k) for integer k."""
    return np.clip(cdf(k + 0.5, mu, sigma) - cdf(k - 0.5, mu, sigma), EPS, 1.0)


def log_score(y, mu, sigma):
    """Log score of the realised integer high (higher is better)."""
    return np.log(pmf_at(np.asarray(y, float), mu, sigma))


def rps(y, mu, sigma, lo=-40, hi=130):
    """Ranked probability score over the integer grid (lower is better); CRPS's discrete form."""
    k = np.arange(lo, hi + 1)
    F = cdf(k[None, :] + 0.5, np.asarray(mu, float)[:, None], np.asarray(sigma, float)[:, None])
    O = (k[None, :] >= np.asarray(y, float)[:, None]).astype(float)
    return ((F - O) ** 2).sum(1)


def pit(y, mu, sigma, rng=None):
    """Randomised PIT for an integer outcome: uniform between F(y - 1) and F(y)."""
    rng = rng or np.random.default_rng(0)
    y = np.asarray(y, float)
    lo, hi = cdf(y - 0.5, mu, sigma), cdf(y + 0.5, mu, sigma)
    return lo + rng.uniform(size=len(y)) * (hi - lo)


def calibration(u) -> dict:
    """PIT summaries: coverage of the central 50/80/90% intervals and a 10-bin flatness error."""
    u = np.asarray(u)
    cov = {str(c): float(np.mean(np.abs(u - 0.5) <= c / 200)) for c in (50, 80, 90)}
    hist = np.histogram(u, bins=10, range=(0, 1))[0] / max(len(u), 1)
    return {"coverage": cov, "pit_flatness_error": float(np.abs(hist - 0.1).sum() / 2)}


def block_ci(dates, vals, n=2000, seed=0):
    """95% CI of the mean of `vals`, resampling whole dates."""
    ud, inv = np.unique(np.asarray(dates), return_inverse=True)
    sums = np.bincount(inv, weights=np.asarray(vals, float), minlength=len(ud))
    cnt = np.bincount(inv, minlength=len(ud))
    picks = np.random.default_rng(seed).integers(0, len(ud), (n, len(ud)))
    stats = sums[picks].sum(1) / cnt[picks].sum(1)
    return [float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))]


def diff(dates, a, b) -> dict:
    d = np.asarray(a, float) - np.asarray(b, float)
    return {"diff": float(d.mean()), "ci": block_ci(dates, d), "n": len(d)}


def month_share(months, vals) -> float:
    """Share of the variance of per-row values explained by the calendar month."""
    v = np.asarray(vals, float)
    m = np.asarray(months)
    tot = ((v - v.mean()) ** 2).sum()
    if tot == 0:
        return 0.0
    between = sum(((v[m == k].mean() - v.mean()) ** 2) * (m == k).sum() for k in np.unique(m))
    return float(between / tot)


# Ladders -----------------------------------------------------------------------------------


def bucket_probs(edges, mu, sigma):
    """Probability of each [lo, hi) bucket on the latent scale."""
    lo = np.array([e[0] for e in edges], float)
    hi = np.array([e[1] for e in edges], float)
    p = cdf(hi, mu, sigma) - cdf(lo, mu, sigma)
    return np.clip(p, EPS, 1.0)


def market_probs(bid, ask, kind):
    """The market's ladder distribution. 'bid': renormalised bids (empty bids at BID_FLOOR);
    'mid': renormalised mid-prices. Bid-priced is the stricter baseline (§41)."""
    bid = np.where(np.isfinite(bid) & (bid > 0), bid, BID_FLOOR)
    if kind == "bid":
        p = bid
    else:
        a = np.where(np.isfinite(ask), ask, 1.0)
        p = (bid + a) / 2
    p = np.clip(p, EPS, None)
    return p / p.sum()


def fee(price):
    """Kalshi taker fee per contract, in dollars: ceil(7 p (1 - p)) cents."""
    return math.ceil(round(7 * price * (1 - price), 6)) / 100


def taker_pnl(p, bid, ask, yes, margin=0.01, slip=0.0):
    """One contract per bucket where the entry's probability clears the quote by fee + margin.

    Buys YES at the ask when p > ask + fee + margin; buys NO at 1 - bid when p < bid - fee - margin.
    Held to settlement. Returns (P&L in dollars, contracts traded).
    """
    pnl, n = 0.0, 0
    for pi, b, a, y in zip(p, bid, ask, yes, strict=True):
        if np.isfinite(a) and 0 < a < 1:
            px = min(a + slip, 0.99)
            if pi > px + fee(px) + margin:
                pnl += y - px - fee(px)
                n += 1
                continue
        if np.isfinite(b) and 0 < b < 1:
            px = max(b - slip, 0.01)  # selling YES at the bid = buying NO at 1 - bid
            if pi < px - fee(px) - margin:
                pnl += px - y - fee(px)
                n += 1
    return pnl, n
