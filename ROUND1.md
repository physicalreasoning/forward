# Round 1: station highs, November to December 2026

Status: **draft**. This file is frozen, with its sha256 and the entries' parameter hash recorded in
`frozen/round1.json`, no later than 2026-10-31 23:59 UTC. Nothing below changes after that; any
deviation is reported beside the original text, never in place of it.

## Question

Does a learned atmospheric world model (ECMWF's AIFS) carry more information about tomorrow's
observed high than the physics models it was trained to imitate, once each is calibrated the
same way? And does any of them beat the trivial answers (copy yesterday, or climatology) and
the prediction market that prices the same outcome? And does isotherm, our calibrated model of
the ladders themselves, beat the market it prices against?

## Task

- **Sites:** the 19 NWS climate stations that settle Kalshi's daily-high ladders (`forward/stations.py`).
- **Target:** the CLI daily high (integer deg F) on day D, local calendar day.
- **Read:** 20:00 UTC on D-1. Every input must exist at the read.
- **Window:** target days 2026-11-01 to 2026-12-26 inclusive (8 weeks, up to 1,064 station-days).
- **Truth:** the CLI high from IEM's archive of NWS reports. Where a report is missing, Kalshi's
  settled `expiration_value` for that station and day; if both are missing, the day is dropped
  for every entry.

## Inputs

- **Model forecasts:** each model's latest run at the read, from Open-Meteo, hourly 2 m
  temperature, maximum over D's local hours (at least 20 hours present). Captured by
  `scripts/capture.py` and committed to the `ledger` branch at the read; a day without a
  ledger entry is dropped for every entry. A capture counts only if it was taken before 22:00 UTC
  on D-1 (`forward/ledger.py`); if a station-day has two, the earlier one counts.
- **isotherm's ladders:** at the same read, `scripts/capture.py` asks isotherm's public API
  (https://isotherm.onrender.com, `GET /ladder/{city}?day=D`) for every station it covers and stores
  each answer as served under the ledger file's `isotherm` key, with the time it arrived and the
  model hash `GET /health` reports before and after the calls (`forward/isotherm_live.py`). An
  answer counts only if it arrived before 22:00 UTC on D-1 and both hashes are `b200c51ce4ee`, the
  model entered here; answers from any other model are dropped, not scored.
- **Station history:** CLI highs through D-1. D-1's report is not final at the read; using it
  gives the copy baseline a small advantage, which only makes beating it harder.
- **Fitting data:** model archives (Open-Meteo previous-day runs, AIFS from 2025, others from
  2024) and CLI highs since 2010, all settled by 2026-10-30.

## Entries

Every entry is declared in `forward/registry.py`, as one of two kinds. The **gaussian** entries
below give a Gaussian on the latent high, discretised to the integer CLI value
(`forward/entries.py`). Parameters are fit once, on the fitting data, and frozen. Every model entry is fit on the same
days, those where all five models have a forecast (AIFS's archive starts in February 2025), so no
model gains from a longer record.

| Entry | Mean | Spread |
| --- | --- | --- |
| climatology | station mean for day of year (+/- 10 days, 2010 on) | station SD for day of year |
| persistence (copy) | D-1 high | residual SD by station and month |
| raw-{aifs, ifs, gfs, icon, nbm} | the model's number | its RMSE at the station |
| emos-{aifs, ifs, gfs, icon, nbm} | a + b x model, by station | residual SD by station and month |
| emos-all | ridge on all five models, by station | residual SD by station and month |

One **ladder** entry gives a probability for each bucket of Kalshi's ladder, not for each integer:

| Entry | What it is | Stations |
| --- | --- | --- |
| isotherm | isotherm's served probabilities (`p_model`), model hash `b200c51ce4ee`: a log pool of the market's prices and EMOS-calibrated GFS MOS, fit before 2026-06-29 (isotherm FINDINGS §9) | the 7 it serves: NY, CHI, MIA, AUS, LAX, DEN, PHIL |

isotherm is not fit here; its seal is the model hash, pinned in `forward/isotherm_live.py`, which
is hashed with the rest of the scoring code. It reads the market's quotes when it is called, a
few minutes after the 20:00 UTC candle the market reference uses; it pools those prices by
design, so beating the market is a statement about what it adds to them.

The market (Kalshi's ladder at the read, bid-priced and mid) is a reference, not an entry.
The round scores only the entries above; no outside entries.

## Columns reported for every entry

Gaussian entries get all six. A ladder entry gets columns 4 and 5; columns 1, 2, 3 and 6 are
defined on the integer grid and are reported as not applicable for it.

1. Log score and ranked probability score, with date-block bootstrap 95% CIs.
2. Calibration: PIT flatness and 50/80/90% central-interval coverage.
3. Skill against persistence (copy) and climatology.
4. Log score on Kalshi ladders against the bid-priced market (and the mid, for reference).
5. Decision value: one contract per bucket when the entry's probability clears the quote by
   Kalshi's taker fee plus 1 cent, held to settlement; total and per-ladder P&L with CI, with
   and without 1 cent of slippage.
6. Month share of the gain against persistence.

Columns 4 and 5 are reported twice: for the gaussian entries on every ladder (as in the dry run),
and for every entry, gaussian and ladder, on the same ladders: those isotherm covers, where every
entry has a forecast. A ladder counts for isotherm only if its answer has a probability for every
bucket of the settled ladder (matched by ticker).

## Pre-registered tests

All differences are per station-day (per ladder for H3, H4 and H5), with 95% CIs from 2,000
date-block resamples.

- **H1 (learned vs physics):** log score of emos-aifs minus emos-ifs. AIFS better if the CI is
  above 0, IFS better if below, otherwise a tie. Same test for raw-aifs minus raw-ifs, reported as
  secondary.
- **H2 (copy check):** each emos entry minus persistence. Each passes if its CI is above 0.
- **H3 (market):** emos-all minus the bid-priced market on the ladders. Passes if the CI is above 0.
- **H4 (decision value):** emos-all's mean P&L per ladder after fees and 1 cent of slippage.
  Passes if the CI is above 0.
- **H5 (isotherm vs market):** isotherm minus the bid-priced market, on the ladders isotherm
  covers (the second ladder table). Passes if the CI is above 0. Reported beside it, not tested:
  isotherm's P&L per ladder after fees and 1 cent of slippage, and every gaussian entry on the
  same ladders.

Every result is published, including failures.

## Scoring

After 2026-12-28, `uv run scripts/score.py --round 1`. It checks the spec, code and parameter hashes, reads only the
ledger for inputs, refetches truth and ladders, and writes `results/round1.json`.
