# The world-model track

**Status (2026-10-27): input capture running since 2026-10-23; WM-1's entry interface,
hash-checking runner and four baselines built, with a first dry run
([WM1_DRYRUN.md](WM1_DRYRUN.md)).** Nothing here is part of Round 1 or Round 2, and no file
hashed for them is touched. The first sealed world-model round
is planned for Round 3 (March to April 2027), after an unsealed dry run.

## Why

World models are evaluated on fixed test sets: how generated video looks (FVD, VBench), whether
a physics clip continues plausibly (Physics-IQ, Motamed et al. 2026; Kang et al. 2025), or an
agent's return inside the model. None of these scores a probability against an outcome that
resolved after the model was frozen, so none rules out leakage and none says whether the model
knows what it does not know. Live forecasting benchmarks (ForecastBench, Karger et al. 2025;
Prophet Arena; FutureX) do resolve against the future, but they ask language models questions;
they do not score a model as a simulator, and none scores what happens after an action. The
closest institutional precedent is CSEP's prospective earthquake testing (Schorlemmer et al.
2018); the closest ML one is live pre-registration for time-series models (TS-Arena, Meyer et al.
2026). Neither has action-conditioned tasks, a priced market at the bid, or entries that submit
joint futures.

forward adds that combination: **a world model enters by submitting sample futures of a real
system, frozen and hashed before the outcomes exist; every scored quantity is computed from the
samples by forward's code.** One model answers every query, so its answers cannot contradict
each other (Vafa et al. 2024 on why coherence across queries is the test of a world model).

## Principles

1. The seal is on the model, not the computation. An entry is code plus weights (sha256),
   committed before the window. Inputs are captured at each read into a public ledger, so fixed
   entries can be run after the window on ledger inputs: still leakage-free, and no GPU is
   needed at 20:00 UTC. Only live (API) entries must answer at the read.
2. Same rows for every entry; missing truth drops the row for all; nothing is imputed.
3. Forward's six columns stay (proper score, calibration, trivial baselines, market at the bid,
   decision value, regime share), plus a multivariate score and, for action tasks, a policy
   ranking column.
4. Nothing from Kalshi is republished (docs/DATA_TERMS.md).

## Task families

**WM-1: station trajectories.** Hourly 2 m temperature at the 19 stations, hours 1 to 168
after the 20:00 UTC read. Entries submit K = 50 joint sample trajectories per station.
- Truth: ASOS reports from IEM, the report nearest each hour within 10 minutes
  (`forward/wm/truth.py`; 99.9% of 2026 hours at KNYC).
- Scores (`forward/wm/scores.py`): fair energy score on the 24 h and 168 h trajectories
  (primary), fair CRPS per hour, variogram score (p = 0.5), PIT. The daily high and the Kalshi
  bucket probabilities are derived from the samples, so the market and P&L columns come with
  Task 1's machinery.
- Baselines: the six operational ensembles as served (below), member-by-member calibrated
  versions, climatology analogues, persistence with bootstrapped residuals, and the
  equal-weight blend of the round's entries.

**WM-2: radar and satellite nowcasting.** MRMS precipitation and GOES-19 infrared on tiles
around the stations, leads 10 minutes to 6 hours, scored by fair CRPS on pooled fields,
fractions skill score, and rain at the station gauge. The family that lets video world models
enter on real outcomes. Baselines from pysteps (Pulkkinen et al. 2019); DGMR (Ravuri et al.
2021) as an entrant. Prototype only until WM-1 has run. A prototype (2026-10-30, `forward/wm2/`,
[WM2_PROTOTYPE.md](WM2_PROTOTYPE.md)) ran capture, truth, three baselines and scoring end to
end on four days and six tiles; the draft spec it led to, with a 3 h primary horizon and K = 20,
is [WM2_DRAFT.md](WM2_DRAFT.md).

**WM-3: interventions on the order book.** Extends Task 3 (docs/TASK3_FILLS.md). A replay arm
(fill of hypothetical passive orders), a policy arm (each entry ranks 6 to 8 fixed quoting
policies; scored by rank correlation with replayed P&L and the regret of its top pick), and an
optional live arm of tiny randomised post-only orders, which needs the maintainers' approval of
a loss cap before any order is placed. Its model side is the lab's order-book world model.

