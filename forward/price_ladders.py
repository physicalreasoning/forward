"""Kalshi price ladders that settle inside a round's window, in the layout `prices.problems` reads.

One row per market: strikes, result, close time, and bid/ask at each lead before close from the
last hourly candle that closed by then (as isotherm's scripts/bench/fetch.py records them).
"""

from __future__ import annotations

import pandas as pd
from isotherm import kalshi

from . import DATA
from .prices import LEADS


def fetch(series: str, start: str, end: str) -> pd.DataFrame:
    f = DATA / "price_ladders" / f"{series}_{start}_{end}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    lo_ts = int(pd.Timestamp(start, tz="America/New_York").timestamp())
    hi_ts = int((pd.Timestamp(end, tz="America/New_York") + pd.Timedelta(days=1)).timestamp())
    cutoff = kalshi.cutoff_ts()
    rows = []
    for e in kalshi.settled_events(series, max_pages=500):
        if not e["event_ticker"].startswith(series + "-"):
            continue
        ms = kalshi.event_markets(e["event_ticker"])
        if not ms:
            continue
        close = max(kalshi.ts(m["close_time"]) for m in ms)
        if not (lo_ts <= close < hi_ts):
            continue
        open_ts = min(kalshi.ts(m["open_time"]) for m in ms)
        if close >= cutoff:
            r = kalshi.get(
                f"series/{series}/events/{e['event_ticker']}/candlesticks",
                _cache=True,
                start_ts=open_ts,
                end_ts=close,
                period_interval=60,
            )
            cs = dict(zip(r.get("market_tickers", []), r.get("market_candlesticks", []), strict=False))
        else:
            cs = {m["ticker"]: kalshi.candles(m, 60) for m in ms}
        for m in ms:
            row = {
                "series": series,
                "event": e["event_ticker"],
                "ticker": m["ticker"],
                "strike_type": m.get("strike_type"),
                "floor": kalshi.to_float(m.get("floor_strike")),
                "cap": kalshi.to_float(m.get("cap_strike")),
                "result": kalshi.result_yes(m),
                "close_ts": kalshi.ts(m["close_time"]),
            }
            mc = sorted(cs.get(m["ticker"]) or [], key=lambda c: c.get("end_period_ts", 0))
            for lead, sec in LEADS.items():
                before = [c for c in mc if c.get("end_period_ts", 0) <= row["close_ts"] - sec]
                bid, ask = kalshi.candle_quote(before[-1]) if before else (None, None)
                row["bid_" + lead], row["ask_" + lead] = bid, ask
            rows.append(row)
    df = pd.DataFrame(rows)
    f.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(f, index=False)
    return df
