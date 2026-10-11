#!/usr/bin/env python3
"""Task 2 dry run: time-series foundation models against copy-the-last-price on Kalshi ladders.

    uv run --extra tsfm scripts/score_prices.py --raw ~/isotherm/data/bench/raw

Ladders and quotes come from isotherm's benchmark fetch (data/bench/raw, 400 events per series);
prices from Yahoo's last two years of hourly bars, so only ladders inside that span are scored.
Not sealed: the models are public and fixed, but this window is in the past. Round 2 runs the
same entries on ladders that settle after its freeze.

Entries: copy (the martingale baseline), chronos-bolt-small, chronos-bolt-base, timesfm-2.5,
and for each learned model a "-centre" variant (its median, the copy baseline's spread), which
separates what the model knows about where the price goes from what it knows about how far.
"""

from __future__ import annotations

import argparse
import json
import pathlib

import numpy as np
import pandas as pd

from forward import ROOT, metrics, prices
from forward.tsfm import Chronos, TimesFM

MIN_CONTEXT = 256
BATCH = 64


def market_level(pr, p):
    """The entry's probability for each quoted market: the bucket (partition) or 'above strike'."""
    if pr["kind"] == "threshold":
        return 1 - np.cumsum(p)[:-1]
    return p


def build(raw: pathlib.Path):
    probs = []
    for series, symbol in prices.SYMBOL.items():
        f = raw / f"{series}.parquet"
        if not f.exists():
            continue
        px = prices.hourly(symbol)
        ts, cl = px["ts"].to_numpy(), px["close"].to_numpy(float)
        for pr in prices.problems(series, pd.read_parquet(f)):
            ctx = prices.context(pr, ts, cl)
            h = prices.horizon_bars(pr, ts)
            if len(ctx) < MIN_CONTEXT or h < 1:
                continue
            copy = prices.copy_baseline(pr, ts, cl)
            if copy is None:
                continue
            n = prices.bars_before(ts, pr["read_ts"])
            sigma_copy = _copy_sigma(pr, ts, cl)
            probs.append(
                {**pr, "ctx": ctx, "h": h, "last": cl[n - 1], "copy": copy, "sigma_copy": sigma_copy}
            )
        print(series, sum(p["series"] == series for p in probs), flush=True)
    return probs


def _copy_sigma(pr, ts, cl):
    lead = pr["close_ts"] - pr["read_ts"]
    moves = []
    for k in range(1, 61):
        end = pr["close_ts"] - k * 86400
        a, b = prices.bars_before(ts, end - lead), prices.bars_before(ts, end)
        if a and b and cl[a - 1] > 0 and cl[b - 1] > 0 and a != b:
            moves.append(np.log(cl[b - 1] / cl[a - 1]))
    return max(float(np.std(moves)), 1e-4)


def run_model(model, probs):
    centres, sigmas = np.zeros(len(probs)), np.zeros(len(probs))
    for i in range(0, len(probs), BATCH):
        chunk = probs[i : i + BATCH]
        c, s = model.predict([p["ctx"] for p in chunk], [p["h"] for p in chunk])
        centres[i : i + len(chunk)], sigmas[i : i + len(chunk)] = c, s
    return centres, sigmas


def settle_proxy(pr):
    """A point inside the realised bucket, for the direction check (finite edge if one is open)."""
    k = prices.outcome(pr)
    edges = np.concatenate([[-np.inf], pr["lo"], [np.inf]]) if pr["kind"] == "threshold" else None
    if pr["kind"] == "threshold":
        lo, hi = edges[k], edges[k + 1]
    else:
        lo, hi = pr["lo"][k], pr["hi"][k]
    if np.isfinite(lo) and np.isfinite(hi):
        return (lo + hi) / 2
    return lo if np.isfinite(lo) else hi


