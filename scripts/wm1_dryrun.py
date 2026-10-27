#!/usr/bin/env python3
"""WM-1 dry run: every baseline entry at every captured read so far, scored on the truth so far.

    uv run scripts/wm1_dryrun.py [--first 2026-10-23] [--last YYYY-MM-DD]

1. Download each read's manifest (ledger-wm branch) and trajectories (wm-ledger release) into
   data/wm/captures, refusing any whose sha256 differs from its manifest.
2. Fetch hourly ASOS truth (forward/wm/truth.py) for the past ten years and this year.
3. Run each entry in entries/wm1 through the hash-checking runner (forward/wm/runner.py) at
   20:00 UTC on each read's day, writing forecasts and their sha256 to data/wm1/forecasts.
4. Score what has verified (forward/wm/evaluate.py) and write results/wm/wm1_dryrun.json,
   docs/WM1_DRYRUN.md and docs/wm1_dryrun.svg.

A dry run, not a result: the entries are not sealed before these reads (the runner is called
without a deadline), and a handful of inits cannot support any comparison.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json

import numpy as np
import pandas as pd

from forward import DATA, ROOT
from forward.stations import STATIONS
from forward.wm import access, baselines, captures, entry, evaluate, runner, truth

ENTRIES = ["climatology", "persistence", "raw", "emos-ecc"]
FIRST = "2026-10-23"


def load_truth(years) -> dict[str, pd.Series]:
    return {k: truth.hourly(s.icao, years).rename(k) for k, s in STATIONS.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", default=FIRST)
    ap.add_argument("--last", default=None, help="last read day (default: the latest captured)")
    a = ap.parse_args()
    now = pd.Timestamp.now(tz="UTC")
    last = pd.Timestamp(a.last) if a.last else (now - pd.Timedelta(hours=22)).normalize().tz_localize(None)
    days = [str(d.date()) for d in pd.date_range(a.first, last)]
    cap_dir = DATA / "wm" / "captures"
    captures.download(days, cap_dir)
    store = captures.Store(cap_dir)
    for d in store.days():
        store.load(d)  # checks every sha256 before anything runs
    access.protect(cap_dir)
    years = range(now.year - baselines.YEARS, now.year + 1)
    tr = load_truth(years)
    truth_asof = max(s.index.max() for s in tr.values())
    stations = list(STATIONS)
    inits = [pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=20) for d in days]

    fc, recs = {}, {}
    for name in ENTRIES:
        e = entry.load(ROOT / "entries" / "wm1" / name)
        xs = []
        for t in inits:
            x, rec = runner.run(e, t, stations, truth=tr, captures=store, out=DATA / "wm1" / "forecasts")
            xs.append(x[..., 0])
            recs.setdefault(name, []).append(
                {
                    k: rec[k]
                    for k in ("init_time", "forecast_sha256", "manifest_sha256", "code_sha256", "nan_share")
                }
            )
        fc[name] = np.stack(xs)  # [init, K, station, lead]
    y = np.stack(
        [
            np.stack([tr[s].reindex(baselines.lead_times(t)).to_numpy(dtype=float) for s in stations])
            for t in inits
        ]
    )
    res = evaluate.score(fc, y, days)
    res.update(
        generated_at=now.isoformat(timespec="seconds"),
        truth_asof=str(truth_asof),
        inits=days,
        stations=stations,
        captures={str(d.date()): store.manifest(d)["sha256"] for d in store.days() if str(d.date()) in days},
        forecasts=recs,
        lead_coverage={name: int(np.isfinite(fc[name]).all(axis=(0, 1, 2)).sum()) for name in fc},
        verified_hours_by_init={d: int(np.isfinite(y[i]).all(axis=0).sum()) for i, d in enumerate(days)},
    )
    (ROOT / "results" / "wm").mkdir(exist_ok=True)
    (ROOT / "results" / "wm" / "wm1_dryrun.json").write_text(json.dumps(res, indent=1) + "\n")
    (ROOT / "docs" / "wm1_dryrun.svg").write_text(figure(res))
    (ROOT / "docs" / "WM1_DRYRUN.md").write_text(report(res))
    print("wrote results/wm/wm1_dryrun.json docs/WM1_DRYRUN.md docs/wm1_dryrun.svg")


# Figure ------------------------------------------------------------------------------------

COLORS = {  # categorical slots 1 to 4, light and dark steps
    "climatology": ("#2a78d6", "#3987e5"),
    "persistence": ("#eb6834", "#d95926"),
    "raw": ("#1baf7a", "#199e70"),
    "emos-ecc": ("#eda100", "#c98500"),
}


def figure(res: dict) -> str:
    """Fair CRPS by lead (6 h bins) for each entry over the full 168 h, marking the leads not yet
    verified and where the captures end; a standalone SVG with light and dark modes."""
    w, h, ml, mr, mt, mb = 760, 380, 48, 110, 44, 46
    series = {n: e["crps_by_lead"] for n, e in res["entries"].items()}
    pts = [v for s in series.values() for v in s if v is not None]
    step = 1.0
    ymax = step * np.ceil((max(pts) if pts else 1) * 1.05 / step)
    last_bin = max((i for s in series.values() for i, v in enumerate(s) if v is not None), default=0)
    verified = (last_bin + 1) * evaluate.LEAD_BIN
    cap_end = min(res["lead_coverage"].values())
    xmax = baselines.LEADS
    xs = lambda lead: ml + (lead / xmax) * (w - ml - mr)
    ys = lambda v: mt + (1 - v / ymax) * (h - mt - mb)
    css = "".join(f".s{i}{{stroke:{c[0]}}}.f{i}{{fill:{c[0]}}}" for i, c in enumerate(COLORS.values()))
    css_dark = "".join(f".s{i}{{stroke:{c[1]}}}.f{i}{{fill:{c[1]}}}" for i, c in enumerate(COLORS.values()))
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        'font-family="system-ui, sans-serif" font-size="12">',
        "<style>.bg{fill:#fcfcfb}.ink{fill:#0b0b0b}.mute{fill:#52514e}.grid{stroke:#e4e3df}"
        ".band{fill:#f0efec}.rule{stroke:#52514e}" + css + "@media (prefers-color-scheme: dark){"
        ".bg{fill:#1a1a19}.ink{fill:#f0efec}.mute{fill:#c3c2b7}.grid{stroke:#3a3a37}.band{fill:#262624}"
        ".rule{stroke:#c3c2b7}" + css_dark + "}</style>",
        f'<rect class="bg" width="{w}" height="{h}"/>',
        f'<text class="ink" x="{ml}" y="22" font-size="14" font-weight="600">'
        "Fair CRPS (deg F) by lead: WM-1 dry run, a pipeline check, not a result</text>",
        f'<rect class="band" x="{xs(verified):.1f}" y="{mt}" '
        f'width="{xs(xmax) - xs(verified):.1f}" height="{h - mt - mb}"/>',
        f'<text class="mute" x="{(xs(verified) + xs(xmax)) / 2:.1f}" y="{mt + 16}" text-anchor="middle">'
        "no truth yet</text>",
    ]
    for i in range(int(ymax / step) + 1):
        v = i * step
        out.append(f'<line class="grid" x1="{ml}" x2="{w - mr}" y1="{ys(v):.1f}" y2="{ys(v):.1f}"/>')
        out.append(f'<text class="mute" x="{ml - 6}" y="{ys(v) + 4:.1f}" text-anchor="end">{v:.0f}</text>')
    for lead in range(0, xmax + 1, 24):
        out.append(
            f'<text class="mute" x="{xs(lead):.1f}" y="{h - mb + 18}" text-anchor="middle">{lead}</text>'
        )
    out.append(
        f'<text class="mute" x="{(ml + w - mr) / 2}" y="{h - 8}" text-anchor="middle">'
        "lead (hours after the 20:00 UTC read)</text>"
    )
    if cap_end < xmax:
        out.append(
            f'<line class="rule" x1="{xs(cap_end):.1f}" x2="{xs(cap_end):.1f}" y1="{mt}" y2="{h - mb}" '
            'stroke-dasharray="4 3" stroke-width="1"/>'
        )
        out.append(
            f'<text class="mute" x="{xs(cap_end) + 4:.1f}" y="{mt + 34}">captures end ({cap_end} h)</text>'
        )
    labels = []
    for i, (name, s) in enumerate(series.items()):
        p = [(xs((b + 0.5) * evaluate.LEAD_BIN), ys(v)) for b, v in enumerate(s) if v is not None]
        if not p:
            continue
        d = " ".join(f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}" for j, (x, y) in enumerate(p))
        out.append(f'<path class="s{i}" d="{d}" fill="none" stroke-width="2" stroke-linejoin="round"/>')
        out += [f'<circle class="f{i}" cx="{x:.1f}" cy="{y:.1f}" r="3"/>' for x, y in p]
        labels.append([p[-1][1], p[-1][0], name])
    labels.sort()
    for j in range(1, len(labels)):  # keep end labels at least 15 px apart
        labels[j][0] = max(labels[j][0], labels[j - 1][0] + 15)
    out += [f'<text class="ink" x="{x + 8:.1f}" y="{y + 4:.1f}">{n}</text>' for y, x, n in labels]
    out.append("</svg>\n")
    return "\n".join(out)


# Report ------------------------------------------------------------------------------------


def _ci(v, ci, f="{:.2f}"):
    return f"{f.format(v)} [{f.format(ci[0])}, {f.format(ci[1])}]"


def report(res: dict) -> str:
    names = list(res["entries"])
    when = pd.Timestamp(res["generated_at"]).strftime("%Y-%m-%d %H:%M UTC")
    L = [
        "# WM-1 dry run",
        "",
        "**A pipeline check, not a result.** "
        f"{len(res['inits'])} reads ({res['inits'][0]} to {res['inits'][-1]}), 19 stations, truth to "
        f"{pd.Timestamp(res['truth_asof']).strftime('%Y-%m-%d %H:00 UTC')}. "
        "The baselines were written after these reads, so nothing here is sealed, and with this "
        "few inits the intervals (resampling whole init dates) mean little. Generated by "
        f"`uv run scripts/wm1_dryrun.py` at {when}; numbers in `results/wm/wm1_dryrun.json`.",
        "",
        "Task and scores: [WORLD_MODEL_TRACK.md](WORLD_MODEL_TRACK.md). Each entry submits 50 joint "
        "trajectories of hourly 2 m temperature per station for hours 1 to 168 after the 20:00 UTC "
        "read; truth is ASOS, the report nearest each hour within ten minutes. Every score is in "
        "deg F, lower is better, on the same cells for every entry.",
        "",
        "## Entries",
        "",
        "| Entry | What it is | Inputs |",
        "| --- | --- | --- |",
    ]
    for n in names:
        m = json.loads((ROOT / "entries" / "wm1" / n / "entry.json").read_text())
        L.append(f"| `{n}` | {m['summary']} | {', '.join(m['inputs'])} |")
    L += [
        "",
        "## How much has verified",
        "",
        "| Read | Hours with truth at every station (of 168) |",
        "| --- | --- |",
        *[f"| {d} | {v} |" for d, v in res["verified_hours_by_init"].items()],
        "",
        "Leads every forecast covers: "
        + ", ".join(f"`{n}` {v}" for n, v in res["lead_coverage"].items())
        + ". The captures hold seven calendar days from 00:00 UTC, so the ensemble entries stop "
        "at lead 147 (Findings).",
        "",
        "## Energy score (primary) and variogram score, by window",
        "",
        "Rows are (read, station) pairs whose whole window has verified. Windows with no rows yet "
        "are listed so the gap is visible. With one read an interval collapses to a point and with "
        "two or three it is not a measure of uncertainty; they are printed to exercise the code.",
        "",
        "| Window | Reads | Rows | " + " | ".join(f"`{n}` energy" for n in names) + " |",
        "| --- | --- | --- | " + " | ".join("---" for _ in names) + " |",
    ]
    for wk, rec in res["windows"].items():
        cells = [
            _ci(rec["entries"][n]["energy"], rec["entries"][n]["energy_ci"]) if rec["rows"] else "n/a"
            for n in names
        ]
        L.append(f"| {wk} h | {rec['inits']} | {rec['rows']} | " + " | ".join(cells) + " |")
    L += [
        "",
        "| Window | " + " | ".join(f"`{n}` variogram (p = 0.5)" for n in names) + " |",
        "| --- | " + " | ".join("---" for _ in names) + " |",
    ]
    for wk, rec in res["windows"].items():
        if rec["rows"]:
            L.append(
                f"| {wk} h | "
                + " | ".join(
                    _ci(rec["entries"][n]["variogram"], rec["entries"][n]["variogram_ci"], "{:.1f}")
                    for n in names
                )
                + " |"
            )
    L += [
        "",
        "Energy score minus climatology's (negative is better), date-block 95% interval:",
        "",
        "| Window | " + " | ".join(f"`{n}`" for n in names if n != "climatology") + " |",
        "| --- | " + " | ".join("---" for n in names if n != "climatology") + " |",
    ]
    for wk, rec in res["windows"].items():
        if rec["rows"]:
            ds = [rec["entries"][n]["energy_minus_climatology"] for n in names if n != "climatology"]
            L.append(f"| {wk} h | " + " | ".join(_ci(d["diff"], d["ci"], "{:+.2f}") for d in ds) + " |")
    L += [
        "",
        "## Fair CRPS and calibration, every verified hour",
        "",
        f"{res['cells']} station-hours with truth and a forecast from every entry. PIT coverage is "
        "the share of truths inside the central 50/80/90% sample interval (calibrated: 0.50, 0.80, "
        "0.90); flatness is half the L1 distance of the 10-bin PIT histogram from uniform.",
        "",
        "| Entry | Fair CRPS | Cover 50% | Cover 80% | Cover 90% | PIT flatness |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for n, e in res["entries"].items():
        c = e["coverage"]
        L.append(
            f"| `{n}` | {_ci(e['crps'], e['crps_ci'])} | {c['50']:.2f} | {c['80']:.2f} | {c['90']:.2f} | "
            f"{e['pit_flatness_error']:.3f} |"
        )
    L += [
        "",
        "![Fair CRPS by lead](wm1_dryrun.svg)",
        "",
        "Each point is a 6 h lead bin. Later bins pool fewer reads (only the earliest read has "
        "verified that far), so the curve's shape mixes lead and read; it is a pipeline check.",
        "",
        "| Lead bin (h) | " + " | ".join(f"`{n}`" for n in names) + " |",
        "| --- | " + " | ".join("---" for _ in names) + " |",
    ]
    nb = len(next(iter(res["entries"].values()))["crps_by_lead"])
    for b in range(nb):
        vals = [res["entries"][n]["crps_by_lead"][b] for n in names]
        if all(v is None for v in vals):
            continue
        lo = b * evaluate.LEAD_BIN + 1
        L.append(
            f"| {lo}-{lo + evaluate.LEAD_BIN - 1} | "
            + " | ".join("n/a" if v is None else f"{v:.2f}" for v in vals)
            + " |"
        )
    L += ["", FINDINGS, "", ATTRIBUTION, ""]
    return "\n".join(L)


FINDINGS = """## Findings (about the pipeline)

