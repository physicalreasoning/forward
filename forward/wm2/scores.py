"""Scores for sampled rain-rate fields: forecasts [K, ..., H, W] against truth [..., H, W].

- fair CRPS per pixel after average pooling over s x s pixels (Ferro 2014 for the fair form; the
  pooled form is the one Ravuri et al. 2021 used for DGMR, so a forecast that puts rain a few
  pixels off is not scored as if it had missed it entirely). Reuses forward/wm/scores.py.
- fair energy score of the whole pooled field (Gneiting and Raftery 2007), the multivariate
  score that rewards getting the joint pattern right.
- fractions skill score (Roberts and Lean 2008) of the ensemble's neighbourhood exceedance
  probability (as in Schwartz et al. 2010) at a threshold and a neighbourhood size, accumulated
  over cases before the ratio. Not a proper score: reported, never ranked on.

Every function takes a boolean `ok` mask [..., H, W] of the cells scored (truth and every
entry's forecast finite); cells outside it never count.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from ..wm import scores as wm_scores


def pool(x: np.ndarray, s: int) -> np.ndarray:
    """Average over s x s blocks of the last two axes (which must divide by s)."""
    if s == 1:
        return x
    h, w = x.shape[-2:]
    return x.reshape(*x.shape[:-2], h // s, s, w // s, s).mean(axis=(-3, -1))


def pooled_crps(fc: np.ndarray, y: np.ndarray, ok: np.ndarray, s: int) -> np.ndarray:
    """Fair CRPS per pooled cell [..., H/s, W/s]; a block with any cell outside `ok` is NaN."""
    f = np.where(ok, fc, 0.0)
    yy = np.where(ok, y, 0.0)
    good = pool(ok.astype(float), s) == 1.0
    c = wm_scores.crps(pool(f, s), pool(yy, s))
    return np.where(good, c, np.nan)


def pooled_energy(fc: np.ndarray, y: np.ndarray, ok: np.ndarray, s: int) -> np.ndarray:
    """Fair energy score of each whole pooled field: fc [K, N, H, W], y [N, H, W] -> [N].
    A field with any cell outside `ok` is NaN (the same rows for every entry)."""
    k, n = fc.shape[:2]
    pf = pool(np.where(ok, fc, 0.0), s).reshape(k, n, -1)
    py = pool(np.where(ok, y, 0.0), s).reshape(n, -1)
    es = wm_scores.energy(pf, py)
    return np.where(ok.reshape(n, -1).all(axis=-1), es, np.nan)


def fractions(p: np.ndarray, n: int) -> np.ndarray:
    """Neighbourhood mean over n x n pixels of the last two axes (zero outside the field)."""
    if n == 1:
        return p
    size = (1,) * (p.ndim - 2) + (n, n)
    return ndimage.uniform_filter(p.astype(float), size=size, mode="constant", cval=0.0)


def fss_terms(fc: np.ndarray, y: np.ndarray, ok: np.ndarray, threshold: float, n: int) -> tuple[float, float]:
    """(sum of squared differences, reference sum) over the scored cells; FSS = 1 - a / b."""
    pf = fractions((np.where(ok, fc, 0.0) >= threshold).mean(axis=0), n)
    po = fractions(np.where(ok, y, 0.0) >= threshold, n)
    m = ok
    return float(((pf - po) ** 2)[m].sum()), float((pf**2 + po**2)[m].sum())


def fss(terms: list[tuple[float, float]]) -> float:
    a = sum(t[0] for t in terms)
    b = sum(t[1] for t in terms)
    return float("nan") if b == 0 else 1.0 - a / b
