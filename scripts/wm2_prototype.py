#!/usr/bin/env python3
"""WM-2 prototype: three baselines on MRMS rain-rate tiles over a few days, scored end to end.

    uv run scripts/wm2_prototype.py [--first 2026-10-14] [--days 4] [--hours 0,6,12,18]

1. Capture every frame the baselines and the truth need (forward/wm2/store.py), from the public
   NOAA MRMS bucket; tiles and manifests go to data/wm2/tiles (gitignored).
2. Run each baseline (forward/wm2/baselines.py) at each init through the input shim and WM-1's
   guard, recording each forecast's sha256 and the time it took.
3. Score each init on the truth (forward/wm2/evaluate.py), pool, and write
   results/wm2/wm2_prototype.json, docs/WM2_PROTOTYPE.md and docs/wm2_prototype.svg.

A prototype, not a result: the baselines were written after these days, the days were chosen
after looking at their rain, and four days cannot support any comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time

import numpy as np
import pandas as pd

from forward import DATA, ROOT
from forward.wm.runner import npy_bytes
from forward.wm2 import access, baselines, evaluate, mrms, truth

sys.path.insert(0, str(ROOT / "scripts"))
from capture_wm2 import DEFAULT_STATIONS, store_for  # noqa: E402

FIRST = "2026-10-14"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", default=FIRST)
    ap.add_argument("--days", type=int, default=4)
    ap.add_argument("--hours", default="0,6,12,18")
    ap.add_argument("--stations", default=DEFAULT_STATIONS)
    a = ap.parse_args()
    stations = a.stations.split(",")
    days = pd.date_range(a.first, periods=a.days)
    inits = [d + pd.Timedelta(hours=int(h)) for d in days for h in a.hours.split(",")]
    root = DATA / "wm2" / "tiles"
    st = store_for(stations, root)
    t = time.time()
    cap = st.capture(baselines.needed_times(inits))
    cap["seconds"] = round(time.time() - t, 1)
    access.protect(root)
    off = (mrms.CONTEXT - mrms.TARGET) // 2
    points = []
    for tl in st.tiles:
        r, c = tl.station_rc[0] - off, tl.station_rc[1] - off
        points.append((r, c) if 0 <= r < mrms.TARGET and 0 <= c < mrms.TARGET else None)

    stats, dates, recs, secs = [], [], {}, {n: 0.0 for n in baselines.ENTRIES}
    for t0 in inits:
        fc = {}
        for name, f in baselines.ENTRIES.items():
            inp = access.Inputs(t0, st)
            s = time.time()
            with access.guard():
                x = np.asarray(f(inp.init_time, stations, inp), dtype=np.float32)
            secs[name] += time.time() - s
            fc[name] = x
            recs.setdefault(name, []).append(
                {
                    "init_time": str(t0),
                    "sha256": hashlib.sha256(npy_bytes(x)).hexdigest(),
                    "nan_share": float(np.isnan(x).mean()),
                    "reads": len(inp.log),
                }
            )
        y = truth.truth(t0, st)
        stats.append(evaluate.init_stats(fc, y, points))
        dates.append(str(t0.date()))
        print(t0, "cells", stats[-1]["cells"], flush=True)
    res = evaluate.combine(stats, dates, baselines.LEADS)
    shape = (baselines.K, len(stations), len(baselines.LEADS), mrms.TARGET, mrms.TARGET)
    res.update(
        generated_at=pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        stations=stations,
        init_times=[str(t) for t in inits],
        K=baselines.K,
        forecast_shape=list(shape),
        forecast_mb=float(np.prod(shape) * 4 / 1e6),
        capture=cap,
        captures={d: st._load_day(d)[0].get("sha256") for d in st.days()},
        tile_bytes=sum((root / f"{d}.npz").stat().st_size for d in st.days()),
        frames_stored=len(st.times()),
        predict_seconds={n: round(v, 1) for n, v in secs.items()},
        forecasts=recs,
        wet_share_by_init=[
            [
                s["wet"][li][0] / s["wet"][li][1] if s["wet"][li][1] else None
                for li in range(len(baselines.LEADS))
            ]
            for s in stats
        ],
    )
    (ROOT / "results" / "wm2").mkdir(parents=True, exist_ok=True)
    (ROOT / "results" / "wm2" / "wm2_prototype.json").write_text(json.dumps(res, indent=1) + "\n")
    (ROOT / "docs" / "wm2_prototype.svg").write_text(figure(res))
    (ROOT / "docs" / "WM2_PROTOTYPE.md").write_text(report(res))
    print("wrote results/wm2/wm2_prototype.json docs/WM2_PROTOTYPE.md docs/wm2_prototype.svg")


# Figure ------------------------------------------------------------------------------------

COLORS = {  # categorical slots, light and dark steps (as docs/wm1_dryrun.svg)
    "persistence": ("#eb6834", "#d95926"),
    "climatology": ("#2a78d6", "#3987e5"),
    "advection": ("#1baf7a", "#199e70"),
}


def _panel(out, x0, y0, pw, ph, series, ymax, step, fmt, title, leads):
    xmax = max(leads)
    xs = lambda m: x0 + (m / xmax) * pw
    ys = lambda v: y0 + (1 - v / ymax) * ph
    out.append(f'<text class="ink" x="{x0}" y="{y0 - 10}" font-weight="600">{title}</text>')
    for i in range(int(round(ymax / step)) + 1):
        v = i * step
        out.append(f'<line class="grid" x1="{x0}" x2="{x0 + pw}" y1="{ys(v):.1f}" y2="{ys(v):.1f}"/>')
        out.append(
            f'<text class="mute" x="{x0 - 6}" y="{ys(v) + 4:.1f}" text-anchor="end">{fmt.format(v)}</text>'
        )
    for m in (0, 60, 120, 180, 240, 300, 360):
        out.append(f'<text class="mute" x="{xs(m):.1f}" y="{y0 + ph + 18}" text-anchor="middle">{m}</text>')
    out.append(
        f'<text class="mute" x="{x0 + pw / 2:.1f}" y="{y0 + ph + 36}" text-anchor="middle">'
        "lead (minutes after the init)</text>"
    )
    labels = []
    for i, (name, s) in enumerate(series.items()):
        p = [(xs(m), ys(v)) for m, v in zip(leads, s, strict=True) if v is not None]
        if not p:
            continue
        d = " ".join(f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}" for j, (x, y) in enumerate(p))
        out.append(f'<path class="s{i}" d="{d}" fill="none" stroke-width="2" stroke-linejoin="round"/>')
        out += [f'<circle class="f{i}" cx="{x:.1f}" cy="{y:.1f}" r="3"/>' for x, y in p]
        labels.append([p[-1][1], p[-1][0], name])
    labels.sort()
    for j in range(1, len(labels)):
        labels[j][0] = max(labels[j][0], labels[j - 1][0] + 15)
    out += [f'<text class="ink" x="{x + 8:.1f}" y="{y + 4:.1f}">{n}</text>' for y, x, n in labels]


def figure(res: dict) -> str:
    """Two panels: fair CRPS at 8 km pooling, and FSS at 1 mm/h over 34 km, by lead."""
    w, h = 960, 400
    leads = res["leads"]
    crps = {n: e["crps_4"] for n, e in res["entries"].items()}
    fss = {n: e["fss_1_17"] for n, e in res["entries"].items()}
    cmax = max(v for s in crps.values() for v in s if v is not None)
    cstep = 0.05 if cmax < 0.3 else 0.1
    cmax = cstep * np.ceil(cmax * 1.05 / cstep)
    css = "".join(f".s{i}{{stroke:{c[0]}}}.f{i}{{fill:{c[0]}}}" for i, c in enumerate(COLORS.values()))
    css_dark = "".join(f".s{i}{{stroke:{c[1]}}}.f{i}{{fill:{c[1]}}}" for i, c in enumerate(COLORS.values()))
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        'font-family="system-ui, sans-serif" font-size="12">',
        "<style>.bg{fill:#fcfcfb}.ink{fill:#0b0b0b}.mute{fill:#52514e}.grid{stroke:#e4e3df}"
        + css
        + "@media (prefers-color-scheme: dark){"
        ".bg{fill:#1a1a19}.ink{fill:#f0efec}.mute{fill:#c3c2b7}.grid{stroke:#3a3a37}"
        + css_dark
        + "}</style>",
        f'<rect class="bg" width="{w}" height="{h}"/>',
        '<text class="ink" x="48" y="24" font-size="14" font-weight="600">'
        f"WM-2 prototype, not a result: {len(res['stations'])} tiles, {res['inits']} inits, "
        f"{res['init_times'][0][:10]} to {res['init_times'][-1][:10]}</text>",
    ]
    _panel(
        out,
        52,
        72,
        300,
        250,
        crps,
        cmax,
        cstep,
        "{:.2f}",
        "Fair CRPS, 8 km pooling (mm/h, lower is better)",
        leads,
    )
    _panel(out, 530, 72, 300, 250, fss, 1.0, 0.2, "{:.1f}", "FSS, 1 mm/h, 34 km (higher is better)", leads)
    out.append("</svg>\n")
    return "\n".join(out)


# Report ------------------------------------------------------------------------------------


def _v(x, f="{:.3f}"):
    return "n/a" if x is None else f.format(x)


def _ci(v, ci, f="{:.3f}"):
    return _v(v, f) if ci is None else f"{f.format(v)} [{f.format(ci[0])}, {f.format(ci[1])}]"


def report(res: dict) -> str:
    names = list(res["entries"])
    leads = res["leads"]
    when = pd.Timestamp(res["generated_at"]).strftime("%Y-%m-%d %H:%M UTC")
    E = res["entries"]
    cap = res["capture"]
    L = [
        "# WM-2 prototype",
        "",
        "**A prototype, not a result.** "
        f"{res['inits']} inits (00, 06, 12 and 18 UTC on {res['init_times'][0][:10]} to "
        f"{res['init_times'][-1][:10]}), {len(res['stations'])} tiles around the stations "
        f"{', '.join(res['stations'])}. The baselines were written after these days and the days were "
        "picked after looking at October's 24 h rain totals (rain in several tiles), so the sample is "
        "selected on the outcome; four days cannot support any comparison, and the intervals "
        "(resampling whole init dates) are printed to exercise the code. Generated by "
        f"`uv run scripts/wm2_prototype.py` at {when}; numbers in `results/wm2/wm2_prototype.json`.",
        "",
        "Task, truth and scores: [WM2_DRAFT.md](WM2_DRAFT.md). Each entry submits "
        f"K = {res['K']} joint samples of the MRMS rain rate (mm/h) on each tile's central 128 x 128 "
        "box at 0.02 deg (about 2 km; about 285 x 218 km at 40 N) for leads of 10 minutes to 6 hours; "
        "truth is the MRMS PrecipRate frame valid at each lead. Every score is computed on the same "
        "pixels for every entry.",
        "",
        "## Entries",
        "",
        "| Entry | What it is | Reads |",
        "| --- | --- | --- |",
        "| `persistence` | the latest frame before the init (init - 10 min), the same in every sample | 3 frames |",
        "| `climatology` | the sequences observed at the same time of day in the past four years, offsets up to two days (20 analogues) | 200 frames |",
        "| `advection` | the latest frame moved along one cross-correlation motion vector per tile, perturbed per sample | 3 frames |",
        "",
        "## How much rain there was",
        "",
        "Share of scored pixels at or above 0.1 mm/h, by lead (pooled over inits and tiles): "
        + ", ".join(f"{m} min {_v(v, '{:.2f}')}" for m, v in zip(leads, res["wet_share"], strict=True))
        + f". {res['cells']:,} pixel-leads were scored, the same for every entry.",
        "",
        "## Fair CRPS (mm/h) by pooling scale and lead",
        "",
        "Fair CRPS of the rain rate averaged over s x s pixels (1, 4, 16: 2, 8 and 32 km), mean over "
        "pooled cells, date-block 95% interval. Lower is better.",
        "",
    ]
    for p in evaluate.POOLS:
        L += [f"**{2 * p} km**", "", "| Lead (min) | " + " | ".join(f"`{n}`" for n in names) + " |"]
        L.append("| --- |" + " --- |" * len(names))
        for li, m in enumerate(leads):
            row = [_ci(E[n][f"crps_{p}"][li], E[n][f"crps_{p}_ci"][li]) for n in names]
            L.append(f"| {m} | " + " | ".join(row) + " |")
        L.append("")
    L += [
        "## Energy score and station pixel",
        "",
        "Fair energy score of each tile's field averaged to 32 km (64 numbers, mm/h), mean over (init, "
        "tile) rows; and fair CRPS at the station's own pixel (mm/h). Rows are the same for every entry.",
        "",
        "| Lead (min) | Rows | "
        + " | ".join(f"`{n}` energy" for n in names)
        + " | "
        + " | ".join(f"`{n}` station" for n in names)
        + " |",
        "| --- | --- |" + " --- |" * (2 * len(names)),
    ]
    for li, m in enumerate(leads):
        L.append(
            f"| {m} | {E[names[0]]['energy_rows'][li]} | "
            + " | ".join(_v(E[n]["energy"][li]) for n in names)
            + " | "
            + " | ".join(_v(E[n]["station"][li], "{:.4f}") for n in names)
            + " |"
        )
    L += [
        "",
        "## Fractions skill score",
        "",
        "FSS (Roberts and Lean 2008) of the ensemble's neighbourhood exceedance probability, summed over "
        "inits and tiles before the ratio. Higher is better; 1 is perfect. Not proper, so reported, "
        "never ranked on.",
        "",
        "| Lead (min) | " + " | ".join(f"`{n}` 1 mm/h, 2 / 10 / 34 km" for n in names) + " |",
        "| --- |" + " --- |" * len(names),
    ]
    for li, m in enumerate(leads):
        L.append(
            f"| {m} | "
            + " | ".join(
                " / ".join(_v(E[n][f"fss_1_{k}"][li], "{:.2f}") for k in evaluate.NEIGHBOURHOODS)
                for n in names
            )
            + " |"
        )
    L += [
        "",
        "| Lead (min) | " + " | ".join(f"`{n}` 4 mm/h, 2 / 10 / 34 km" for n in names) + " |",
        "| --- |" + " --- |" * len(names),
    ]
    for li, m in enumerate(leads):
        L.append(
            f"| {m} | "
            + " | ".join(
                " / ".join(_v(E[n][f"fss_4_{k}"][li], "{:.2f}") for k in evaluate.NEIGHBOURHOODS)
                for n in names
            )
            + " |"
        )
    L += [
        "",
        "![Fair CRPS and FSS by lead](wm2_prototype.svg)",
        "",
        "## Cost of this run",
        "",
        f"- Capture: {cap['requested']} frames requested, {cap['fetched']} fetched, "
        f"{len(cap['missing'])} not in the bucket, {cap['bytes'] / 1e6:,.0f} MB downloaded "
        f"in {cap['seconds']:.0f} s (6 threads, one laptop CPU; 0 means already captured).",
        f"- Stored: {res['frames_stored']} frames of {len(res['stations'])} tiles in "
        f"{res['tile_bytes'] / 1e6:.1f} MB of compressed uint16.",
        "- Predict, all inits: "
        + ", ".join(f"`{n}` {s:.0f} s" for n, s in res["predict_seconds"].items())
        + ". One forecast is "
        f"{' x '.join(map(str, res['forecast_shape']))} float32, {res['forecast_mb']:.0f} MB before compression.",
        "",
    ]
    L += FINDINGS
    L += DATA_NOTE
    return "\n".join(L)


FINDINGS = [
    "## Findings (about the pipeline)",
    "",
    "1. **Data volume is small.** One CONUS PrecipRate file is about 0.5 MB gzipped (350 MB a day at",
    "   the native 2-minute cadence). At a 10-minute cadence a day is 144 files, about 64 MB to",
    "   download and 12 s to fetch, decode and cut on one laptop; the 19 station tiles of that day",
    "   (2026-10-29) stored in 8.1 MB. A 56-day round is about 3.6 GB downloaded and 0.5 GB kept.",
    "2. **The archive is the backup.** Unlike Open-Meteo's ensembles, MRMS is kept on the bucket",
    "   back to 2020-10-14, so a missed capture loses nothing and an analogue climatology can be",
    "   built from past years without having captured them. Over the 30 days to 2026-10-29, 18 of",
    "   4,320 ten-minute frames were absent (0.4%), clustered in short outages (9 on 2026-10-07);",
    "   in this sample 2 of 1,808 frames were absent, which drops one lead of the first init for",
    "   every entry. One request to the bucket timed out during the TLS handshake in the first run;",
    "   reads now retry transient network errors (an absent file is an answer, not retried).",
    "3. **The context box limits long leads.** `advection` beats `persistence` on pooled CRPS at",
    "   every lead and on FSS for the first 2 to 3 h, then falls below it: rain moved in from outside the",
    "   256-pixel context box is unknown and set to zero, and with 128 km of margin each side and",
    "   tile motions of 40 to 70 km/h (median, rainy tiles) the box empties after 2 to 3 h. A 6 h",
    "   lead needs about 400 km of upstream context; the draft serves a 512-pixel box (about",
    "   1,000 km) and makes 3 h the primary horizon (WM2_DRAFT.md).",
    "4. **Per-pixel CRPS rewards dry hedging.** About 8% of scored pixels were wet. `climatology`",
    "   has almost no skill on FSS (about 0.05) yet is close to `advection` on pixel CRPS at long",
    "   leads, because samples that are mostly dry are cheap where it is dry. The draft ranks on",
    "   the energy score of the 32 km field and on threshold-weighted CRPS, and reports pixel CRPS",
    "   and FSS.",
    "5. **Forecasts are the cost driver, not inputs.** One forecast of 6 tiles is 79 MB as",
    "   float32; quantised to 0.1 mm/h (MRMS's own precision) and compressed it was 1.2 to 2.6 MB.",
    "   At 19 tiles and four inits a day a round is about 1 to 2 GB per entry, which fits release",
    "   assets; the draft makes uint16 tenths of mm/h the submission format.",
    "6. **CPU is enough for the baselines and the scoring.** Every number here was computed on",
    "   one laptop CPU; a learned entry (e.g. DGMR) would need a GPU to train, not to score.",
    "7. **Hashes, not yet the sealed runner.** Every day file is checked against its manifest's",
    "   sha256 before use and each forecast's sha256 is recorded, but the baselines were called",
    "   directly: WM-1's manifest runner accepts only the inputs `truth` and `ensembles`, and WM-1",
    "   is left unchanged. Admitting `radar` there is part of building WM-2 proper.",
    "",
]

DATA_NOTE = [
    "## Data",
    "",
    "Radar: NOAA Multi-Radar/Multi-Sensor System (MRMS; Zhang et al. 2016), product PrecipRate, read "
    "from the NOAA Open Data Dissemination bucket `s3://noaa-mrms-pds` on the AWS Open Data Registry. "
    "NOAA data disseminated through NODD are open to the public and can be used as desired; NOAA "
    "requests attribution. The values here were modified (averaged to 0.02 deg, cut to tiles, "
    "quantised to 0.1 mm/h, forecast and scored) by Physical Reasoning; they are not original, "
    "unaltered NOAA data, and nothing here is endorsed by NOAA. Only aggregate scores are published; "
    "the tiles stay under data/ (gitignored).",
    "",
]


if __name__ == "__main__":
    main()
