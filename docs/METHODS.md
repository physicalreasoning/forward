# Methods

How a round is run and scored. Each rule here is enforced in code (module in brackets) and
covered by the offline tests in `tests/`.

## The seal

A round has three dates that never move once it is frozen: the **cutoff** (last day of data any
entry may be fit on), the **first read**, and the **window** of outcomes it is scored on.

1. **Freeze** (`scripts/freeze.py`). Every entry is fit on data settled by the cutoff. The round
   file `frozen/round<N>.json` records the fitted parameters and the sha256 of: the parameters
   (as sorted-key JSON), the round's spec, and every file its scoring runs. It is committed and
   pushed before the first read; the public commit is the timestamp.
2. **Capture** (`scripts/capture.py`, `forward/ledger.py`). Inputs that exist only live (model
   runs, and the answers of live entries such as isotherm) are written at each read and committed
   to the public `ledger` branch. A capture counts only if it was taken before 22:00 UTC on D-1;
   a live entry's answer is timed by when it arrived. A station-day without one is dropped for
   every entry, never imputed.
3. **Score** (`forward/seal.py`). Scoring refuses to run if any recorded hash differs, then reads
   inputs only from the ledger and truth only from sources published after the outcome.

Entries are scored on the same rows: a row is kept only if every entry has a forecast for it, so
no entry can improve its average by abstaining on hard days.

## Entries: two kinds

Every task and entry is declared in `forward/registry.py`. An entry is one of two kinds:

- **gaussian:** a Gaussian (mu, sigma) on a latent value discretised to integers. Scored on all
  six columns.
- **ladder:** a probability for each bucket of a Kalshi ladder, and nothing finer. Scored on the
  ladder columns only (market and decision value); the integer-grid columns (proper score on the
  integers, calibration, copy and climatology, month share) are reported as not applicable.

and comes from one of three sources: **fit** (parameters fit by the cutoff, frozen and hashed),
**fixed** (a rule, or released weights at a pinned revision) or **live** (an outside model served
at the read; its answers are captured into the ledger, and its version is pinned in the hashed
code so a redeployed model is never scored as the entered one).

On the ladders the same-rows rule holds across kinds: a ladder entry that covers fewer stations
gets its own ladder table, in which every entry, of either kind, is scored on exactly the ladders
all of them forecast. The table of gaussian entries on every ladder is reported unchanged beside
it. A ladder entry's answer counts for a ladder only if it gives every bucket of the settled
ladder (matched by ticker). Adding an entry or a task: [ADDING.md](ADDING.md).

## Task 1: station highs

- **Truth:** the NWS Daily Climatological Report (CLI) high in integer deg F, which is also what
  Kalshi's daily-high ladders settle on. Where a report is missing, Kalshi's settlement value.
- **Forecast form:** a Gaussian on the latent high, discretised to integers:
  P(k) = Phi((k + 0.5 - mu) / sigma) - Phi((k - 0.5 - mu) / sigma).
