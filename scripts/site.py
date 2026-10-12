#!/usr/bin/env python3
"""Render the results page (physicalreasoning.ai/forward/) from results/*.json.

    uv run scripts/site.py [--out site/index.html]

Static HTML in the site's own style (serif text, monochrome, light only). Figures are SVG drawn
here, not in the browser, so the page needs no JavaScript and every number on it comes from the
same files as results/LEADERBOARD.md. Each figure carries a visually hidden table for screen
readers.
"""

from __future__ import annotations

import argparse
import html
import json
import math

from forward import ROOT

INK, MUTED, FAINT, ZERO = "#000", "#6B6B6B", "#E8E8E8", "#9A9A9A"
MONO = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace'

LABEL = {
    "emos-all": "blend of five, calibrated",
    "emos-aifs": "AIFS (learned), calibrated",
    "emos-icon": "ICON, calibrated",
    "emos-nbm": "NBM, calibrated",
    "emos-ifs": "IFS (physics), calibrated",
    "emos-gfs": "GFS, calibrated",
    "raw-icon": "ICON, raw",
    "raw-nbm": "NBM, raw",
    "raw-ifs": "IFS (physics), raw",
    "raw-gfs": "GFS, raw",
    "raw-aifs": "AIFS (learned), raw",
    "climatology": "climatology",
    "persistence": "copy yesterday",
    "copy": "copy the last price",
    "chronos-bolt-small": "Chronos-Bolt small",
    "chronos-bolt-base": "Chronos-Bolt base",
    "timesfm-2.5": "TimesFM 2.5",
    "chronos-bolt-small-centre": "Chronos-Bolt small, median",
    "chronos-bolt-base-centre": "Chronos-Bolt base, median",
    "timesfm-2.5-centre": "TimesFM 2.5, median",
}


def money(v: float, digits: int = 0) -> str:
    """-$40, +$0.021: the sign before the dollar."""
    return f"{'-' if v < 0 else '+'}${abs(v):,.{digits}f}"


def esc(s) -> str:
    return html.escape(str(s))


def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    span = hi - lo
    step = 10 ** math.floor(math.log10(span / n))
    for m in (1, 2, 2.5, 5, 10):
        if span / (step * m) <= n:
            step *= m
            break
    start = math.ceil(lo / step) * step
    return [round(start + i * step, 10) for i in range(int((hi - start) / step) + 1)]


def dot_whisker(rows, title: str, xlabel: str, highlight=()) -> str:
    """rows: (label, diff, lo, hi). Horizontal intervals around zero; one row per entry."""
    W, left, right, top, rh = 640, 250, 24, 30, 28
    H = top + rh * len(rows) + 52
    data = [r for r in rows if r[1] is not None]
    lo = min(0.0, *(r[2] for r in data))
    hi = max(0.0, *(r[3] for r in data))
    pad = (hi - lo) * 0.06
    lo, hi = lo - pad, hi + pad
    X = lambda v: left + (v - lo) / (hi - lo) * (W - left - right)  # noqa: E731
    out = [
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}" '
        f'style="width:100%;height:auto;display:block" font-family=\'{MONO}\' font-size="12">'
    ]
    for t in nice_ticks(lo, hi):
        out.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{top - 8}" y2="{H - 46}" stroke="{FAINT}"/>')
        out.append(
            f'<text x="{X(t):.1f}" y="{H - 28}" text-anchor="middle" fill="{MUTED}">{t:+.2f}</text>'
            if t
            else f'<text x="{X(t):.1f}" y="{H - 28}" text-anchor="middle" fill="{MUTED}">0</text>'
        )
    out.append(f'<line x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{top - 8}" y2="{H - 46}" stroke="{ZERO}"/>')
    out.append(f'<text x="{W - right}" y="{H - 2}" text-anchor="end" fill="{MUTED}">{esc(xlabel)}</text>')
    for i, (label, d, a, b) in enumerate(rows):
        y = top + rh * i + rh / 2
        if d is None:  # a group header
            out.append(f'<text x="0" y="{y + 4:.1f}" fill="{INK}" font-weight="600">{esc(label)}</text>')
            continue
        strong = label in highlight
        sig = a > 0 or b < 0
        out.append(
            f'<text x="{left - 14}" y="{y + 4:.1f}" text-anchor="end" fill="{INK if strong else MUTED}"'
            f"{' font-weight=' + chr(34) + '600' + chr(34) if strong else ''}>{esc(label)}</text>"
        )
        out.append(
            f'<line x1="{X(a):.1f}" x2="{X(b):.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="{INK}" stroke-width="2" '
            f'stroke-linecap="round"/>'
        )
        fill = INK if sig else "#fff"
        out.append(
            f'<circle cx="{X(d):.1f}" cy="{y:.1f}" r="4.5" fill="{fill}" stroke="{INK}" stroke-width="1.5"/>'
        )
    out.append("</svg>")
    return "".join(out)