1. **The captures stop 21 hours short of 168 h.** `capture_wm.py` asked for `forecast_days=7`,
   which Open-Meteo serves as seven calendar days from 00:00 UTC on the read's day: valid times
   to D+6 23:00 UTC, which is lead 147 after a 20:00 UTC read. The ensemble entries have no
   samples for leads 148 to 168, so under the same-rows rule no 168 h window can be scored for
   any entry on these reads. Eight days reach lead 168 for AIFS ENS, IFS ENS, GEFS, GEPS and
   MOGREPS-G (checked on 2026-10-27), and the pull request that added this dry run makes the
   capture ask for eight. ICON-EPS ends earlier (about lead 160 in the same check), so `raw` and
   `emos-ecc` drop a model that does not reach the longest common lead rather than leave holes
   in samples.
2. **168 h needs a week of truth.** The first 168 h window closes seven days after the first
   read; until then only shorter windows have rows, and each longer window rests on fewer reads.
3. **EMOS has almost nothing to learn from yet.** It is fit only on captures whose leads had
   verified before the init: none for the first read (raw mixture mean and variance), one day of
   day-1 leads for the second. Longer lead blocks reuse the longest fitted block. With a few
   weeks of captures each block gets its own fit.
4. **A single missing hour drops a whole window.** In the first run (truth to 2026-10-27
   00:00 UTC) KBOS lacked a report within ten minutes of one or two hours on each of the first
   three reads' first day (KOKC once), so 53 of 57 (read, station) rows have a complete 24 h
   window. At that rate a 168 h window at KBOS will almost never be complete. Before WM-1 is
   frozen, decide between scoring the energy and variogram scores on the observed hours only
   (the same hours for every entry; still proper if missingness does not depend on the
   forecasts) and the current all-or-nothing rule.
