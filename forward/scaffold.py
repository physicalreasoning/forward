"""`forward new entry|task NAME`: write a module and a test from a template, and register it.

The templates are working code (a monthly-mean entry, a live entry with the fetch left to fill
in, a toy task), so the new test passes and CI stays green from the first commit. Registration
appends one `add(...)` at the end of forward/registry.py, where every task and entry is declared.
See docs/ADDING.md.
"""

from __future__ import annotations

import json
import pathlib
import re

from . import ROOT

NAME = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
MARKER = "# forward new: registrations are appended below this line."

GAUSSIAN = '''"""{name}: TODO, one line on what it is and why it is a fair entry.

A gaussian entry of the station-highs task (forward/registry.py): fit once on data settled by
the round's cutoff, frozen as JSON parameters, then a Gaussian (mu, sigma) on the latent CLI
high of each station-day. Scored on every column (docs/METHODS.md).

The template works as is: each station's mean high in the calendar month, with that month's
spread. Replace it with yours. A NaN forecast drops that station-day for every entry, so cover
every station.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SIGMA_FLOOR = 1.0


def fit(train: pd.DataFrame) -> dict:
    """train: rows (station, day, high, prev_high, <model>...) settled by the cutoff."""
    g = train.dropna(subset=["high"])
    params: dict = {{}}
    for (st, month), x in g.groupby(["station", g["day"].dt.month]):
        sd = float(np.nanmax([x["high"].std(), SIGMA_FLOOR]))
        params.setdefault(st, {{}})[str(month)] = [float(x["high"].mean()), sd]
    return params  # stored and hashed as JSON: plain floats, string keys


def predict(params: dict, rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(mu, sigma) per row of (station, day, prev_high, <model>...); NaN where there is none."""
    mu, sigma = np.full(len(rows), np.nan), np.full(len(rows), np.nan)
    for i, r in enumerate(rows.itertuples(index=False)):
        v = params.get(r.station, {{}}).get(str(r.day.month))
        if v is not None:
            mu[i], sigma[i] = v
    return mu, sigma
'''

GAUSSIAN_TEST = """import json

import numpy as np
from test_entries import synthetic

from forward import {mod} as entry
from forward import registry


def test_registered_as_a_gaussian_fit_entry():
    e = registry.ENTRIES["{name}"]
    assert (e.task, e.kind, e.source) == ("station-highs", "gaussian", "fit")
    assert e.module == "forward.{mod}"


def test_parameters_are_json_and_every_row_gets_a_spread():
    df = synthetic()
    params = json.loads(json.dumps(entry.fit(df)))
    mu, sigma = entry.predict(params, df.tail(30))
    assert mu.shape == sigma.shape == (30,)
    assert np.isfinite(mu).all() and (sigma > 0).all()
"""

LADDER = '''"""{name}: TODO, one line on what it is and where it is served.

A live ladder entry of the station-highs task (forward/registry.py). At each read
scripts/capture.py calls `capture` with every station's target day and stores the block it
returns under "{name}" in that read's ledger file; scripts/score.py reads it back through
`accept` and `probs`. Scored on the ladder columns only (docs/METHODS.md).

Rules every live entry follows (forward/isotherm_live.py is the worked example):
- store each answer as served, stamped with `fetched_at`; one fetched at or after 22:00 UTC
  on D-1 does not count;
- `accept` pins the model you entered, so a redeployed model is never scored as this one;
- leave out stations you do not cover; never let one failure stop the others.
"""

from __future__ import annotations

import datetime as dt

MODEL_ID = "TODO: the version of the model you enter"


def fetch(station: str, day: str) -> dict:
    """TODO: ask the model for `station`'s Kalshi ladder on `day` (YYYY-MM-DD). Return its
    answer as served, with "model_id" and a "buckets" list of {{"ticker", "p"}}."""
    raise NotImplementedError


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def capture(days: dict[str, str], fetch=fetch) -> dict:
    rows = []
    for st, day in days.items():
        try:
            rows.append({{"station": st, "day": day, "response": fetch(st, day), "fetched_at": _now()}})
        except Exception as ex:  # noqa: BLE001 (one station failing must not lose the rest)
            rows.append({{"station": st, "day": day, "error": str(ex)[:200], "fetched_at": _now()}})
    return {{"rows": rows}}


def accept(block: dict) -> bool:
    return all(r.get("response", {{}}).get("model_id") == MODEL_ID for r in block["rows"] if "error" not in r)


def probs(row: dict) -> dict[str, float] | None:
    out = {{b["ticker"]: b.get("p") for b in (row.get("response") or {{}}).get("buckets", [])}}
    if not out or any(p is None for p in out.values()):
        return None
    return {{t: float(p) for t, p in out.items()}}
'''