def sr_table(rows, head) -> str:
    rows = [r for r in rows if r[1] is not None]
    body = "".join(
        f"<tr><td>{esc(r[0])}</td><td>{r[1]:+.3f}</td><td>{r[2]:+.3f}</td><td>{r[3]:+.3f}</td></tr>"
        for r in rows
    )
    return f'<table class="sr"><tr>{"".join(f"<th>{h}</th>" for h in head)}</tr>{body}</table>'


def fmt_ci(d) -> str:
    m = d.get("diff", d.get("mean"))
    lo, hi = d["ci"]
    if m == lo == hi == 0:
        return "baseline"
    return f"{m:+.3f} <span class=dim>[{lo:+.3f}, {hi:+.3f}]</span>"


def station_section(r) -> str:
    E = r["entries"]
    order = sorted(E, key=lambda e: -E[e]["log_vs_persistence"]["diff"])
    rows = [
        (LABEL.get(e, e), E[e]["log_vs_persistence"]["diff"], *E[e]["log_vs_persistence"]["ci"])
        for e in order
        if e != "persistence"
    ]
    fig = dot_whisker(
        rows,
        "Log score gain over copying yesterday, per station-day, with 95% intervals",
        "log score minus copy yesterday",
        highlight=(
            "AIFS (learned), calibrated",
            "IFS (physics), calibrated",
            "AIFS (learned), raw",
            "IFS (physics), raw",
        ),
    )
    t = r["tests"]
    lad = r["ladders"]
    table = "".join(
        f"<tr><td>{esc(LABEL.get(e, e))}</td><td>{E[e]['log_score']:.3f}</td>"
        f"<td>{E[e]['calibration']['coverage']['80']:.2f}</td><td>{lad[e]['log_vs_market_bid']['diff']:+.3f}</td>"
        f"<td>{money(lad[e]['pnl_slip1'])}</td></tr>"
        for e in sorted(E, key=lambda e: -E[e]["log_score"])
    )
    h1, h1r = t["H1_emos_aifs_minus_emos_ifs"], t["H1_secondary_raw_aifs_minus_raw_ifs"]
    h3, h4 = t["H3_emos_all_minus_bid_market"], t["H4_emos_all_pnl_per_ladder_slip1"]
    return f"""
    <h2>Task 1: tomorrow's high at 19 weather stations</h2>
    <p>Each entry gives a probability for every whole degree of the official high at the 19 NWS
    stations that settle Kalshi's temperature markets, read at 20:00 UTC the day before. The dry
    run covers {esc(r["window"][0])} to {esc(r["window"][1])}: {r["rows"]:,} station-days.</p>
    <figure>
      {fig}
      <figcaption>fig. 1: log score gain over copying yesterday's high, per station-day. filled dots:
      the 95% interval excludes zero. every model beats copying; calibration matters more than the model</figcaption>
      {sr_table(rows, ["entry", "gain", "low", "high"])}
    </figure>
    <p>ECMWF's learned model, AIFS, is worse than its physics model, IFS, as it comes out of the box
    ({h1r["diff"]:+.3f}, interval {h1r["ci"][0]:+.3f} to {h1r["ci"][1]:+.3f}). After the same simple
    calibration it is the better of the two by {h1["diff"]:+.3f} ({h1["ci"][0]:+.3f} to
    {h1["ci"][1]:+.3f}), and the best single model. A blend of all five is best overall, and still
    loses to the Kalshi market on the same ladders by {h3["diff"]:.3f} ({h3["ci"][0]:+.3f} to
    {h3["ci"][1]:+.3f}), even with the market priced at its bids. Trading it would have made
    {money(h4["mean"], 3)} per ladder after fees and a cent of slippage, an interval that includes zero.</p>
    <table class="stats wide">
      <tr><th>entry</th><th>log score</th><th>80% cover</th><th>vs market</th><th>P&amp;L</th></tr>
      {table}
    </table>
    <p class="note">log score per station-day, higher is better. 80% cover: share of outcomes inside the
    central 80% interval (0.80 is calibrated). vs market: log score minus Kalshi's ladder priced at its
    bids, on the same ladders; every interval excludes zero. P&amp;L: paper taker profit after fees and
    1&cent; of slippage, one contract per mispriced bucket. Full table with intervals:
    <a href="https://github.com/physicalreasoning/forward/blob/main/results/LEADERBOARD.md">LEADERBOARD.md</a>.</p>
    """