5. **The hash chain works end to end.** Every capture's sha256 matched its ledger manifest
   before any entry ran; every entry's code matched its manifest; each forecast's sha256 is in
   `results/wm/wm1_dryrun.json` with the manifest and code hashes of the entry that made it."""

ATTRIBUTION = """## Data

Ensemble forecasts: [Weather data by Open-Meteo.com](https://open-meteo.com/), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); values were processed (sampled,
calibrated and scored) by Physical Reasoning. Upstream: ECMWF AIFS ENS and IFS ENS, Copyright
(c) 2024-2026 European Centre for Medium-Range Weather Forecasts (ECMWF), source www.ecmwf.int,
licence CC BY 4.0, and ECMWF does not accept any liability for the accuracy or completeness of
the data, for any errors, or for any direct or indirect consequences of using it; DWD ICON-EPS,
CC BY 4.0; NOAA GEFS, public domain; ECCC GEPS and UK Met Office MOGREPS-G under their own
licences as listed by Open-Meteo. Observations: NWS ASOS via the Iowa Environmental Mesonet,
public domain. Only aggregate scores are published here; the trajectories are the `wm-ledger`
release assets."""


if __name__ == "__main__":
    t0 = dt.datetime.now()
    main()
    print("took", dt.datetime.now() - t0)
