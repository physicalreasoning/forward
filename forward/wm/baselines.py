"""The WM-1 baselines: K = 50 joint trajectories per station, hours 1 to 168 after the read.

Every function here takes (init_time, stations, inputs) and reads only through the shim
(forward/wm/access.py), so it can serve as an entry's `predict` (entries/wm1/). Randomness is
seeded by the init date, so a forecast is reproducible from the code and the inputs.

- `climatology`: the observed trajectories that followed the same time of day and year in the
  past ten years, at offsets of up to two days (5 offsets x 10 years = 50 analogues). Joint by
  construction: each sample is one real week.
- `persistence`: today's anomaly from the hourly climatology (the diurnal cycle), carried
  forward, plus the error that carrying forward made in the same 50 analogue weeks. The
  persistence-with-bootstrapped-residuals baseline of docs/WORLD_MODEL_TRACK.md.
- `raw`: 50 members drawn from the captured multi-model ensemble, equal weight per model, the
  same members at every station, so each sample is one member's spatially and temporally
  coherent trajectory.
- `emos_ecc`: the same 50 members calibrated hour by hour with EMOS (Gneiting et al. 2005), fit
  by minimum CRPS on every past capture whose leads had verified before the init, then
  reordered with ensemble copula coupling (ECC-Q, Schefzik, Thorarinsdottir and Gneiting 2013),
  which keeps the raw ensemble's rank structure across hours and stations.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import norm

K = 50
LEADS = 168
YEARS = 10
OFFSETS = 2  # analogue offsets in days, each side; one more side is a reserve for missing weeks
MAX_GAP = 3  # hours of missing truth an analogue trajectory may have, filled linearly inside it
VARIABLES = ["tmpf"]
H = pd.Timedelta(hours=1)


def lead_times(init) -> pd.DatetimeIndex:
    return pd.date_range(pd.Timestamp(init) + H, periods=LEADS, freq="h")


def _seed(init) -> int:
    return int(pd.Timestamp(init).strftime("%Y%m%d"))


def _same_time(t: pd.Timestamp, year: int) -> pd.Timestamp:
    try:
        return t.replace(year=year)
    except ValueError:  # 29 February
        return t.replace(year=year, day=28)


def analog_starts(init, years: int = YEARS, offsets: int = OFFSETS + 1) -> list[pd.Timestamp]:
    """Analogue start times, nearest offsets first, then most recent years first."""
    init = pd.Timestamp(init)
    out = []
    for o in sorted(range(-offsets, offsets + 1), key=lambda o: (abs(o), o)):
        for y in range(init.year - 1, init.year - years - 1, -1):
            out.append(_same_time(init, y) + pd.Timedelta(days=o))
    return out


def _window(s: pd.Series, start: pd.Timestamp) -> np.ndarray | None:
    """Truth at hours start+1 .. start+LEADS, with gaps of at most MAX_GAP hours filled inside."""
    v = s.reindex(pd.date_range(start + H, periods=LEADS, freq="h"))
    miss = v.isna().to_numpy()
    if miss[0] or miss[-1]:
        return None
    if miss.any():
        runs = np.diff(np.flatnonzero(np.diff(np.r_[0, miss.astype(int), 0])))[::2]
        if runs.max() > MAX_GAP:
            return None
        v = v.interpolate(limit_area="inside")
    return v.to_numpy(dtype=float)


def _analogues(s: pd.Series, init) -> list[tuple[pd.Timestamp, np.ndarray]]:
    """The first K complete analogue weeks in analog_starts order."""
    out = []
    for t in analog_starts(init):
        w = _window(s, t)
        if w is not None:
            out.append((t, w))
            if len(out) == K:
                break
    return out


def _history(inputs, station: str, init) -> pd.Series:
    start = pd.Timestamp(init) - pd.DateOffset(years=YEARS) - pd.Timedelta(days=OFFSETS + 10)
    return inputs.truth(station, start=start)


def _fill(samples: list[np.ndarray]) -> np.ndarray:
    """K samples from those found, cycling in order if fewer; all NaN if none."""
    if not samples:
        return np.full((K, LEADS), np.nan)
    return np.stack([samples[i % len(samples)] for i in range(K)])


def climatology(init, stations, inputs) -> np.ndarray:
    out = np.full((K, len(stations), LEADS, 1), np.nan)
    for j, st in enumerate(stations):
        out[:, j, :, 0] = _fill([w for _, w in _analogues(_history(inputs, st, init), init)])
    return out


def clim_table(s: pd.Series, half_width: int = 7) -> np.ndarray:
    """Mean truth by (day of year, hour of day), smoothed over +-half_width days: [366, 24]."""
    t = s.dropna()
    g = t.groupby([t.index.dayofyear - 1, t.index.hour]).mean()
    tab = np.full((366, 24), np.nan)
    tab[g.index.get_level_values(0), g.index.get_level_values(1)] = g.to_numpy()
    pad = np.concatenate([tab[-half_width:], tab, tab[:half_width]])
    win = np.lib.stride_tricks.sliding_window_view(pad, 2 * half_width + 1, axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN windows stay NaN
        return np.nanmean(win, axis=-1)


def clim_at(tab: np.ndarray, times) -> np.ndarray:
    times = pd.DatetimeIndex(times)
    return tab[times.dayofyear - 1, times.hour]


def _last_obs(s: pd.Series, init, within: int = 6) -> pd.Timestamp | None:
    for h in range(1, within + 1):
        t = pd.Timestamp(init) - h * H
        if t in s.index and np.isfinite(s[t]):
            return t
    return None


def persistence(init, stations, inputs) -> np.ndarray:
    init = pd.Timestamp(init)
    out = np.full((K, len(stations), LEADS, 1), np.nan)
    target = lead_times(init)
    for j, st in enumerate(stations):
        s = _history(inputs, st, init)
        t0 = _last_obs(s, init)
        if t0 is None:
            continue
        tab = clim_table(s)
        a0 = s[t0] - clim_at(tab, [t0])[0]
        back = init - t0
        errs = []
        for t, w in _analogues(s, init):
            ta = t - back
            if ta not in s.index or not np.isfinite(s[ta]):
                continue
            anom = w - clim_at(tab, pd.date_range(t + H, periods=LEADS, freq="h"))
            errs.append(anom - (s[ta] - clim_at(tab, [ta])[0]))
        out[:, j, :, 0] = clim_at(tab, target) + a0 + _fill(errs)
    return out


# Ensembles --------------------------------------------------------------------------------


def members(frame: pd.DataFrame, init, stations) -> dict[str, np.ndarray]:
    """Each model's members as [member, station, lead] at the init's 168 lead hours (NaN where
    the capture has none)."""
    target = lead_times(init)
    f = frame[frame.station.isin(stations)]
    out = {}
    for model, g in f.groupby("model", sort=True):
        w = g.pivot_table(index=["member", "station"], columns="valid", values="temperature_2m", dropna=False)
        w = w.reindex(columns=target)
        ids = sorted(g.member.unique())
        idx = pd.MultiIndex.from_product([ids, list(stations)], names=["member", "station"])
        out[model] = w.reindex(idx).to_numpy().reshape(len(ids), len(stations), LEADS)
    return out


def coverage(a: np.ndarray) -> int:
    """Leads from the first that are finite for every member and station."""
    ok = np.isfinite(a).all(axis=(0, 1))
    return int(np.argmin(ok)) if not ok.all() else LEADS


def full_models(mem: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """The models reaching the longest coverage among them; a model that stops short (ICON-EPS
    at long leads) is dropped rather than leaving a hole in every sample it would join."""
    cov = {m: coverage(a) for m, a in mem.items()}
    top = max(cov.values(), default=0)
    return {m: a for m, a in mem.items() if cov[m] == top and top > 0}


def allocation(models: list[str], k: int = K) -> dict[str, int]:
    """k slots split as evenly as possible across models, in name order."""
    models = sorted(models)
    base, extra = divmod(k, len(models))
    return {m: base + (i < extra) for i, m in enumerate(models)}


def draw(mem: dict[str, np.ndarray], init, k: int = K) -> np.ndarray:
    """k members, equal weight per model, the same members at every station: [k, station, lead]."""
    mem = full_models(mem)
    if not mem:
        raise ValueError("no model covers any lead")
    rng = np.random.default_rng(_seed(init))
    parts = []
    for m, n in allocation(list(mem), k).items():
        a = mem[m]
        pick = rng.choice(a.shape[0], size=n, replace=n > a.shape[0])
        parts.append(a[np.sort(pick)])
    x = np.concatenate(parts)
    x[:, :, coverage(x) :] = np.nan
    return x


def _latest_capture(inputs) -> pd.Timestamp | None:
    days = inputs.capture_days()
    return days[-1] if days else None


def _capture_members(inputs, day, init, stations) -> dict[str, np.ndarray]:
    """Members of the capture of `day`, re-aligned so lead 1 is the hour after `init`."""
    return members(inputs.ensembles(day), init, stations)


def raw(init, stations, inputs) -> np.ndarray:
    day = _latest_capture(inputs)
    if day is None:
        return np.full((K, len(stations), LEADS, 1), np.nan)
    return draw(_capture_members(inputs, day, init, stations), init)[..., None]


def mixture_stats(mem: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Mean and variance of the equal-weight mixture of the models' ensembles: [station, lead]."""
    means = np.stack([a.mean(axis=0) for a in mem.values()])
    vars_ = np.stack([a.var(axis=0) for a in mem.values()])
    m = means.mean(axis=0)
    return m, (vars_ + (means - m) ** 2).mean(axis=0)