def price_section(r) -> str:
    rows, sr = [], []
    for lead, title in (("24h", "24 h before close"), ("6h", "6 h before close")):
        P = r[lead]["pooled"]
        rows.append((title, None, None, None))
        for e in ("chronos-bolt-small", "chronos-bolt-base", "timesfm-2.5"):
            for suffix in ("", "-centre"):
                v = P[e + suffix]["vs_copy"]
                rows.append((LABEL[e + suffix], v["diff"], *v["ci"]))
    sr = [(f"{x[0]}", *x[1:]) for x in rows]
    fig = dot_whisker(
        rows,
        "Log score gain over copying the last price, per ladder, with 95% intervals",
        "log score minus copy the last price",
    )
    d = r["direction"]
    hits = ", ".join(f"{LABEL[e]} {d[e]['hit_rate']:.1%}" for e in d)
    n24, n6 = r["24h"]["pooled"]["problems"], r["6h"]["pooled"]["problems"]
    cb = r["24h"]["pooled"]["copy"]
    return f"""
    <h2>Task 2: where a price closes</h2>
    <p>Kalshi lists daily ladders on the S&amp;P 500, the Nasdaq-100, EUR/USD, USD/JPY, WTI, Brent,
    gold, silver, copper and natural gas. Each entry sees the last 512 hourly prices of the
    underlying and gives a probability for every bucket, 24 or 6 hours before the close
    ({n24:,} and {n6:,} past ladders). The trivial answer is to copy the last price: centre on it,
    with the spread of past moves over the same hours. The entries are three released time-series
    foundation models from two families, Chronos-Bolt and TimesFM, used as published.</p>
    <figure>
      {fig}
      <figcaption>fig. 2: log score gain over copying the last price, per ladder. no foundation model
      is above zero. "median": the model's median with the copy baseline's spread; every one is below zero</figcaption>
      {sr_table(sr, ["entry", "gain", "low", "high"])}
    </figure>
    <p>None of them beats copying. Their predicted moves point the right way about half the time
    ({esc(hits)}), and keeping their direction while using the copy baseline's spread makes each
    one significantly worse. What they add to copying is noise. The copy baseline itself beats the
    market at its bid by {cb["vs_market_bid"]["diff"]:+.2f} a day out, and still does not make money
    after fees.</p>
    """