LADDER_TEST = """from forward import {mod} as entry
from forward import registry


def answer(station, day):
    buckets = [{{"ticker": "A", "p": 0.4}}, {{"ticker": "B", "p": 0.6}}]
    return {{"model_id": entry.MODEL_ID, "buckets": buckets}}


def test_registered_as_a_live_ladder_entry():
    e = registry.ENTRIES["{name}"]
    assert (e.task, e.kind, e.source) == ("station-highs", "ladder", "live")
    assert e.module == "forward.{mod}"


def test_capture_stores_answers_and_probs_reads_them_back():
    b = entry.capture({{"NY": "2026-11-02"}}, fetch=answer)
    assert entry.accept(b)
    assert entry.probs(b["rows"][0]) == {{"A": 0.4, "B": 0.6}}


def test_a_failing_station_is_an_error_row():
    def down(station, day):
        raise TimeoutError("down")

    b = entry.capture({{"NY": "2026-11-02", "CHI": "2026-11-02"}}, fetch=down)
    assert [r["error"] for r in b["rows"]] == ["down", "down"]
"""

TASK = '''#!/usr/bin/env python3
"""{name}: TODO, one line on what is forecast and what settles it.

A task (forward/registry.py): problems whose truth resolves after the read, entries that give a
probability for each of a problem's buckets, and a scorer that reports the columns of README.md
against a trivial baseline, with date-block intervals. The template runs on toy problems:

    uv run forward score --task {name} --start 2026-01-01 --end 2026-03-31

Before it enters a round: a spec (ROUND<N>.md) that pre-registers its window, entries and tests,
real problems with truth from a public source, and this file in the round's hashed code list
(scripts/freeze.py).
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from forward import ROOT, metrics

NAME = "{name}"
BASELINE = "uniform"


def problems(start: str, end: str) -> list[dict]:
    """One problem per day: bucket edges and the index of the bucket that settled (toy data)."""
    rng = np.random.default_rng(0)
    edges = [(-np.inf, 0.0), (0.0, 1.0), (1.0, np.inf)]
    days = pd.date_range(start, end)
    return [{{"day": d, "edges": edges, "y": int(rng.choice(3, p=[0.2, 0.5, 0.3]))}} for d in days]


def forecasts(pr: dict) -> dict[str, np.ndarray]:
    """Every entry's probabilities over the problem's buckets. TODO: your entries."""
    n = len(pr["edges"])
    return {{BASELINE: np.full(n, 1 / n), "toy": np.array([0.2, 0.5, 0.3])}}


def score(probs: list[dict]) -> dict:
    dates = np.array([p["day"] for p in probs])
    ls: dict[str, list] = {{}}
    for pr in probs:
        for e, p in forecasts(pr).items():
            ls.setdefault(e, []).append(float(np.log(max(p[pr["y"]], metrics.EPS))))
    return {{
        e: {{"log_score": float(np.mean(v)), "vs_" + BASELINE: metrics.diff(dates, v, ls[BASELINE])}}
        for e, v in ls.items()
    }}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-03-31")
    a = ap.parse_args()
    res = {{"kind": "dry run (not sealed)", "task": NAME, "window": [a.start, a.end]}}
    res["scores"] = score(problems(a.start, a.end))
    out = ROOT / "results" / f"{{NAME}}_dry_run.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    for e, v in res["scores"].items():
        print(f"{{e:12s}} log {{v['log_score']:+.3f}}  vs {{BASELINE}} {{metrics.fmt(v['vs_' + BASELINE])}}")
    print(out)


if __name__ == "__main__":
    main()
'''

