"""Kalshi daily-high ladders at the read: each bucket's edges, bid, ask and result.

The read is 20:00 UTC on D-1, the same instant the model forecasts are captured. A quote is the
last hourly candle that closed at or before it, so nothing after the read leaks in.
"""

from __future__ import annotations

import pandas as pd
from isotherm import kalshi
from isotherm.weather import bucket_interval

from . import DATA

READ_HOUR_UTC = 20


def target_day(event_ticker: str) -> pd.Timestamp | None:
    """Target day from a ticker like KXHIGHNY-26OCT12; None for legacy formats."""
    try:
        return pd.to_datetime(event_ticker.split("-")[1][:7], format="%y%b%d")
    except (IndexError, ValueError):
        return None


def read_ts(day: pd.Timestamp) -> int:
    t = (day - pd.Timedelta(days=1)).replace(hour=READ_HOUR_UTC).tz_localize("UTC")
    return int(t.timestamp())


def _quotes(series: str, event: str, ms: list, t: int, cutoff: int) -> dict:
    open_ts = min(kalshi.ts(m["open_time"]) for m in ms)
    close_ts = max(kalshi.ts(m["close_time"]) for m in ms)
    if close_ts >= cutoff:
        r = kalshi.get(
            f"series/{series}/events/{event}/candlesticks",
            _cache=True,
            start_ts=open_ts,
            end_ts=min(close_ts, t + 3600),
            period_interval=60,
        )
        cs = dict(zip(r.get("market_tickers", []), r.get("market_candlesticks", []), strict=False))
    else:
        cs = {m["ticker"]: kalshi.candles(m, 60) for m in ms}
    out = {}
    for m in ms:
        before = [c for c in (cs.get(m["ticker"]) or []) if c.get("end_period_ts", 0) <= t]
        out[m["ticker"]] = kalshi.candle_quote(before[-1]) if before else (None, None)
    return out


def ladders(series: str, start: str, end: str) -> pd.DataFrame:
    """One row per bucket for target days in [start, end], settled events only."""
    f = DATA / "ladders" / f"{series}_{start}_{end}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    cutoff = kalshi.cutoff_ts()
    rows = []
    for e in kalshi.settled_events(series):
        day = target_day(e["event_ticker"])
        if day is None or not e["event_ticker"].startswith(series + "-"):
            continue
        if not (pd.Timestamp(start) <= day <= pd.Timestamp(end)):
            continue
        ms = [m for m in kalshi.event_markets(e["event_ticker"]) if m.get("strike_type")]
        t = read_ts(day)
        live = [m for m in ms if kalshi.ts(m["open_time"]) < t]
        if not live:
            continue
        q = _quotes(series, e["event_ticker"], live, t, cutoff)
        for m in live:
            lo, hi = bucket_interval(
                m["strike_type"], kalshi.to_float(m.get("floor_strike")), kalshi.to_float(m.get("cap_strike"))
            )
            bid, ask = q[m["ticker"]]
            rows.append(
                {
                    "series": series,
                    "event": e["event_ticker"],
                    "day": day,
                    "ticker": m["ticker"],
                    "lo": lo,
                    "hi": hi,
                    "bid": bid,
                    "ask": ask,
                    "yes": kalshi.result_yes(m),
                }
            )
    df = pd.DataFrame(rows)
    f.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(f, index=False)
    return df