def page(station, prices_) -> str:
    css = (ROOT / "scripts" / "site.css").read_text()
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light only">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Sealed forward tests for world models: entries frozen before a round, scored only on outcomes that resolve after it, on six columns including skill against copying and against the market.">
<meta property="og:title" content="forward: sealed forward tests for world models">
<meta property="og:url" content="https://physicalreasoning.ai/forward/">
<meta property="og:image" content="https://physicalreasoning.ai/og.png">
<link rel="canonical" href="https://physicalreasoning.ai/forward/">
<link rel="icon" type="image/svg+xml" href="/logo.svg">
<title>forward · Physical Reasoning</title>
<style>
{css}
</style>
</head>
<body>
<div class="wrap">
  <nav>
    <a class="wordmark" href="/">[Pr]</a>
    <a class="back" href="https://github.com/physicalreasoning/forward">GitHub &rarr;</a>
  </nav>
  <article>
    <div class="meta">Benchmark &middot; generated from the results files</div>
    <h1>forward: sealed forward tests for world models</h1>
    <p>Every entry is frozen and hashed before a round opens, then scored only on outcomes that
    resolve after the freeze. Nothing can leak into training and nothing can be tuned after the
    fact. Each entry reports six columns: a proper score with honest intervals, calibration, skill
    against copying the last value, skill against the prediction market on the same outcome,
    paper profit after fees, and how much of any gain one month explains.</p>
    <p>The results below are dry runs on past data, through the same pipeline the sealed rounds
    use. Round 1 freezes on 31 October 2026 and scores November and December, with isotherm, our
    own model of these markets, entered live; Round 2 freezes on 3 January 2027. Their specs, with every hypothesis and pass rule, are public before any of
    their data exists.</p>
    {station_section(station)}
    {price_section(prices_)}
    <h2>Task 3: what an action would have done</h2>
    <p>The first two tasks score predictions of what happens on its own. A world model also has to
    say what would happen if we acted. Task 3 asks it about a limit order we did not place: would it
    have filled within 5 minutes, 30 minutes or 2 hours, and where did the price go next? We record
    Kalshi's order books ourselves, and a matching engine is deterministic, so replaying the record
    gives every such action a known outcome (assuming nobody reacts to our order, which the record
    cannot show). The first pipeline check uses one day of recordings, too little for a result; the
    design and a draft spec are in
    <a href="https://github.com/physicalreasoning/forward/blob/main/docs/TASK3_FILLS.md">TASK3_FILLS.md</a>.</p>
    <h2>How the seal works</h2>
    <ol class="steps">
      <li><b>Freeze.</b> Fit every entry on data settled by the cutoff; record the sha256 of the
      parameters, the spec and every scoring file; push before the first read.</li>
      <li><b>Capture.</b> At each read, write the live model runs and commit them to a public
      branch. A capture after 22:00 UTC the day before does not count.</li>
      <li><b>Score.</b> After the window, refuse if any hash changed; score on truth published
      after the outcomes; publish the result, including failures.</li>
    </ol>
    <p class="coda">Code, specs, methods and every result file:
    <a href="https://github.com/physicalreasoning/forward">github.com/physicalreasoning/forward</a>.
    Methods: <a href="https://github.com/physicalreasoning/forward/blob/main/docs/METHODS.md">METHODS.md</a>.
    Full tables: <a href="https://github.com/physicalreasoning/forward/blob/main/results/LEADERBOARD.md">LEADERBOARD.md</a>.
    Weather data by <a href="https://open-meteo.com/">Open-Meteo.com</a> (CC BY 4.0), from ECMWF
    (AIFS, IFS; &copy; ECMWF, CC BY 4.0), DWD (ICON, CC BY 4.0) and NOAA (GFS, NBM). Truth from NWS
    climate reports via the Iowa Environmental Mesonet. Market data is used for scoring and not
    republished: <a href="https://github.com/physicalreasoning/forward/blob/main/docs/DATA_TERMS.md">DATA_TERMS.md</a>.</p>
  </article>
  <footer>&copy; 2026 Physical Reasoning</footer>
</div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "site" / "index.html"))
    a = ap.parse_args()
    res = ROOT / "results"
    station = json.loads((res / "round0_dry_run.json").read_text())
    prices_ = json.loads((res / "prices_dry_run.json").read_text())
    out = ROOT.joinpath(a.out) if not a.out.startswith("/") else __import__("pathlib").Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(station, prices_))
    print(out)


if __name__ == "__main__":
    main()
