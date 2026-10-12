#!/usr/bin/env python3
"""Score the station-high task over a window, for every entry, on all mandatory columns.

    uv run scripts/score.py --dry-run 2026-07-01 2026-10-09   # Round 0: fit through Jun 30, archive inputs
    uv run scripts/score.py --round 1                          # sealed: frozen params, captured inputs

The dry run fits entries on data settled before its window and uses the archive's
previous-day runs as inputs. It checks the pipeline and gives a first look; it is not sealed.
A sealed round loads frozen/round<N>.json (hash-checked) and the inputs captured live at
each read (ledger/), and refuses to report a verdict until the window has settled.
"""

from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np
import pandas as pd

from forward import ROOT, entries, metrics, truth
from forward import ledger as ledger_mod
from forward.history import fit_table
from forward.market import ladders
from forward.seal import check_frozen
from forward.stations import STATIONS

BASELINES = ("persistence", "climatology")


def score(d: pd.DataFrame, params: dict, lad: pd.DataFrame) -> dict:
    d = d.dropna(subset=["high"]).reset_index(drop=True)
    pred = entries.predict(params, d)
    # Score every entry on the same rows: those where all entries have a forecast.
    ok = np.ones(len(d), bool)
    for mu, _ in pred.values():
        ok &= np.isfinite(mu)
    d, pred = d[ok].reset_index(drop=True), {e: (m[ok], s[ok]) for e, (m, s) in pred.items()}
    dates, months = d["day"].to_numpy(), d["day"].dt.to_period("M").astype(str).to_numpy()
    y = d["high"].to_numpy()
    ls = {e: metrics.log_score(y, *pred[e]) for e in pred}
    rp = {e: metrics.rps(y, *pred[e]) for e in pred}
    res = {"rows": len(d), "days": int(d["day"].nunique()), "entries": {}}
    for e in pred:
        res["entries"][e] = {
            "log_score": float(ls[e].mean()),
            "rps": float(rp[e].mean()),
            "mae_mu": float(np.abs(pred[e][0] - y).mean()),
            "calibration": metrics.calibration(metrics.pit(y, *pred[e])),
            "log_vs_persistence": metrics.diff(dates, ls[e], ls["persistence"]),
            "log_vs_climatology": metrics.diff(dates, ls[e], ls["climatology"]),
            "rps_skill_vs_persistence": float(1 - rp[e].mean() / rp["persistence"].mean()),
            "month_share_of_gain_vs_persistence": metrics.month_share(months, ls[e] - ls["persistence"]),
            "by_month_log_vs_persistence": {
                m: float((ls[e] - ls["persistence"])[months == m].mean()) for m in np.unique(months)
            },
        }
    res["ladders"] = ladder_scores(d, pred, lad)
    res["tests"] = tests(dates, ls, res["ladders"])
    return res


def tests(dates, ls, lad) -> dict:
    """The pre-registered tests of ROUND1.md, computed the same way for the dry run."""

    def verdict(ci, two_sided=False):
        if ci[0] > 0:
            return "PASS" if not two_sided else "first better"
        if two_sided and ci[1] < 0:
            return "second better"
        return "FAIL" if not two_sided else "tie"

    h1 = metrics.diff(dates, ls["emos-aifs"], ls["emos-ifs"])
    h1_raw = metrics.diff(dates, ls["raw-aifs"], ls["raw-ifs"])
    out = {
        "H1_emos_aifs_minus_emos_ifs": {**h1, "verdict": verdict(h1["ci"], True)},
        "H1_secondary_raw_aifs_minus_raw_ifs": {**h1_raw, "verdict": verdict(h1_raw["ci"], True)},
        "H2_emos_minus_persistence": {
            e: {**v, "verdict": verdict(v["ci"])}
            for e in ls
            if e.startswith("emos-")
            for v in [metrics.diff(dates, ls[e], ls["persistence"])]
        },
    }
    if "emos-all" in lad:
        h3 = lad["emos-all"]["log_vs_market_bid"]
        out["H3_emos_all_minus_bid_market"] = {**h3, "verdict": verdict(h3["ci"])}
        h4 = lad["emos-all"]["pnl_slip1_per_ladder"]
        out["H4_emos_all_pnl_per_ladder_slip1"] = {**h4, "verdict": verdict(h4["ci"])}
    return out


def ladder_scores(d, pred, lad) -> dict:
    """Entries against the market on Kalshi ladders: log score of the winning bucket, and P&L."""
    if lad.empty:
        return {}
    key = {(r.station, r.day): i for i, r in enumerate(d[["station", "day"]].itertuples(index=False))}
    series_to_station = {st.series: k for k, st in STATIONS.items()}
    per = {e: [] for e in list(pred) + ["market_bid", "market_mid"]}
    pnl = {e: {"slip0": [], "slip1": [], "trades": 0} for e in pred}
    dates = []
    for _, g in lad.groupby("event"):
        g = g.sort_values("lo")
        if g["yes"].isna().any() or g["yes"].sum() != 1:
            continue
        i = key.get((series_to_station[g["series"].iat[0]], g["day"].iat[0]))
        if i is None:
            continue
        win = int(np.argmax(g["yes"].to_numpy()))
        edges = list(zip(g["lo"], g["hi"], strict=True))
        bid, ask = g["bid"].to_numpy(float), g["ask"].to_numpy(float)
        if not np.isfinite(bid).any():
            continue
        dates.append(g["day"].iat[0])
        for kind in ("bid", "mid"):
            per["market_" + kind].append(np.log(metrics.market_probs(bid, ask, kind)[win]))
        for e, (mu, s) in pred.items():
            p = metrics.bucket_probs(edges, mu[i], s[i])
            per[e].append(np.log(p[win] / p.sum()))
            for slip, k in ((0.0, "slip0"), (0.01, "slip1")):
                v, n = metrics.taker_pnl(p, bid, ask, g["yes"].to_numpy(float), slip=slip)
                pnl[e][k].append(v)
                pnl[e]["trades"] += n if slip == 0 else 0
    out = {"ladders": len(dates)}
    for e in pred:
        out[e] = {
            "log_vs_market_bid": metrics.diff(dates, per[e], per["market_bid"]),
            "log_vs_market_mid": metrics.diff(dates, per[e], per["market_mid"]),
            "pnl": float(np.sum(pnl[e]["slip0"])),
            "pnl_ci_per_ladder": metrics.block_ci(dates, pnl[e]["slip0"]),
            "pnl_slip1": float(np.sum(pnl[e]["slip1"])),
            "pnl_slip1_per_ladder": {
                "mean": float(np.mean(pnl[e]["slip1"])),
                "ci": metrics.block_ci(dates, pnl[e]["slip1"]),
            },
            "trades": pnl[e]["trades"],
        }
    out["market_bid_log"] = float(np.mean(per["market_bid"]))
    out["market_mid_log"] = float(np.mean(per["market_mid"]))
    return out