**WM-4: language models as world models.** Not a family but an entry lane: every family accepts
a text rendering of the read's inputs, with pinned model snapshots and no web access during a
call, scored on exactly the rows the physical and learned models are scored on.

## Inputs captured now

Open-Meteo's Ensemble API serves six global ensembles at the stations; it keeps no archive of
past runs (`past_days` reaches about four days back), so `scripts/capture_wm.py` records them
at every read:

| Name | Model | Members | Kind |
| --- | --- | --- | --- |
| `aifs_ens` | ECMWF AIFS ENS | 51 | learned |
| `ifs_ens` | ECMWF IFS ENS | 51 | physics |
| `gefs` | NOAA GEFS | 31 | physics |
| `icon_eps` | DWD ICON-EPS | 40 | physics |
| `geps` | ECCC GEPS | 21 | physics |
| `mogreps_g` | UK Met Office MOGREPS-G | 18 | physics |

BOM's ACCESS-GE is served but has not updated since June 2025, so it is left out. Open-Meteo's
metadata for ICON-EPS stopped updating on 2026-10-06 while its data stayed current (checked
against IFS ENS), so its run times are not recorded.

Captures through 2026-10-27 hold seven UTC days from 00:00 on the read's day, which end at
lead 147 after the 20:00 UTC read; from the merge of the WM-1 dry run they hold eight, which
reach 168 h for every model but ICON-EPS (WM1_DRYRUN.md). A day is about 1 MB, too large to
commit daily. The parquet is an asset of the `wm-ledger` release; its sha256 and each model's run initialisation and availability times are committed to
the `ledger-wm` branch the same evening. Capture runs on a maintainer's machine with a GitHub
Actions backup (`capture_wm.yml`); an asset is never overwritten, so the first capture of a day
is the one kept.

## Entry interface (WM-1, built)

A frozen entry is a directory, `entries/wm1/<name>/`, holding `entry.py` and a manifest,
`entry.json`: id, family, created_at, declared inputs, the sha256 of every code file its
forecasts depend on, the sha256 of its weights (if any), and the forecast shape it promises,
`(K, stations, leads, variables)` = (50, 19, 168, 1) for WM-1 (`forward/wm/entry.py`).

```
predict(init_time, stations, inputs) -> float array [K, len(stations), 168, len(variables)]
```