def gaussian_crps(mu, sigma, y):
    """CRPS of N(mu, sigma^2) at y (Gneiting et al. 2005, eq. 5)."""
    z = (y - mu) / sigma
    return sigma * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / np.sqrt(np.pi))


IDENTITY = {"a": None, "b": 1.0, "c": 0.0, "d": 1.0}  # a = None: no intercepts
BLOCK = 24  # hours per lead block with its own EMOS parameters
MIN_PAIRS = 400  # pairs a block needs to be fit; fewer reuse the longest fitted shorter block


def fit_emos(st_idx, m, v, y, n_stations: int) -> dict:
    """Minimum-CRPS EMOS: Y ~ N(a_s + b m, c^2 + d^2 v), one intercept per station."""
    bias = float(np.mean(y - m))
    x0 = np.r_[np.full(n_stations, bias), 1.0, 1.0, 1.0]

    def f(p):
        mu = p[st_idx] + p[n_stations] * m
        sig = np.sqrt(p[n_stations + 1] ** 2 + p[n_stations + 2] ** 2 * v + 1e-6)
        return gaussian_crps(mu, sig, y).mean()

    r = minimize(f, x0, method="L-BFGS-B")
    p = r.x
    return {
        "a": p[:n_stations].tolist(),
        "b": float(p[n_stations]),
        "c": float(p[-2]),
        "d": float(p[-1]),
        "n": len(y),
    }


