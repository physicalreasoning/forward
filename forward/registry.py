"""Every task and every entry, declared in one place.

A **task** is a forecasting problem with its own truth, inputs, spec and scorer. An **entry** is
one model answering a task. Entries come in two kinds, which decide the columns they are scored on:

  gaussian  a Gaussian (mu, sigma) on a latent value that is discretised to integers. Scored on
            every column: the integer grid (log score, RPS, PIT, against copy and climatology)
            and the ladders (log score against the market, taker P&L).
  ladder    one probability per Kalshi ladder bucket. Scored on the ladder columns only; the
            integer-grid columns do not apply, and the entry is absent from them.

and from one of three sources:

  fit    fit on data settled by the round's cutoff; the parameters are frozen and hashed
  fixed  nothing fit on our data (a rule, or released weights at a pinned revision)
  live   an outside model served at the read; its answers are captured into the ledger

On the ladders, every entry of a task is compared on the same ladders: those where all of them
have a forecast (`scripts/score.py`).

`forward new entry NAME` and `forward new task NAME` scaffold a module and a test from a template
and append the registration at the end of this file (`forward/cli.py`); see docs/ADDING.md.
Scoring reads this file, so it is hashed with every round that scores station highs: an entry
registered after a freeze cannot enter that round.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from .openmeteo import MODELS

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

Kind = Literal["gaussian", "ladder"]
Source = Literal["fit", "fixed", "live"]


@dataclass(frozen=True)
class Task:
    name: str
    summary: str
    score: str  # script that scores it, relative to the repo root
    spec: str = ""  # the spec that pre-registers it, e.g. ROUND1.md
    capture: str = ""  # script that captures its live inputs at the read, if any


@dataclass(frozen=True)
class Entry:
    name: str
    task: str
    kind: Kind
    source: Source
    module: str  # where it is implemented, e.g. forward.entries
    summary: str

    def load(self):
        return importlib.import_module(self.module)

    @property
    def path(self) -> str:
        return self.module.replace(".", "/") + ".py"


class FitEntry(Protocol):
    """A module implementing one gaussian entry fit before the freeze (`forward new entry`)."""

    def fit(self, train: pd.DataFrame) -> dict:
        """train: rows (station, day, high, prev_high, <model>...) settled by the cutoff. The
        parameters must be JSON (they are stored and hashed as JSON)."""
        ...

    def predict(self, params: dict, rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """(mu, sigma) per row, NaN where the entry has no forecast."""
        ...


class LiveLadderEntry(Protocol):
    """A module implementing one live ladder entry (see forward/isotherm_live.py)."""

    def capture(self, days: dict[str, str]) -> dict:
        """Ask the model for each station's target day; the block stored under its name in the
        ledger file, with a "rows" list of {"station", "day", "fetched_at", ...}."""
        ...

    def accept(self, block: dict) -> bool:
        """Whether a stored block came from the entered model."""
        ...

    def probs(self, row: dict) -> dict[str, float] | None:
        """{Kalshi bucket ticker: probability} from one stored row; None if unusable."""
        ...


TASKS: dict[str, Task] = {}
ENTRIES: dict[str, Entry] = {}


def add(x: Task | Entry) -> None:
    reg = TASKS if isinstance(x, Task) else ENTRIES
    if x.name in reg:
        raise ValueError(f"{x.name} is registered twice")
    if isinstance(x, Entry) and x.task not in TASKS:
        raise ValueError(f"{x.name}: unknown task {x.task}")
    reg[x.name] = x


def entries(task: str, kind: Kind | None = None, source: Source | None = None) -> list[Entry]:
    return [
        e
        for e in ENTRIES.values()
        if e.task == task and (kind is None or e.kind == kind) and (source is None or e.source == source)
    ]


# The seeded entries of forward/entries.py fit and predict together, as one module.
BUILTIN = "forward.entries"


def extra_fit_entries(task: str = "station-highs") -> list[Entry]:
    """Gaussian entries fit before the freeze, other than the seeded ones."""
    return [e for e in entries(task, "gaussian", "fit") if e.module != BUILTIN]


def params_key(e: Entry) -> str:
    """Where an extra entry's parameters sit in the frozen parameters (beside the stations)."""
    return "entry:" + e.name


def fit(train: pd.DataFrame, task: str = "station-highs") -> dict:
    """Parameters of every fit entry of the task. Without extra entries, exactly entries.fit."""
    from . import entries as seeded

    params = seeded.fit(train)
    for e in extra_fit_entries(task):
        params[params_key(e)] = e.load().fit(train)
    return params


def predict(params: dict, rows: pd.DataFrame, task: str = "station-highs") -> dict:
    """{entry: (mu, sigma)} for every gaussian entry of the task."""
    from . import entries as seeded

    out = seeded.predict(params, rows)
    for e in extra_fit_entries(task):
        out[e.name] = e.load().predict(params[params_key(e)], rows)
    return out


def code_files(task: str = "station-highs") -> list[str]:
    """Every entry module of the task, for the hashes a round is frozen with."""
    return sorted({e.path for e in entries(task)})


# Tasks -------------------------------------------------------------------------------------

add(
    Task(
        "station-highs",
        "tomorrow's CLI high at the 19 NWS stations that settle Kalshi's daily-high ladders",
        score="scripts/score.py",
        spec="ROUND1.md",
        capture="scripts/capture.py",
    )
)
add(
    Task(
        "price-ladders",
        "where an index, FX rate or commodity closes, on Kalshi's daily price ladders",
        score="scripts/score_prices.py",
        spec="ROUND2.md",
    )
)

# Entries: station highs --------------------------------------------------------------------

add(
    Entry(
        "climatology", "station-highs", "gaussian", "fit", BUILTIN, "station mean and SD for the day of year"
    )
)
add(Entry("persistence", "station-highs", "gaussian", "fit", BUILTIN, "copy D-1's high, the copy baseline"))
for _m in MODELS:
    add(
        Entry(
            f"raw-{_m}", "station-highs", "gaussian", "fit", BUILTIN, f"{_m} as it comes, spread = its RMSE"
        )
    )
for _m in MODELS:
    add(Entry(f"emos-{_m}", "station-highs", "gaussian", "fit", BUILTIN, f"{_m} calibrated, a + b x model"))
add(Entry("emos-all", "station-highs", "gaussian", "fit", BUILTIN, "ridge on all five models"))
add(
    Entry(
        "isotherm",
        "station-highs",
        "ladder",
        "live",
        "forward.isotherm_live",
        "isotherm's served ladder probabilities (7 cities), captured at the read",
    )
)

# Entries: price ladders --------------------------------------------------------------------

add(
    Entry(
        "copy", "price-ladders", "ladder", "fixed", "forward.prices", "lognormal at the last price, no drift"
    )
)
for _n, _what in (
    ("chronos-bolt-small", "Chronos-Bolt small"),
    ("chronos-bolt-base", "Chronos-Bolt base"),
    ("timesfm-2.5", "TimesFM 2.5"),
):
    add(Entry(_n, "price-ladders", "ladder", "fixed", "forward.tsfm", f"{_what}, zero-shot"))
    add(
        Entry(
            _n + "-centre",
            "price-ladders",
            "ladder",
            "fixed",
            "forward.tsfm",
            f"{_what}'s median, copy's spread",
        )
    )

# forward new: registrations are appended below this line.