`inputs` is the only door to data (`forward/wm/access.py`): `inputs.truth(station)` serves
hourly ASOS truth for hours strictly before `init_time`, `inputs.ensembles(day)` a captured read
on or before the init day (the init day's only if captured before 22:00 UTC), and any later
request, or a source the manifest did not declare, raises `LeakageError`. While `predict` runs,
network connections, subprocesses and opening files under the data directories are refused too.
NaN means no forecast; a NaN in a scored window drops that row for every entry. Missing truth
is allowed for up to 5% of a window's hours: the energy and variogram scores are then computed on
the hours with truth, the same hours for every entry (`forward/wm/evaluate.py`, `MIN_COVERAGE`).

The runner (`forward/wm/runner.py`) refuses an entry whose code or weights differ from its
manifest, and, for a sealed round, one whose files were committed after the window's first init
or have uncommitted changes. It writes each forecast as `.npy` with a record of its own sha256,
the entry's manifest, code and weights hashes, and the shim's log of what was read. The leakage
tests (`tests/test_wm_runner.py`) also rerun every baseline with the truth after the init and
every later capture replaced by nonsense and require identical forecasts.

Baselines, each such an entry (`forward/wm/baselines.py`):

| Entry | What it is |
| --- | --- |
| `climatology` | the observed weeks that followed the same time of year in the past ten years, offsets up to two days (50 analogues) |
| `persistence` | today's anomaly from the hourly climatology carried forward, plus the error that carrying forward made in the same 50 weeks |
| `raw` | 50 members of the captured six-model ensemble, equal weight per model, the same members at every station |
| `emos-ecc` | EMOS (Gneiting et al. 2005) per 24 h lead block with a per-station intercept, fit by minimum CRPS on captures verified before the init, reordered by ECC-Q (Schefzik et al. 2013) |

Other families will get their own interfaces; an entry is ranked only within the families it
enters, and there is no cross-family headline.

## Statistics

Date-block bootstrap of every difference, as in docs/METHODS.md. At most four to six primary
hypotheses per family, pre-registered, Holm-corrected; the rest exploratory. Tail claims only
with threshold-weighted CRPS (Gneiting and Ranjan 2011; Allen et al. 2023) at a threshold fixed
at the freeze. An eight-week round has about 56 independent dates, so intervals will be wide;
pooling across rounds follows a rule fixed in advance.

## Plan

- Now to 2026-10-31: capture daily; scores and truth; ship Round 1's freeze untouched.
- November: WM-1 baselines and a dry run on the first captured weeks; the entry interface and
  a hash-checking runner (built early, 2026-10-27; first dry run in WM1_DRYRUN.md, rerun as
  truth arrives); WM-3 policy arm on recorded books (aggregate results only); MRMS
  prototype to size WM-2 (built early, 2026-10-30: WM2_PROTOTYPE.md, WM2_DRAFT.md).
- December: go or no-go for WM-1 as an exploratory family in Round 2 (freeze 2027-01-03).
- Round 3 (March to April 2027): first sealed world-model round. Candidate hypotheses: a
  calibrated learned ensemble (AIFS ENS) beats the calibrated physics ensemble (IFS ENS) on the
  168 h energy score; every entry beats persistence; language-model entries do not beat
  calibrated ensembles on the derived daily high.

## Main references

- Gneiting, T. and Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and
  estimation. *JASA* 102(477).
- Ferro, C. A. T. (2014). Fair scores for ensemble forecasts. *QJRMS* 140(683).
- Scheuerer, M. and Hamill, T. M. (2015). Variogram-based proper scoring rules for
  probabilistic forecasts of multivariate quantities. *Monthly Weather Review* 143(4).
- Schorlemmer, D. et al. (2018). The Collaboratory for the Study of Earthquake Predictability:
  achievements and priorities. *Seismological Research Letters* 89(4).
- Karger, E. et al. (2025). ForecastBench: a dynamic benchmark of AI forecasting capabilities.
  *ICLR 2025*. arXiv:2409.19839.
- Vafa, K. et al. (2024). Evaluating the world model implicit in a generative model.
  *NeurIPS 2024*. arXiv:2406.03689.
- Motamed, S. et al. (2026). Do generative video models understand physical principles?
  *WACV 2026*. arXiv:2501.09038.
- Kang, B. et al. (2025). How far is video generation from world model: a physical law
  perspective. *ICML 2025*. arXiv:2411.02385.
- Nagy, P. et al. (2025). LOB-Bench: benchmarking generative AI for finance. *ICML 2025*.
  arXiv:2502.09172.
- Meyer, M. et al. (2026). TS-Arena: a live forecast pre-registration platform. *KDD 2026*.
  arXiv:2512.20761.
- Ravuri, S. et al. (2021). Skilful precipitation nowcasting using deep generative models of
  radar. *Nature* 597.
- Gneiting, T., Raftery, A. E., Westveld, A. H. and Goldman, T. (2005). Calibrated
  probabilistic forecasting using ensemble model output statistics and minimum CRPS
  estimation. *Monthly Weather Review* 133(5).
- Schefzik, R., Thorarinsdottir, T. L. and Gneiting, T. (2013). Uncertainty quantification in
  complex simulation models using ensemble copula coupling. *Statistical Science* 28(4).
- Gneiting, T. and Ranjan, R. (2011). Comparing density forecasts using threshold- and
  quantile-weighted scoring rules. *JBES* 29(3).
- Allen, S., Ginsbourger, D. and Ziegel, J. (2023). Evaluating forecasts for high-impact events
  using transformed kernel scores. *SIAM/ASA JUQ* 11(3).