def summarise(probs, scores, pnl):
    dates = np.array([p["day"] for p in probs])
    out = {"problems": len(probs), "days": len(set(dates))}
    for e in scores:
        out[e] = {
            "log_score": float(np.mean(scores[e])),
            "vs_copy": metrics.diff(dates, scores[e], scores["copy"]),
            "vs_market_bid": metrics.diff(dates, scores[e], scores["market_bid"]),
            "vs_market_mid": metrics.diff(dates, scores[e], scores["market_mid"]),
        }
        if e in pnl:
            out[e]["pnl"] = float(np.sum(pnl[e][0]))
            out[e]["pnl_slip1"] = float(np.sum(pnl[e][1]))
            out[e]["pnl_slip1_per_ladder_ci"] = metrics.block_ci(dates, pnl[e][1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=pathlib.Path, default=pathlib.Path.home() / "isotherm/data/bench/raw")
    a = ap.parse_args()
    probs = build(a.raw)
    print("problems", len(probs), flush=True)
    models = {
        "chronos-bolt-small": lambda: Chronos("amazon/chronos-bolt-small"),
        "chronos-bolt-base": lambda: Chronos("amazon/chronos-bolt-base"),
        "timesfm-2.5": lambda: TimesFM(max_horizon=max(p["h"] for p in probs)),
    }
    dists = {"copy": [p["copy"] for p in probs]}
    direction = {}
    for name, make in models.items():
        c, s = run_model(make(), probs)
        dists[name] = [
            prices.from_cdf(p, prices.lognormal_cdf(ci, si)) for p, ci, si in zip(probs, c, s, strict=True)
        ]
        dists[name + "-centre"] = [
            prices.from_cdf(p, prices.lognormal_cdf(ci, p["sigma_copy"]))
            for p, ci in zip(probs, c, strict=True)
        ]
        # Does the model's median move point the way the price went? 50% is a coin.
        move = np.log(c / np.array([p["last"] for p in probs]))
        real = np.log(np.array([settle_proxy(p) for p in probs]) / np.array([p["last"] for p in probs]))
        nz = np.abs(move) > 1e-9
        direction[name] = {
            "hit_rate": float(np.mean(np.sign(move[nz]) == np.sign(real[nz]))) if nz.any() else None,
            "share_moved": float(nz.mean()),
            "median_abs_move_bp": float(np.median(np.abs(move)) * 1e4),
            "sigma_ratio_to_copy": float(np.median(s / np.array([p["sigma_copy"] for p in probs]))),
        }
        print(name, direction[name], flush=True)
    dists["market_bid"] = [prices.market(p, "bid") for p in probs]
    dists["market_mid"] = [prices.market(p, "mid") for p in probs]
    scores = {
        e: np.array([prices.log_score(d, p) for d, p in zip(ds, probs, strict=True)])
        for e, ds in dists.items()
    }
    pnl = {}
    for e, ds in dists.items():
        if e.startswith("market"):
            continue
        rows = [
            [
                metrics.taker_pnl(market_level(p, d), p["bid"], p["ask"], p["y"].astype(float), slip=s)[0]
                for s in (0, 0.01)
            ]
            for d, p in zip(ds, probs, strict=True)
        ]
        pnl[e] = np.array(rows).T
    res = {"kind": "dry run (not sealed)", "direction": direction}
    for lead in prices.LEADS:
        idx = [i for i, p in enumerate(probs) if p["lead"] == lead]
        sub = [probs[i] for i in idx]
        res[lead] = {
            "pooled": summarise(
                sub, {e: v[idx] for e, v in scores.items()}, {e: v[:, idx] for e, v in pnl.items()}
            ),
            "by_series": {},
        }
        for s in sorted({p["series"] for p in sub}):
            j = [i for i in idx if probs[i]["series"] == s]
            res[lead]["by_series"][s] = summarise(
                [probs[i] for i in j],
                {e: v[j] for e, v in scores.items()},
                {e: v[:, j] for e, v in pnl.items()},
            )
    out = ROOT / "results" / "prices_dry_run.json"
    out.write_text(json.dumps(res, indent=1, default=str))
    for lead in prices.LEADS:
        P = res[lead]["pooled"]
        print(f"\n{lead}: {P['problems']} ladders, {P['days']} days")
        for e in dists:
            x = P[e]
            line = "{:26s} log {:+.3f}  vs copy {:+.3f} [{:+.3f}, {:+.3f}]  vs bid {:+.3f} [{:+.3f}, {:+.3f}]".format(
                e,
                x["log_score"],
                x["vs_copy"]["diff"],
                *x["vs_copy"]["ci"],
                x["vs_market_bid"]["diff"],
                *x["vs_market_bid"]["ci"],
            )
            if "pnl" in x:
                line += "  pnl ${:+.0f} (1c ${:+.0f})".format(x["pnl"], x["pnl_slip1"])
            print(line)


if __name__ == "__main__":
    main()