TASK_TEST = """import numpy as np

from forward import registry
from forward.tasks import {mod} as task


def test_registered():
    assert registry.TASKS["{name}"].score == "forward/tasks/{mod}.py"


def test_every_entry_gives_a_distribution_over_the_buckets():
    for pr in task.problems("2026-01-01", "2026-01-10"):
        for p in task.forecasts(pr).values():
            assert len(p) == len(pr["edges"]) and np.isclose(p.sum(), 1.0)


def test_scores_every_entry_against_the_baseline():
    res = task.score(task.problems("2026-01-01", "2026-03-31"))
    assert res[task.BASELINE]["vs_" + task.BASELINE]["diff"] == 0.0
    assert set(res) > {{task.BASELINE}}
"""


def _registration(call: str, args: list[str]) -> str:
    inner = "".join(f"        {a},\n" for a in args)
    return f"add(\n    {call}(\n{inner}    )\n)\n"


def _register(root: pathlib.Path, text: str) -> None:
    reg = root / "forward" / "registry.py"
    s = reg.read_text()
    if MARKER not in s:
        raise SystemExit(f"{reg}: the line {MARKER!r} is missing")
    reg.write_text(s.rstrip("\n") + "\n" + text)


def _check(name: str, taken) -> str:
    if not NAME.match(name):
        raise SystemExit(f"{name!r}: use lower case letters, digits and dashes, starting with a letter")
    if name in taken:
        raise SystemExit(f"{name!r} is already registered")
    return name.replace("-", "_")


def _write(root: pathlib.Path, files: dict[str, str]) -> list[pathlib.Path]:
    paths = [root / p for p in files]
    if existing := [str(p) for p in paths if p.exists()]:
        raise SystemExit(f"already exists: {existing}")
    for p, text in zip(paths, files.values(), strict=True):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return paths


def new_entry(name: str, kind: str = "gaussian", summary: str = "", root: pathlib.Path = ROOT):
    """Scaffold forward/entry_<name>.py and its test; register it for the station-highs task."""
    from . import registry

    mod = "entry_" + _check(name, registry.ENTRIES)
    if kind not in ("gaussian", "ladder"):
        raise SystemExit(f"kind is gaussian or ladder, not {kind!r}")
    source = "fit" if kind == "gaussian" else "live"
    src, test = (GAUSSIAN, GAUSSIAN_TEST) if kind == "gaussian" else (LADDER, LADDER_TEST)
    paths = _write(
        root,
        {
            f"forward/{mod}.py": src.format(name=name),
            f"tests/test_{mod}.py": test.format(name=name, mod=mod),
        },
    )
    summary = summary or "TODO: one line"
    args = [json.dumps(a) for a in (name, "station-highs", kind, source, "forward." + mod, summary)]
    _register(root, _registration("Entry", args))
    return paths


def new_task(name: str, summary: str = "", root: pathlib.Path = ROOT):
    """Scaffold forward/tasks/<name>.py and its test; register the task."""
    from . import registry

    mod = _check(name, registry.TASKS)
    paths = _write(
        root,
        {
            f"forward/tasks/{mod}.py": TASK.format(name=name),
            f"tests/test_task_{mod}.py": TASK_TEST.format(name=name, mod=mod),
        },
    )
    summary = summary or "TODO: one line"
    args = [json.dumps(name), json.dumps(summary), "score=" + json.dumps(f"forward/tasks/{mod}.py")]
    _register(root, _registration("Task", args))
    return paths
