"""WM-2 prototype baselines: K joint sample futures of the rain-rate field on each tile.

Every function takes (init_time, tiles, inputs) and reads only through the shim
(forward/wm2/access.py), so it can serve as an entry's `predict`. It returns float32
[K, tile, len(LEADS), TARGET, TARGET] rain rate in mm/h on the scored central box. Randomness is
seeded by the init time.

- `persistence`: the latest frame before the init (init - 10 min; up to 30 min old if frames
  are missing), the same in every sample. Eulerian persistence, the floor every nowcast must
  beat.
- `climatology`: the observed sequences that followed the same time of day in the past four
  years at offsets of up to two days (4 x 5 = 20 analogues; offsets of three days are a reserve
  for missing frames). Joint by construction: each sample is one real sequence of fields.
- `advection`: Lagrangian persistence (Germann and Zawadzki 2002): the latest frame moved along
  one motion vector per tile, estimated by phase correlation (Kuglin and Hines 1975) between the
  last three frames, with the vector perturbed per sample (as STEPS perturbs motion, Bowler et
  al. 2006) so the samples spread with lead time. Rain advected in from outside the context box
  is unknown and set to zero.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import ndimage

from . import mrms

K = 20
LEADS = (10, 20, 30, 60, 90, 120, 180, 240, 300, 360)  # minutes after the init
CADENCE = pd.Timedelta(minutes=10)
YEARS = 4
OFFSETS = (0, -1, 1, -2, 2, -3, 3)  # days; the last two are the reserve
WET = 0.1  # mm/h: below this a pixel counts as dry when estimating motion
SIGMA0, SIGMA1 = 0.3, 0.3  # motion perturbation per 10 min: SIGMA0 px + SIGMA1 x |v|, fixed a priori


def lead_times(init) -> list[pd.Timestamp]:
    t = pd.Timestamp(init).tz_localize(None) if pd.Timestamp(init).tzinfo else pd.Timestamp(init)
    return [t + pd.Timedelta(minutes=m) for m in LEADS]


def _naive(init) -> pd.Timestamp:
    t = pd.Timestamp(init)
    return t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t


def _seed(init) -> int:
    return int(_naive(init).value // 10**9) % (2**32)


def _target(x: np.ndarray) -> np.ndarray:
    a = (mrms.CONTEXT - mrms.TARGET) // 2
    return x[..., a : a + mrms.TARGET, a : a + mrms.TARGET]


def _latest(init, inputs, back: int = 3) -> tuple[np.ndarray, pd.Timestamp | None]:
    """The most recent frame before the init with every tile captured, at most `back` steps old."""
    t0 = _naive(init)
    times = [t0 - CADENCE * i for i in range(1, back + 1)]
    x = inputs.radar(times)
    for i, t in enumerate(times):
        if not np.isnan(x[i]).all(axis=(-1, -2)).any():
            return x[i], t
    return np.full_like(x[0], np.nan), None


def persistence(init_time, tiles, inputs) -> np.ndarray:
    x, _ = _latest(init_time, inputs)
    f = _target(x)  # [tile, T, T]
    return np.broadcast_to(f[None, :, None], (K, len(tiles), len(LEADS), *f.shape[-2:])).astype(np.float32)


def climatology(init_time, tiles, inputs) -> np.ndarray:
    t0 = _naive(init_time)
    out = np.full((K, len(tiles), len(LEADS), mrms.TARGET, mrms.TARGET), np.nan, np.float32)
    k = 0
    for off in OFFSETS:
        for y in range(1, YEARS + 1):
            if k == K:
                return out
            try:
                a = t0.replace(year=t0.year - y) + pd.Timedelta(days=off)
            except ValueError:  # 29 February
                continue
            x = inputs.radar([a + pd.Timedelta(minutes=m) for m in LEADS])
            if np.isnan(x).all(axis=(-1, -2)).any():  # a frame not in the archive: use a reserve
                continue
            out[k] = np.moveaxis(np.nan_to_num(_target(x), nan=0.0), 0, 1)  # gaps in coverage: dry
            k += 1
    return out


def phase_shift(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(dy, dx) in pixels such that b(r) ~ a(r - d), by phase correlation with a parabolic peak."""
    wy = np.hanning(a.shape[0])[:, None] * np.hanning(a.shape[1])[None, :]
    fa, fb = np.fft.rfft2(a * wy), np.fft.rfft2(b * wy)
    r = fb * np.conj(fa)
    c = np.fft.irfft2(r / np.maximum(np.abs(r), 1e-12), s=a.shape)
    i, j = np.unravel_index(np.argmax(c), c.shape)
    d = []
    for p, n, line in ((i, a.shape[0], c[:, j]), (j, a.shape[1], c[i, :])):
        lo, mid, hi = line[(p - 1) % n], line[p], line[(p + 1) % n]
        den = lo - 2 * mid + hi
        frac = 0.5 * (lo - hi) / den if den != 0 else 0.0
        q = p + frac
        d.append(q - n if q > n / 2 else q)
    return np.array(d)


def motion(frames: np.ndarray) -> np.ndarray:
    """Per-tile motion (dy, dx) in pixels per CADENCE from frames [time, tile, C, C], oldest first.

    Fields are compared as log rain rate, as optical-flow nowcasts do, so heavy cores do not
    dominate; a tile with too little rain in any frame gets zero motion.
    """
    n_t, n_tile = frames.shape[:2]
    v = np.zeros((n_tile, 2))
    for s in range(n_tile):
        f = np.nan_to_num(frames[:, s], nan=0.0)
        if ((f > WET).mean(axis=(-1, -2)) < 0.005).any():
            continue
        g = np.log1p(np.where(f > WET, f, 0.0))
        v[s] = np.mean([phase_shift(g[i], g[i + 1]) for i in range(n_t - 1)], axis=0)
    return v


def advection(init_time, tiles, inputs) -> np.ndarray:
    t0 = _naive(init_time)
    frames = inputs.radar([t0 - CADENCE * i for i in (3, 2, 1)])
    out = np.full((K, len(tiles), len(LEADS), mrms.TARGET, mrms.TARGET), np.nan, np.float32)
    if np.isnan(frames[-1]).all():
        return out
    v = motion(frames)
    last = np.nan_to_num(frames[-1], nan=0.0)
    rng = np.random.default_rng(_seed(init_time))
    steps = np.array(LEADS) / (CADENCE / pd.Timedelta(minutes=1))
    for s in range(len(tiles)):
        sig = SIGMA0 + SIGMA1 * np.hypot(*v[s])
        vk = v[s][None, :] + rng.normal(0.0, sig, size=(K, 2))
        vk[0] = v[s]  # the unperturbed control
        for k in range(K):
            for li, n in enumerate(steps):
                moved = ndimage.shift(last[s], vk[k] * n, order=1, mode="constant", cval=0.0)
                out[k, s, li] = _target(moved)
    return np.clip(out, 0.0, None)


ENTRIES = {"persistence": persistence, "climatology": climatology, "advection": advection}


def needed_times(inits) -> list[pd.Timestamp]:
    """Every frame the baselines and the truth need for these inits (for the capture)."""
    out = set()
    for t in inits:
        t0 = _naive(t)
        out.update(t0 - CADENCE * i for i in (1, 2, 3))
        out.update(lead_times(t0))
        for off in OFFSETS:
            for y in range(1, YEARS + 1):
                try:
                    a = t0.replace(year=t0.year - y) + pd.Timedelta(days=off)
                except ValueError:
                    continue
                out.update(a + pd.Timedelta(minutes=m) for m in LEADS)
    return sorted(out)
