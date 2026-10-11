# forward

Sealed forward tests for world models. Every entry is frozen and hashed before a round opens,
then scored only on outcomes that resolve after the freeze, so nothing can leak into training.

Existing world-model benchmarks mostly score how generated video looks, or score language-model
forecasters on real outcomes. This one scores models of real systems on real outcomes, and makes
every entry report the same six columns:

1. a proper score (log score, ranked probability score) with date-block bootstrap CIs
2. calibration (PIT, interval coverage)
3. skill against the trivial answers: copy the last value, and climatology
4. skill against the prediction market that prices the same outcome, at its bid
5. decision value: a fixed trading policy's paper P&L after fees and slippage
6. how much of any gain one calendar month explains

Column 3 exists because a model that learns to copy its input can look healthy on every other
diagnostic ([causal-jepa](https://github.com/physicalreasoning/causal-jepa)). Columns 4 and 5
exist because a better score is not the same as a better decision
([isotherm](https://github.com/physicalreasoning/isotherm), FINDINGS §41 and §49).

## Rounds

| Round | Task | Window | Status |
| --- | --- | --- | --- |
| 0 | Station highs, dry run (archive inputs, not sealed) | 2026-07-01 to 2026-10-09 | pipeline check |
| 1 | Station highs, 19 Kalshi climate stations | 2026-11-01 to 2026-12-26 | spec in [ROUND1.md](ROUND1.md), freezes 2026-10-31 |
| 2 | Station highs again; Kalshi price ladders vs copying the last price | 2027-01-04 to 2027-02-28 | draft in [ROUND2.md](ROUND2.md), freezes 2027-01-03 |

## Round 0 (dry run, not sealed)

Fit on data through 2026-06-29, scored 2026-07-01 to 2026-10-09 (1,917 station-days, 1,916 Kalshi
ladders) with archived previous-day runs as inputs. Log score differences per station-day, 95% CIs:

| Test | Result |
| --- | --- |
| H1: calibrated AIFS minus calibrated IFS | +0.133 [+0.089, +0.178], AIFS better |
| H1 secondary: raw AIFS minus raw IFS | -0.061 [-0.092, -0.029], IFS better |
| H2: every calibrated model minus copy | +0.41 to +0.76, all pass |
| H3: five-model blend minus bid-priced market | -0.113 [-0.151, -0.075], market better |
| H4: blend's P&L per ladder, 1c slippage | -$0.021 [-0.061, +0.019], no edge |

The learned model is worse than physics as it comes out of the box and better once calibrated,
and no entry beats the market that prices the same outcome. Round 1 tests whether this holds
on inputs captured live. Full output: `results/round0_dry_run.json`.

## Task 2 dry run: foundation models vs copying the last price

Kalshi's daily ladders on the S&P 500, Nasdaq-100, EUR/USD, USD/JPY, WTI, Brent, gold, silver,
copper and natural gas (2,609 ladders in Yahoo's two-year hourly window). Entries see the
underlying's last 512 hourly closes at the read. Zero-shot, as released. Log score per ladder
minus the copy baseline (a lognormal at the last price, no drift), 95% date-block CIs:

| Entry | 24 h before close (903) | 6 h before close (1,706) |
| --- | --- | --- |
| Chronos-Bolt small | -0.046 [-0.100, +0.010] | -0.028 [-0.069, +0.010] |
| Chronos-Bolt base | -0.072 [-0.120, -0.020] | -0.020 [-0.056, +0.018] |
| TimesFM 2.5 | -0.059 [-0.103, -0.011] | -0.017 [-0.062, +0.026] |
| each model's median, copy's spread | -0.04 to -0.07, all below zero | -0.04 to -0.05, all below zero |

None beats copying. Their median moves point the right way 49 to 50% of the time, and using
their direction makes every one worse, so what they add to copying is noise. The copy baseline
itself beats the bid-priced market (+1.30 at 24 h, +0.21 at 6 h) but trades to about zero after
fees, as in isotherm §49. Output: `results/prices_dry_run.json`.

## Layout

- `forward/`: stations, truth (NWS CLI), Open-Meteo inputs, Kalshi ladders, entries, metrics
- `scripts/build_history.py`: fitting data; `scripts/capture.py`: live inputs at each read;
  `scripts/score.py`: scoring
- `ledger` branch: inputs captured at each read; the commit time is the seal

Physical Reasoning, 2026.