def training_pairs(inputs, init, stations) -> pd.DataFrame:
    """(station index, lead, mixture mean, variance, truth) for every past capture's lead whose
    truth had been observed before the init."""
    init = pd.Timestamp(init)
    days = inputs.capture_days()
    if not days:
        return pd.DataFrame(columns=["st", "lead", "m", "v", "y"])
    truth = {s: inputs.truth(s, start=days[0].tz_localize("UTC")) for s in stations}
    rows = []
    for day in days:
        t_c = day.tz_localize("UTC") + pd.Timedelta(hours=20)
        if t_c >= init:
            continue
        mem = full_models(_capture_members(inputs, day, t_c, stations))
        if not mem:
            continue
        m, v = mixture_stats(mem)
        valid = lead_times(t_c)
        for j, s in enumerate(stations):
            y = truth[s].reindex(valid).to_numpy(dtype=float)
            ok = np.isfinite(y) & np.isfinite(m[j]) & (valid < init)
            lead = np.flatnonzero(ok) + 1
            rows.append(pd.DataFrame({"st": j, "lead": lead, "m": m[j][ok], "v": v[j][ok], "y": y[ok]}))
    cols = ["st", "lead", "m", "v", "y"]
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=cols)


def fit_blocks(pairs: pd.DataFrame, n_stations: int) -> list[dict]:
    """EMOS parameters per 24 h lead block; blocks with too few pairs reuse the longest fitted
    shorter block, and with none fitted the raw mixture's mean and variance are used."""
    out, last = [], None
    for b in range(LEADS // BLOCK):
        p = pairs[(pairs.lead > b * BLOCK) & (pairs.lead <= (b + 1) * BLOCK)]
        if len(p) >= MIN_PAIRS:
            last = {
                **fit_emos(p.st.to_numpy(int), p.m.to_numpy(), p.v.to_numpy(), p.y.to_numpy(), n_stations),
                "fit": b,
            }
        out.append(last if last is not None else {**IDENTITY, "fit": None, "n": 0})
    return out


def ecc(template: np.ndarray, mu: np.ndarray, sigma: np.ndarray, rng) -> np.ndarray:
    """ECC-Q: the K equidistant quantiles k/(K+1) of N(mu, sigma^2), placed in the rank order of
    the template's members (ties broken at random), elementwise over the trailing axes."""
    k = template.shape[0]
    q = norm.ppf(np.arange(1, k + 1) / (k + 1)).reshape((k,) + (1,) * (template.ndim - 1))
    quant = mu + sigma * q  # sorted along axis 0
    jitter = rng.uniform(size=template.shape) * 1e-6
    ranks = np.argsort(np.argsort(template + jitter, axis=0), axis=0)
    out = np.take_along_axis(quant, ranks, axis=0)
    out[~np.isfinite(template)] = np.nan
    return out


def emos_ecc(init, stations, inputs) -> np.ndarray:
    day = _latest_capture(inputs)
    if day is None:
        return np.full((K, len(stations), LEADS, 1), np.nan)
    mem = full_models(_capture_members(inputs, day, init, stations))
    template = draw(mem, init)
    m, v = mixture_stats(mem)
    params = fit_blocks(training_pairs(inputs, init, stations), len(stations))
    mu, sigma = np.empty_like(m), np.empty_like(m)
    for b, p in enumerate(params):
        sl = slice(b * BLOCK, (b + 1) * BLOCK)
        a = np.zeros((len(stations), 1)) if p["a"] is None else np.asarray(p["a"], dtype=float)[:, None]
        mu[:, sl] = a + p["b"] * m[:, sl]
        sigma[:, sl] = np.sqrt(p["c"] ** 2 + p["d"] ** 2 * v[:, sl] + 1e-6)
    return ecc(template, mu, sigma, np.random.default_rng(_seed(init) + 1))[..., None]