- **Inputs:** each model's hourly 2 m temperature from Open-Meteo, maximum over the station's
  local day (at least 20 hours present). Archived previous-day runs fit the entries; live runs
  captured at the read are what a round scores. The archived values are each from the run started 24 h before the hour (checked
  against Open-Meteo's exact-run archive), so for afternoon hours they come from a run published
  after the read: fine for fitting, which only needs the forecast-to-truth relation, but the dry
  run's scores are slightly optimistic for every entry.
- **isotherm (ladder entry, live):** at the read, `GET /ladder/{city}?day=D` on isotherm's public
  API for each of the 7 stations it serves, stored without the market's quotes (bid, ask and market probability are dropped, since the ledger is public); the bucket probabilities are its
  `p_model`. `GET /health` before and after the calls must report the entered model hash
  (`forward/isotherm_live.py`). isotherm pools the market's live prices, so it is compared to
  the market on the ladders, which is the comparison it is built for.

## Task 2: price ladders

- **Truth:** each Kalshi market's result.
- **Inputs:** the underlying's hourly closes from Yahoo, using only bars that closed by the read.
- **Copy baseline:** a lognormal centred on the last close, with the standard deviation of log
  moves over the same clock window on the previous 60 days, and no drift. Prices are close to
  martingales, so this is the trivial solution a learned model must beat.
- **Learned entries:** the 10th, 50th and 90th percentiles at the close, read as a lognormal
  (median; spread = log(q90 / q10) / 2.5631). The "-centre" variants keep the model's median and
  the copy baseline's spread, which isolates whether the model knows where the price goes.

## The six columns

| Column | Definition | Code |
| --- | --- | --- |
| Proper score | log score of the realised integer high or bucket; ranked probability score (Epstein 1969) on the integer grid | `metrics.log_score`, `metrics.rps` |
| Calibration | randomised PIT for integer outcomes (Czado, Gneiting and Held 2009); 50/80/90% central-interval coverage; 10-bin PIT flatness error | `metrics.pit`, `metrics.calibration` |
| Trivial solutions | difference from persistence (copy) and climatology | `scripts/score.py` |
| Market | log score on Kalshi ladders minus the bid-priced market: every bucket at its bid, empty bids at 0.5 cents, renormalised. Mid-prices flatter every model, because a bucket nobody bids still carries half its ask (isotherm FINDINGS §41) | `metrics.market_probs` |
| Decision value | one contract per bucket when the entry's probability clears the quote by Kalshi's taker fee, ceil(7 p (1 - p)) cents, plus 1 cent; held to settlement; with and without 1 cent of slippage | `metrics.taker_pnl` |
| Regime | share of the per-row gain's variance explained by calendar month | `metrics.month_share` |

**Uncertainty.** Every difference is a mean per row with a 95% interval from 2,000 resamples of
whole dates (a cluster bootstrap). Stations on one date share a weather pattern and a model run,
so rows within a date are not independent; resampling rows would understate the interval
(`tests/test_metrics.py` checks this).

## Entries, task 1

| Entry | Mean | Spread |
| --- | --- | --- |
| climatology | station mean, day of year +/- 10 days, 2010 on | station SD, same window |
| persistence | D-1 high | residual SD by station and month (+/- 1 month) |
| raw-*model* | the model's number | its RMSE at the station |
| emos-*model* | a + b x model, by station (EMOS, Gneiting et al. 2005, without an ensemble-spread term) | residual SD by station and month |
| emos-all | ridge regression on all five models, by station | residual SD by station and month |
| isotherm | ladder entry: isotherm's served bucket probabilities, model hash pinned | not applicable |

Every model entry is fit on the same days, those where all five models exist, so no model gains
from a longer archive.

## References

- Ansari, A. F. et al. (2024). Chronos: Learning the language of time series. *TMLR*. arXiv:2403.07815.
- Czado, C., Gneiting, T. and Held, L. (2009). Predictive model assessment for count data. *Biometrics* 65(4).
- Das, A. et al. (2024). A decoder-only foundation model for time-series forecasting. *ICML*. arXiv:2310.10688.
- Epstein, E. S. (1969). A scoring system for probability forecasts of ranked categories. *Journal of Applied Meteorology* 8(6).
- Gneiting, T. and Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. *JASA* 102(477).
- Gneiting, T., Raftery, A. E., Westveld, A. H. and Goldman, T. (2005). Calibrated probabilistic forecasting using ensemble model output statistics and minimum CRPS estimation. *Monthly Weather Review* 133(5).
- Lang, S. et al. (2024). AIFS: ECMWF's data-driven forecasting system. arXiv:2406.01465.
- Merchant, A. et al. (2026). Towards financial world modeling. arXiv:2610.09048.
- Physical Reasoning (2026). isotherm: calibrated decision models for prediction markets. FINDINGS §41, §47, §49. https://github.com/physicalreasoning/isotherm
