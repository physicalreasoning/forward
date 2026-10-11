"""Task 2: Kalshi's daily price ladders (indices, FX, commodities) against their underlying.

Each ladder asks where a price settles at the close. At the read (24 h or 6 h before close) an
entry sees the underlying's hourly closes up to the read and returns a distribution over the
ladder's buckets. The trivial answer is to copy the last price: a lognormal centred on it,
with the spread of log moves over the same clock window on the previous 60 days, no drift
(isotherm FINDINGS §47). Prices are martingales, so a learned model has to beat this to show it
learned anything (the copying failure in causal-jepa).

Ladder construction and the copy baseline follow isotherm's scripts/bench/evaluate.py, which is
frozen for isotherm's own sealed tests and so is copied here rather than imported.
"""

from __future__ import annotations

import json
import urllib.request

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import DATA

EPS = 1e-4
LEADS = {"24h": 86400, "6h": 21600}
SYMBOL = {
    "KXINX": "^GSPC",
    "KXNASDAQ100": "^NDX",
    "KXEURUSD": "EURUSD=X",
    "KXUSDJPY": "JPY=X",
    "KXWTI": "CL=F",
    "KXGOLDD": "GC=F",
    "KXSILVERD": "SI=F",
    "KXCOPPERD": "HG=F",
    "KXBRENTD": "BZ=F",
    "KXNATGASD": "NG=F",
}
CONTEXT = 512  # hourly bars given to a learned entry


def interval(st, fl, cp):
    if st == "less":
        return -np.inf, cp
    if st in ("greater", "greater_or_equal"):
        return fl, np.inf
    if st == "between":
        return fl, cp
    return None


def problems(series: str, df: pd.DataFrame) -> list[dict]:
    """One problem per (event, lead) with at least two two-sided quotes at the lead."""
    out = []
    for ev, g in df.groupby("event"):
        g = g[g["result"].notna()]
        if g.empty:
            continue
        sts = set(g["strike_type"].dropna())
        kind = "threshold" if sts <= {"greater", "greater_or_equal"} else "partition"
        iv = [interval(s, f, c) for s, f, c in zip(g["strike_type"], g["floor"], g["cap"], strict=True)]
        if any(x is None for x in iv):
            continue
        g = g.assign(lo=[a for a, _ in iv], hi=[b for _, b in iv]).sort_values(["lo", "hi"])
        if kind == "partition" and g["result"].sum() != 1:
            continue
        close = int(g["close_ts"].max())
        day = pd.to_datetime(close, unit="s", utc=True).tz_convert("America/New_York").normalize()
        for lead, sec in LEADS.items():
            bid = g["bid_" + lead].to_numpy(float)
            ask = g["ask_" + lead].to_numpy(float)
            two = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask < 1) & (ask > bid)
            if two.sum() < 2:
                continue
            out.append(
                {
                    "series": series,
                    "event": ev,
                    "lead": lead,
                    "day": day.tz_localize(None),
                    "read_ts": close - sec,
                    "close_ts": close,
                    "kind": kind,
                    "lo": g["lo"].to_numpy(float),
                    "hi": g["hi"].to_numpy(float),
                    "bid": np.nan_to_num(bid, nan=0.0),
                    "ask": np.nan_to_num(ask, nan=1.0),
                    "y": g["result"].to_numpy(int),
                }
            )
    return out


def outcome(pr) -> int:
    """Index of the realised bucket (threshold ladders: strikes that settled YES)."""
    return int(pr["y"].sum()) if pr["kind"] == "threshold" else int(np.argmax(pr["y"]))


def to_buckets(p_above):
    q = np.minimum.accumulate(np.clip(p_above, EPS, 1 - EPS))
    p = np.concatenate([[1 - q[0]], q[:-1] - q[1:], [q[-1]]])
    p = np.clip(p, EPS, None)
    return p / p.sum()


def from_cdf(pr, F):
    """Bucket probabilities from a CDF over the settlement price."""
    if pr["kind"] == "threshold":
        return to_buckets(1 - F(pr["lo"]))
    lo = np.where(np.isfinite(pr["lo"]), F(pr["lo"]), 0.0)
    hi = np.where(np.isfinite(pr["hi"]), F(pr["hi"]), 1.0)
    p = np.clip(hi - lo, EPS, None)
    return p / p.sum()


def lognormal_cdf(center, sigma):
    return lambda x: norm.cdf((np.log(np.clip(x, 1e-12, None)) - np.log(center)) / sigma)


def market(pr, use):
    """'mid' or 'bid' (empty bids floored at half a cent, isotherm §41) as a ladder distribution."""
    px = (pr["bid"] + pr["ask"]) / 2 if use == "mid" else np.maximum(pr["bid"], 0.005)
    if pr["kind"] == "threshold":
        return to_buckets(px)
    p = np.clip(px, EPS, None)
    return p / p.sum()


def log_score(p, pr) -> float:
    return float(np.log(max(p[outcome(pr)], EPS)))


# Underlying prices ---------------------------------------------------------------------------


def hourly(symbol: str) -> pd.DataFrame:
    """Hourly closes for the last two years from Yahoo (free); bar start times in UTC seconds."""
    f = DATA / "prices" / "{}.parquet".format(symbol.replace("^", "").replace("=", "_"))
    if f.exists():
        return pd.read_parquet(f)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2y&interval=1h"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())["chart"]["result"][0]
    px = pd.DataFrame({"ts": d["timestamp"], "close": d["indicators"]["quote"][0]["close"]}).dropna()
    f.parent.mkdir(parents=True, exist_ok=True)
    px.to_parquet(f, index=False)
    return px


def bars_before(ts, t) -> int:
    """Number of hourly bars that closed by t (a bar starting at s closes at s + 3600)."""
    return int(np.searchsorted(ts, t - 3600, side="right"))


def copy_baseline(pr, ts, cl):
    """Lognormal at the last close, spread from same-clock-window moves on the previous 60 days."""
    n = bars_before(ts, pr["read_ts"])
    if n == 0:
        return None
    s = cl[n - 1]
    lead = pr["close_ts"] - pr["read_ts"]
    moves = []
    for k in range(1, 61):
        end = pr["close_ts"] - k * 86400
        a, b = bars_before(ts, end - lead), bars_before(ts, end)
        if a and b and cl[a - 1] > 0 and cl[b - 1] > 0 and a != b:
            moves.append(np.log(cl[b - 1] / cl[a - 1]))
    if len(moves) < 15:
        return None
    return from_cdf(pr, lognormal_cdf(s, max(float(np.std(moves)), 1e-4)))


def horizon_bars(pr, ts) -> int:
    """How many hourly bars the read-to-close window usually holds (median of the previous 20
    days), so a learned entry forecasts the right number of steps through closed sessions."""
    lead = pr["close_ts"] - pr["read_ts"]
    hs = [
        bars_before(ts, pr["close_ts"] - k * 86400) - bars_before(ts, pr["close_ts"] - k * 86400 - lead)
        for k in range(1, 21)
    ]
    hs = [h for h in hs if h > 0]
    return int(np.median(hs)) if hs else 0


def context(pr, ts, cl):
    n = bars_before(ts, pr["read_ts"])
    return cl[max(0, n - CONTEXT) : n]
