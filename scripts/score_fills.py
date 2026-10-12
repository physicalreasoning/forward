#!/usr/bin/env python3
"""Task 3 dry run: fills under intervention, on the order books recorded so far.

    uv run scripts/score_fills.py                       # isotherm's recorder output, read only
    uv run scripts/score_fills.py --end 2026-10-12T18:00 --cutoff 2026-10-12

Rebuilds every market's book from isotherm's raw websocket record, simulates hypothetical
passive limit orders at every clean decision time (forward/fills.py), fits the entries on rows
whose labels resolved before the cutoff (an America/New_York date) and scores them on decision
times after it. Not sealed and not a result: the record is a day or two long. It checks that the
pipeline a sealed round would run works end to end.

Parsed events and samples are cached under data/fills/ (git-ignored), keyed by --end.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import time

import numpy as np
import pandas as pd

from forward import DATA, ROOT, fills, metrics
from forward.fill_entries import brier, entries, log_score, reliability

ISOTHERM = pathlib.Path.home() / "isotherm" / "data" / "book"
TZ = "America/New_York"
MIN_BLOCKS = 10  # below this a block bootstrap interval is not worth reading
ZERO = "zero (copy, queue, queue-cal)"


def ms(ts: pd.Timestamp) -> int:
    return int(ts.value // 1_000_000)


def load(raw, gaps_log, end_ms, rebuild):
    cache = DATA / "fills"
    cache.mkdir(parents=True, exist_ok=True)
    tag = pd.Timestamp(end_ms, unit="ms", tz="UTC").strftime("%Y%m%dT%H%M")
    ev_f, s_f = cache / f"events-{tag}.parquet", cache / f"samples-{tag}.parquet"
    if ev_f.exists() and not rebuild:
        ev = pd.read_parquet(ev_f)
    else:
        ev = fills.load_events(raw, end_ms)
        ev.to_parquet(ev_f)
    gaps = fills.gap_intervals(ev, gaps_log, end_ms)
    if s_f.exists() and not rebuild:
        df = pd.read_parquet(s_f)
    else:
        df = fills.build_samples(ev, gaps)
        df.to_parquet(s_f)
    return ev, gaps, df


def record_summary(ev, gaps, end_ms) -> dict:
    t = ev["recv"].to_numpy()
    span = (int(t[0]), int(min(t[-1], end_ms)))
    inner = gaps[(gaps[:, 1] > span[0]) & (gaps[:, 0] < span[1])]
    lost = sum(min(b, span[1]) - max(a, span[0]) for a, b in inner)
    iso = lambda x: pd.Timestamp(x, unit="ms", tz="UTC").isoformat()  # noqa: E731
    trades = int((ev["kind"] == fills.TRADE).sum())
    return {
        "first_message": iso(span[0]),
        "last_message": iso(span[1]),
        "hours_recorded": round((span[1] - span[0]) / 3.6e6, 2),
        "hours_clean": round((span[1] - span[0] - lost) / 3.6e6, 2),
        "gaps": len(inner),
        "events": len(ev),
        "markets": int(ev.loc[ev["kind"] == fills.SNAP, "tk"].nunique()),
        "trades": trades,
        "trades_matched_to_a_delta": int(ev["exec"].sum()),
    }


def mean_ci(blocks, v) -> dict:
    return {"mean": float(np.mean(v)), "ci": metrics.block_ci(blocks, v)}


def score_horizon(df, h, cutoff_ms, block) -> dict:
    d = fills.labels(df, h)
    resolve = d["t0"] + fills.HORIZONS[h] + fills.MOVE_MS
    train, test = d[resolve <= cutoff_ms], d[d["t0"] >= cutoff_ms]
    alt = {v: fills.labels(df, h, v).loc[test.index, "y"].to_numpy() for v in fills.VARIANTS}
    if len(train) == 0 or len(test) == 0:
        return {"train_rows": len(train), "test_rows": len(test)}
    t0 = pd.to_datetime(test["t0"], unit="ms", utc=True).dt.tz_convert(TZ)
    blocks = (t0.dt.strftime("%Y-%m-%d") if block == "date" else t0.dt.strftime("%Y-%m-%d %H")).to_numpy()
    y = test["y"].to_numpy()
    fitted = [e.fit(train) for e in entries(h)]
    probs = {e.name: e.predict(test) for e in fitted}
    ls = {k: log_score(y, p) for k, p in probs.items()}
    out = {
        "train_rows": len(train),
        "train_fills": int(train["y"].sum()),
        "test_rows": len(test),
        "test_fills": int(y.sum()),
        "test_markets": int(test["tk"].nunique()),
        "test_decision_times": int(test["t0"].nunique()),
        "blocks": int(len(np.unique(blocks))),
        "intervals_meaningful": bool(len(np.unique(blocks)) >= MIN_BLOCKS),
        "fill_rate": mean_ci(blocks, y),
        "fill_rate_by_label_variant": {v: mean_ci(blocks, a) for v, a in alt.items()},
        "fills_completed_by": test.loc[test["y"] == 1, "how"].value_counts(normalize=True).to_dict(),
        "fill_rate_by_level_and_size": {
            f"{lv:+d}c x{q}": float(g["y"].mean()) for (lv, q), g in test.groupby(["level", "size"])
        },
        "models": {},
    }
    for k, p in probs.items():
        out["models"][k] = {
            "log_score": mean_ci(blocks, ls[k]),
            "brier": mean_ci(blocks, brier(y, p)),
            "log_score_minus_base_rate": metrics.diff(blocks, ls[k], ls["base-rate"]),
            "log_score_minus_copy": metrics.diff(blocks, ls[k], ls["copy"]),
            "log_score_by_label_variant": {v: float(log_score(a, p).mean()) for v, a in alt.items()},
            "calibration": reliability(y, p),
        }
    # The move after a fill: rows that filled within h with a clean 5 minutes after the fill.
    f = test["move"].notna().to_numpy()
    if f.sum():
        mv, fb = test["move"].to_numpy()[f], blocks[f]
        out["move"] = {"fills": int(f.sum()), "realised_cents": mean_ci(fb, mv), "models": {}}
        se0 = mv**2
        for e in fitted:
            pred = e.move(test[f])
            if not pred.any() and e.name != "copy":
                continue  # predicts no move, the same forecast as copy's
            se, ae = (pred - mv) ** 2, np.abs(pred - mv)
            out["move"]["models"][ZERO if e.name == "copy" else e.name] = {
                "mae_cents": mean_ci(fb, ae),
                "rmse_cents": float(np.sqrt(se.mean())),
                "sq_error_minus_zero": metrics.diff(fb, se, se0),
            }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=pathlib.Path, default=ISOTHERM / "raw")
    ap.add_argument("--gaps", type=pathlib.Path, default=ISOTHERM / "gaps.jsonl")
    ap.add_argument("--end", help="UTC; only hourly files that closed by then (default: this hour)")
    ap.add_argument("--cutoff", default="2026-10-12", help="first test date (America/New_York)")
    ap.add_argument("--block", choices=["auto", "date", "hour"], default="auto")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "results" / "fills_dry_run.json")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    end = pd.Timestamp(a.end, tz="UTC") if a.end else pd.Timestamp.now("UTC").floor("h")
    end_ms, cutoff_ms = ms(end), ms(pd.Timestamp(a.cutoff, tz=TZ))
    t = time.time()
    ev, gaps, df = load(a.raw, a.gaps, end_ms, a.rebuild)
    print(f"{len(ev):,} events, {len(df):,} actions in {time.time() - t:.0f} s", flush=True)
    test_dates = pd.to_datetime(df.loc[df["t0"] >= cutoff_ms, "t0"], unit="ms", utc=True).dt.tz_convert(TZ)
    block = a.block
    if block == "auto":
        block = "date" if test_dates.dt.date.nunique() >= 5 else "hour"
    res = {
        "task": "fills under intervention",
        "status": "pipeline check on the first day of recorded books, not a result",
        "record": record_summary(ev, gaps, end_ms),
        "design": {
            "end": end.isoformat(),
            "cutoff": f"{a.cutoff} (America/New_York); train labels resolve by then, test t0 after",
            "decision_grid_minutes": fills.GRID_MS // 60_000,
            "lookback_minutes": fills.LOOKBACK_MS // 60_000,
            "horizons": list(fills.HORIZONS),
            "move_after_fill_minutes": fills.MOVE_MS // 60_000,
            "levels_cents_from_best_bid": list(fills.LEVELS),
            "sizes": list(fills.SIZES),
            "mid_range_cents": list(fills.MID_RANGE),
            "label": "whole order filled within the horizon, pro-rata cancellations",
            "ci": f"95%, {block}-block bootstrap ({'one test date' if block == 'hour' else 'dates'})",
        },
        "actions": len(df),
        "horizons": {},
    }
    for h in fills.HORIZONS:
        res["horizons"][h] = score_horizon(df, h, cutoff_ms, block)
        r = res["horizons"][h]
        if "models" in r:
            m = r["models"]
            line = ", ".join(f"{k} {metrics.fmt(v['log_score_minus_base_rate'])}" for k, v in m.items())
            print(f"{h}: {r['test_rows']:,} test rows, fill rate {r['fill_rate']['mean']:.3f}; {line}")
    a.out.write_text(json.dumps(res, indent=1) + "\n")
    print(a.out)


if __name__ == "__main__":
    main()
