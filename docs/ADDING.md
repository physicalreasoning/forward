# Adding an entry or a task

Every task and every entry is declared in one place, [`forward/registry.py`](../forward/registry.py).
The `forward` command scaffolds a new one from a template, with a test, and registers it there:

```bash
uv sync                                                # installs the `forward` command
uv run forward list                                    # what is registered
uv run forward new entry NAME [--kind gaussian|ladder] [--summary TEXT]
uv run forward new task NAME [--summary TEXT]
```

The templates are working code, so the new test passes and CI stays green from the first commit;
then you replace the template's logic with yours. To undo a scaffold, delete the two files it
wrote and the `add(...)` block it appended to the registry.

## Kinds and sources

An entry's **kind** decides the columns it is scored on ([METHODS.md](METHODS.md)):

| Kind | Gives | Scored on |
| --- | --- | --- |
| `gaussian` | (mu, sigma) on a latent value discretised to integers | all six columns |
| `ladder` | a probability for each bucket of a Kalshi ladder | the ladder columns only (market, decision value); the integer-grid columns are not applicable |

Its **source** decides how it is sealed: `fit` (parameters fit by the cutoff, frozen and hashed by
`scripts/freeze.py`), `fixed` (a rule, or released weights at a pinned revision) or `live` (an
outside model served at the read, captured into the ledger by `scripts/capture.py`, its version
pinned in its module).

`forward new entry` adds entries to the station-highs task: `--kind gaussian` makes a `fit` entry,
`--kind ladder` a `live` one. A new task carries its own entries in its module.

## Worked example: a gaussian entry

Suppose we want to test whether a station's mean high for the calendar month is a useful entry.

```console
$ uv run forward new entry month-mean --summary "station mean high by calendar month"
wrote forward/entry_month_mean.py
wrote tests/test_entry_month_mean.py
registered in forward/registry.py; next: docs/ADDING.md
```

The registry gains one block:

```python
add(
    Entry(
        "month-mean",
        "station-highs",
        "gaussian",
        "fit",
        "forward.entry_month_mean",
        "station mean high by calendar month",
    )
)
```

`forward/entry_month_mean.py` has two functions, the `FitEntry` protocol of the registry:

- `fit(train) -> dict`: `train` holds one row per station-day (station, day, high, prev_high and
  each model's forecast) settled by the cutoff. Return JSON-able parameters: they are stored and
  hashed as JSON.
- `predict(params, rows) -> (mu, sigma)`: one Gaussian per row, NaN where the entry has none.
  A NaN drops that station-day for **every** entry (the same-rows rule), so cover every station.

The template already implements the monthly mean, so it runs as is:

```console
$ uv run pytest tests/test_entry_month_mean.py
2 passed
$ uv run forward score --dry-run 2026-07-01 2026-10-09
rows 1917 days 101
emos-all       log -2.155  rps 1.128  vs copy +0.758  cov80 0.79
...
climatology    log -3.121  rps 3.195  vs copy -0.208  cov80 0.82
month-mean     log -3.185  rps 3.467  vs copy -0.273  cov80 0.80
...
month-mean     vs bid-market -1.047 [-1.116, -0.976]  pnl $-248 (1c slip $-322) trades 9573
```

Every scorer, the freeze and the rehearsal pick it up from the registry: `registry.fit` and
`registry.predict` run it beside the seeded entries, and its module joins the files a round hashes.
(A month's mean is worse than the day-of-year climatology, as it should be; the dry run above
rewrote `results/round0_dry_run.json`, so restore it with `git checkout results/` before
committing anything else.)

## Worked example: a live ladder entry

isotherm is the worked example: [`forward/isotherm_live.py`](../forward/isotherm_live.py). To add
another served model:

```bash
uv run forward new entry my-model --kind ladder --summary "my model's ladder probabilities"
```

and fill in `fetch(station, day)` in `forward/entry_my_model.py`. The module has three
functions, the `LiveLadderEntry` protocol:

- `capture(days) -> dict`: called by `scripts/capture.py` at each read with every station's
  target day. Return the block stored under the entry's name in that read's ledger file: the
  answers as served, each with `fetched_at`. Leave out stations you do not cover; record an error
  row rather than raising, so one failure never costs the others.
- `accept(block) -> bool`: whether a stored block came from the model you entered. isotherm
  compares the hash `/health` reports with the one pinned in its module.
- `probs(row) -> {ticker: probability}`: one ladder's probabilities, keyed by Kalshi ticker.

Rules the scorer enforces: an answer that arrived at or after 22:00 UTC on D-1 does not count;
a ladder counts only if the answer gives every bucket of the settled ladder; a station-day with
two answers keeps the earlier. Check a capture without touching the ledger:

```bash
uv run forward capture --out /tmp/ledger-check
```

A ladder entry is scored in a second ladder table where every entry, of either kind, is scored on
exactly the ladders all of them forecast (isotherm: the 7 stations it serves). Until the scaffold's
`fetch` is filled in, each capture stores error rows for it, and it is absent from scoring.

## Worked example: a task

```console
$ uv run forward new task my-task --summary "what is forecast, and what settles it"
wrote forward/tasks/my_task.py
wrote tests/test_task_my_task.py
registered in forward/registry.py; next: docs/ADDING.md
$ uv run forward score --task my-task --start 2026-01-01 --end 2026-03-31
```

The template runs end to end on toy problems: `problems(start, end)` (bucket edges and the
realised bucket), `forecasts(problem)` (each entry's probabilities, with a uniform baseline) and
`score(...)` (log score and the difference from the baseline, with date-block intervals,
written to `results/my-task_dry_run.json`). Replace the toy problems with real ones whose truth
comes from a public source and resolves after the read.

## Before it enters a round

Registering is not entering. A round scores what its spec pre-registers, frozen before its first
read:

1. Name the entry (or task) and its tests in the round's spec, `ROUND<N>.md`, before the freeze.
2. A task's scorer and modules go in the round's hashed code list in `scripts/freeze.py`. Entry
   modules of station highs are added to it automatically, from the registry.
3. Run the offline checks: `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run pytest`, and `uv run forward rehearse /tmp/ledger` (it must still reproduce the dry
   run exactly, unless your change is meant to add to it).

The registry is hashed with every round that scores station highs, so an entry registered after a
round froze cannot enter that round: its scorer would refuse to run on the changed files.

## Command reference

| Command | Runs |
| --- | --- |
| `forward list` | prints every task and entry from the registry |
| `forward history` | `scripts/build_history.py` |
| `forward capture [--out DIR]` | `scripts/capture.py` |
| `forward freeze --round N` | `scripts/freeze.py` |
| `forward score [--task NAME] [ARGS]` | the task's scorer: `scripts/score.py` (station highs), `scripts/score_prices.py` (price ladders) |
| `forward rehearse DIR` | `scripts/rehearse.py` |
| `forward leaderboard` | `scripts/leaderboard.py` |
| `forward site [--out FILE]` | `scripts/site.py` |
| `forward new entry NAME` / `forward new task NAME` | scaffold, test, register |

Arguments after a step pass through to its script unchanged. The scripts remain the entry points
the scheduled jobs call (`uv run scripts/capture.py`, `scripts/build_history.py`,
`scripts/freeze.py`).
