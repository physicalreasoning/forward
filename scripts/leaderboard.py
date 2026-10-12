#!/usr/bin/env python3
"""Write results/LEADERBOARD.md from the result files, so the tables cannot drift from the data.

    uv run scripts/leaderboard.py

Reads every results/*.json that a scorer wrote: station-high results (score.py) and price-ladder
results (score_prices.py). Each table is sorted by log score, best first. A difference is shown
with its 95% date-block interval; one whose interval excludes zero is in bold.
"""

from __future__ import annotations

import json

from forward import ROOT

OUT = ROOT / "results" / "LEADERBOARD.md"


def ci(d: dict, digits: int = 3, bold: bool = True) -> str:
    m = d.get("diff", d.get("mean"))
    lo, hi = d["ci"]
    if m == lo == hi == 0:
        return "baseline"
    s = f"{m:+.{digits}f} [{lo:+.{digits}f}, {hi:+.{digits}f}]"
    return f"**{s}**" if bold and (lo > 0 or hi < 0) else s


def station_table(r: dict) -> list[str]:
    lad = r.get("ladders", {})
    rows = sorted(r["entries"].items(), key=lambda kv: -kv[1]["log_score"])
    out = [
        "| Entry | Log score | RPS | vs copy | vs climatology | 80% coverage | PIT error "
        "| vs bid market | P&L, 1c slip | Month share |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e, v in rows:
        x = lad.get(e, {})
        mkt = ci(x["log_vs_market_bid"]) if x else ""
        pnl = f"${x['pnl_slip1']:+,.0f}" if x else ""
        out.append(
            f"| {e} | {v['log_score']:.3f} | {v['rps']:.3f} | {ci(v['log_vs_persistence'])} "
            f"| {ci(v['log_vs_climatology'])} | {v['calibration']['coverage']['80']:.2f} "
            f"| {v['calibration']['pit_flatness_error']:.3f} | {mkt} | {pnl} "
            f"| {v['month_share_of_gain_vs_persistence']:.2f} |"
        )
    if lad:
        out.append("")
        out.append(
            f"Market reference on the same {lad['ladders']:,} ladders: bid-priced log score "
            f"{lad['market_bid_log']:.3f}, mid-priced {lad['market_mid_log']:.3f}."
        )
    return out


def common_table(r: dict) -> list[str]:
    """Every entry, gaussian and ladder kind, on the same ladders: those all of them forecast."""
    c = r.get("ladders_common", {})
    if not c.get("entries"):
        return []
    ladder_only = [e for e, k in c["entries"].items() if k == "ladder"]
    rows = sorted(c["entries"], key=lambda e: -c[e]["log_vs_market_bid"]["diff"])
    out = [
        f"### Every entry on the {c['ladders']:,} ladders {', '.join(ladder_only)} also covers",
        "",
        f"Ladder entries ({', '.join(ladder_only)}) give bucket probabilities only, so the integer-grid "
        "columns above do not apply to them.",
        "",
        "| Entry | Kind | vs bid market | vs mid market | P&L, 1c slip | P&L per ladder, 1c slip |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for e in rows:
        x = c[e]
        out.append(
            f"| {e} | {c['entries'][e]} | {ci(x['log_vs_market_bid'])} | {ci(x['log_vs_market_mid'])} "
            f"| ${x['pnl_slip1']:+,.0f} | {ci(x['pnl_slip1_per_ladder'])} |"
        )
    out += [
        "",
        f"Market reference on these ladders: bid-priced log score {c['market_bid_log']:.3f}, "
        f"mid-priced {c['market_mid_log']:.3f}.",
    ]
    return out


def tests_list(r: dict) -> list[str]:
    out = []
    for k, v in r.get("tests", {}).items():
        if not isinstance(v, dict):
            out.append(f"- {k}: {v}")
        elif "verdict" in v:
            out.append(f"- **{k}**: {ci(v)}, {v['verdict']}")
        else:
            parts = [f"{e} {x['diff']:+.3f} {x['verdict']}" for e, x in v.items()]
            out.append(f"- **{k}**: " + "; ".join(parts))
    return out


def price_table(r: dict, lead: str) -> list[str]:
    P = r[lead]["pooled"]
    d = r.get("direction", {})
    rows = sorted(((e, v) for e, v in P.items() if isinstance(v, dict)), key=lambda kv: -kv[1]["log_score"])
    out = [
        f"{P['problems']:,} ladders over {P['days']} days.",
        "",
        "| Entry | Log score | vs copy | vs bid market | vs mid market | P&L, 1c slip | Direction hit rate |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e, v in rows:
        pnl = f"${v['pnl_slip1']:+,.0f}" if "pnl_slip1" in v else ""
        hit = f"{d[e]['hit_rate']:.1%}" if e in d and d[e]["hit_rate"] is not None else ""
        out.append(
            f"| {e} | {v['log_score']:.3f} | {ci(v['vs_copy'])} | {ci(v['vs_market_bid'])} "
            f"| {ci(v['vs_market_mid'])} | {pnl} | {hit} |"
        )
    return out


def fills_table(r: dict) -> list[str]:
    """Task 3: log score of each fill model minus the base rate, by horizon."""
    hs = list(r["horizons"])
    models = list(r["horizons"][hs[0]]["models"])
    out = [
        f"Recorded {r['record']['hours_recorded']:.1f} h, "
        f"{r['record']['hours_clean']:.1f} h clean, {r['record']['markets']:,} markets.",
        "",
        "| Entry | " + " | ".join(f"{h}: log score minus base rate" for h in hs) + " |",
        "| --- |" + " --- |" * len(hs),
    ]
    for m in models:
        cells = []
        for h in hs:
            x = r["horizons"][h]["models"][m]
            d = x.get("log_score_minus_base_rate")
            cells.append("baseline" if m == "base-rate" or d is None else ci(d, bold=False))
        out.append(f"| {m} | " + " | ".join(cells) + " |")
    rates = ", ".join(f"{h} {r['horizons'][h]['fill_rate']['mean']:.1%}" for h in hs)
    out += [
        "",
        f"Fill rate of the sampled orders: {rates}. Intervals use hour blocks and are not yet meaningful.",
    ]
    return out


def main():
    lines = [
        "# Leaderboard",
        "",
        "Generated by `scripts/leaderboard.py` from `results/*.json`; do not edit by hand.",
        "Differences are per row (station-day or ladder) with 95% date-block intervals; bold intervals",
        "exclude zero. Log score: higher is better. RPS: lower is better.",
        "",
    ]
    results = [(f, json.loads(f.read_text())) for f in sorted((ROOT / "results").glob("*.json"))]
    results.sort(key=lambda fr: 0 if "entries" in fr[1] else 2 if "horizons" in fr[1] else 1)
    for f, r in results:
        if "entries" in r:
            w = r.get("window", ["", ""])
            lines += [f"## Task 1, station highs: {r['kind']}", ""]
            lines += [f"`{f.name}`, {w[0]} to {w[1]}, {r['rows']:,} station-days, inputs: {r['inputs']}.", ""]
            lines += station_table(r) + [""]
            if common := common_table(r):
                lines += common + [""]
            if r.get("tests"):
                lines += ["Pre-registered tests:", ""] + tests_list(r) + [""]
        elif "horizons" in r:
            lines += [f"## Task 3, fills under intervention: {r['status']}", "", f"`{f.name}`.", ""]
            lines += fills_table(r) + [""]
        elif "24h" in r:
            lines += [f"## Task 2, price ladders: {r['kind']}", "", f"`{f.name}`.", ""]
            for lead in ("24h", "6h"):
                if lead in r:
                    lines += [f"### {lead} before close", ""] + price_table(r, lead) + [""]
    OUT.write_text("\n".join(lines).rstrip() + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