def dry_run(start: str, end: str) -> dict:
    d = fit_table(end)
    train = d[d["day"] < pd.Timestamp(start) - pd.Timedelta(days=1)]
    params = json.loads(json.dumps(entries.fit(train)))
    test = d[(d["day"] >= pd.Timestamp(start)) & (d["day"] <= pd.Timestamp(end))]
    lad = pd.concat([ladders(st.series, start, end) for st in STATIONS.values()], ignore_index=True)
    res = score(test, params, lad)
    res.update({"kind": "dry-run (not sealed)", "window": [start, end], "inputs": "archive previous_day1"})
    return res


def sealed(n: int, ledger_dir) -> dict:
    fz = check_frozen(n)
    start, end = fz["window"]
    fc, log = ledger_mod.load(ledger_dir, start, end)
    lad = pd.concat([ladders(st.series, start, end) for st in STATIONS.values()], ignore_index=True)
    # Truth: the CLI high, refetched now; Kalshi's settlement value where the CLI is missing.
    years = range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1)
    cli = truth.all_highs(STATIONS, years)
    k2s = {st.series: k for k, st in STATIONS.items()}
    kal = lad.dropna(subset=["settle"]).groupby(["series", "day"])["settle"].first().reset_index()
    kal = kal.assign(station=kal["series"].map(k2s)).rename(columns={"settle": "high"})
    t = cli.set_index(["station", "day"])["high"]
    t = t.combine_first(kal.set_index(["station", "day"])["high"]).rename("high").reset_index()
    in_cli = pd.MultiIndex.from_frame(t[["station", "day"]]).isin(cli.set_index(["station", "day"]).index)
    n_kalshi = int((~in_cli).sum())
    prev = t.assign(day=t["day"] + pd.Timedelta(days=1)).rename(columns={"high": "prev_high"})
    d = fc.merge(t, on=["station", "day"], how="left").merge(prev, on=["station", "day"], how="left")
    res = score(d, fz["params"], lad)
    res.update(
        {
            "kind": f"sealed round {n}",
            "window": [start, end],
            "inputs": "ledger",
            "ledger": log,
            "truth_from_kalshi": n_kalshi,
            "complete": bool(pd.Timestamp.now() > pd.Timestamp(end) + pd.Timedelta(days=2)),
            "params_sha256": fz["params_sha256"],
        }
    )
    if not res["complete"]:
        res["tests"] = {"note": "window not settled; no verdicts before it is"}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", nargs=2, metavar=("START", "END"))
    ap.add_argument("--round", type=int)
    ap.add_argument("--ledger", default=str(ROOT.parent / "forward-ledger" / "ledger"))
    a = ap.parse_args()
    if a.dry_run:
        res = dry_run(*a.dry_run)
        out = ROOT / "results" / "round0_dry_run.json"
    else:
        res = sealed(a.round, a.ledger)
        out = ROOT / "results" / f"round{a.round}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, indent=1, default=str))
    rows = [
        (e, v["log_score"], v["rps"], v["log_vs_persistence"]["diff"], v["calibration"]["coverage"]["80"])
        for e, v in res["entries"].items()
    ]
    print("rows", res["rows"], "days", res["days"])
    for r in sorted(rows, key=lambda r: -r[1]):
        print("{:14s} log {:+.3f}  rps {:.3f}  vs copy {:+.3f}  cov80 {:.2f}".format(*r))
    lad = res["ladders"]
    print("ladders", lad.get("ladders"), "market bid log", round(lad.get("market_bid_log", 0), 3))
    for e in res["entries"]:
        if e in lad:
            x = lad[e]
            print(
                f"{e:14s} vs bid-market {metrics.fmt(x['log_vs_market_bid'])}"
                f"  pnl ${x['pnl']:+.0f} (1c slip ${x['pnl_slip1']:+.0f}) trades {x['trades']}"
            )
    for k, v in res["tests"].items():
        if not isinstance(v, dict):
            print(k, v)
        elif "verdict" in v:
            m = v.get("diff", v.get("mean"))
            print("{}: {:+.3f} [{:+.3f}, {:+.3f}] {}".format(k, m, *v["ci"], v["verdict"]))
        else:
            print(k, {e: "{:+.3f} {}".format(x["diff"], x["verdict"]) for e, x in v.items()})
    print("sha256", hashlib.sha256(out.read_bytes()).hexdigest()[:12], out)


if __name__ == "__main__":
    main()
