# WM-2 draft spec: precipitation nowcasting on radar tiles

**Status (2026-10-30): a draft for discussion, not frozen; nothing here is part of any round.**
Built from the prototype in [WM2_PROTOTYPE.md](WM2_PROTOTYPE.md) (code in `forward/wm2/`),
which ran every step below end to end on four days and six tiles. Numbers marked "measured"
come from that run or from the bucket on 2026-10-30; everything else is a proposal. The family
was sketched in [WORLD_MODEL_TRACK.md](WORLD_MODEL_TRACK.md); this draft changes it in three
places, each from a prototype finding: a 3 h primary horizon (6 h exploratory), K = 20 samples,
and a larger input box than the scored box.

## Task

At each init (00, 06, 12 and 18 UTC), an entry submits K = 20 joint sample futures of the
surface rain rate (mm/h) on a fixed box around each of the 19 stations, at leads 10, 20, 30,
60, 90, 120 and 180 minutes (primary) and 240, 300 and 360 minutes (exploratory). The samples
are joint across leads and pixels: sample k at every lead and pixel is one coherent future, so
the scores see whether the model moves, grows and decays rain as a whole, not pixel by pixel.

Grid: the MRMS CONUS grid (0.01 deg) averaged 2 x 2 to 0.02 deg (about 2 km). The scored box
is 128 x 128 pixels (2.56 deg, about 285 x 218 km at 40 N) centred on the station, shifted
inside the CONUS grid where the station is near its edge (`forward/wm2/mrms.py`).

This is the family where video and generative world models (DGMR, Ravuri et al. 2021;
NowcastNet, Zhang et al. 2023) can enter on real outcomes that resolve after they are frozen.

## Truth

NOAA MRMS (Zhang et al. 2016) `PrecipRate`, the instantaneous radar-derived surface rain rate,
published every 2 minutes on the CONUS grid. The truth for lead L is the frame valid exactly at
init + L, averaged to 0.02 deg; a 2 x 2 block with any flagged point (no coverage, missing) is
NaN (`forward/wm2/truth.py`). A frame absent from the bucket drops that (init, lead) for every
entry; a NaN pixel drops that pixel for every entry; nothing is interpolated.

Measured: 18 of 4,320 ten-minute frames were absent from the bucket in the 30 days to
2026-10-29 (0.4%), in short clusters; a frame appears about 3 minutes after its valid time.

Known limits, stated now so no one tunes to them later: PrecipRate is a radar estimate, not a
gauge; it has brightband and beam-blockage errors, worst in the mountain West (SEA, LAX, SFO,
LV, PHX, DEN tiles), and coastal tiles include ocean beyond radar range, which is flagged NaN.

Secondary truths, not prototyped:
- `MultiSensor_QPE_01H_Pass2`, gauge-corrected hourly accumulation (24 files a day, 0.57 MB
  each measured), for an hourly-accumulation column;
- the ASOS hourly precipitation at the station gauge (IEM, as WM-1's truth), the "rain at the
  station gauge" column the track doc promises; a station pixel score against MRMS is in the
  prototype.

## Inputs available at the init

| Source | What | Rule | Measured size |
| --- | --- | --- | --- |
| `radar` | MRMS PrecipRate tiles, 512 x 512 pixels (about 1,000 km) around each station, 10-minute frames | valid strictly before the init (the latest is init - 10 min); any earlier time, back to 2020-10-14 | 0.5 MB per CONUS file; 64 MB a day to download at 10 minutes; 8.1 MB a day stored for 19 tiles of 256 pixels (about 4x for 512) |
| `radar_products` (optional) | other MRMS fields on the same tiles, e.g. `MergedReflectivityQCComposite`, `PrecipFlag` | as `radar` | composite reflectivity 900 MB a day at 2 minutes (1.25 MB a file); PrecipFlag 135 MB a day |
| `satellite` (optional) | GOES-19 ABI L2 cloud and moisture imagery, CONUS sector, band 13 (10.3 um), 5-minute | scan end strictly before the init | 3.9 MB a file, 47 MB an hour, 1.1 GB a day for one band; NetCDF4, so a reader dependency; western tiles are better seen by GOES-18 |
| `ensembles` | WM-1's captured station ensembles | as in WM-1 | about 1 MB a day |

The input box is larger than the scored box because rain moves in from outside: in the
prototype, with 256-pixel inputs (128 km of margin each side) and tile motions of 40 to 70 km/h,
an advection nowcast lost its skill to persistence after 2 to 3 h because the inflow was
unknown. 512 pixels give 192 pixels each side, about 330 km east-west and 430 km north-south
at 40 N: enough for 3 h at 110 km/h and for 6 h at 55 km/h. An entry may also read the whole CONUS mosaic if WM-2 serves it; that is an open
decision (below), since it multiplies storage by about 25.

## Leakage rules (mirroring WM-1, `forward/wm/access.py`)

1. **The shim is the only door.** `predict` gets `inputs`; `inputs.radar(times)` returns
   frames for times strictly before the init and raises `LeakageError` for any later time
   (`forward/wm2/access.py`). The init's own frame is excluded because it would not exist at a
   live read (MRMS publishes about 3 minutes after the valid time).
2. **Declared sources only.** A source the manifest does not declare raises `LeakageError`.
3. **The guard.** While `predict` runs, WM-1's guard refuses network connections,
   subprocesses and opening files under the data directories (imported, not changed).
4. **Invariance test.** Every baseline is rerun with every frame at or after the init
   replaced by nonsense and must give identical forecasts (`tests/test_wm2.py`).
5. **The seal is on the model.** An entry is code plus weights, hashed in a manifest and
   committed before the window's first init, as in WM-1. WM-2 adds one risk WM-1 does not
   have: MRMS is publicly archived within minutes, so anything trained or tuned after the
   window opens could have seen the window. The commit-time check is therefore the rule, and
   there is no exception for "retrained on the same recipe".
6. **Captured inputs and truth are hashed.** Each captured day is a compressed file plus a
   manifest holding its sha256 and, per frame, the source key, size and S3 ETag
   (`forward/wm2/store.py`); a file whose hash differs is refused. Because the archive is
   complete, a missed capture can be filled from the bucket later; the manifest records when.
7. **Past years are allowed.** Frames from any earlier time are inputs, so an analogue
   climatology or a model trained on 2020 to 2026 data is legitimate if frozen before the window.

## Entry signature

```
predict(init_time, tiles, inputs) -> float array [K, len(tiles), len(leads), 128, 128]
```

Rain rate in mm/h on each tile's scored box; NaN means no forecast and drops that pixel for
every entry. The manifest is WM-1's (`forward/wm/entry.py`) with `family: "wm2"`, inputs from
`radar`, `radar_products`, `satellite`, `ensembles`, `K: 20`, `leads` as the list of minutes,
and `variables: ["rain_rate"]`. Forecasts are stored as uint16 tenths of mm/h (MRMS's own
precision) in compressed `.npz`: measured 1.2 to 2.6 MB per init for 6 tiles, against 79 MB
as float32. Admitting the new input names in WM-1's manifest checker is part of building
WM-2; WM-1's behaviour does not change.

Why K = 20 and not WM-1's 50: a forecast is about 400 times larger per station than WM-1's
(20 x 10 x 128 x 128 numbers against 50 x 168), and the fair scores below are unbiased in K, so
a smaller K costs precision, not fairness. A round fixes K for every entry.

## Scores

All lower is better unless stated; the same pixels and rows for every entry; intervals resample
whole init dates (`forward/metrics.py`).

Primary (candidates for pre-registration, at most two):
- **Fair energy score of the 32 km field** (Gneiting and Raftery 2007; fair form, Ferro 2014):
  each tile's sample fields averaged over 16 x 16 pixels (64 numbers), per (init, tile, lead),
  averaged over leads to 3 h. Proper and multivariate, so it rewards the right pattern and
  spread, not only the right pixel values; the 32 km pooling keeps it from punishing a small
  displacement as a miss and a hit. Its weak sensitivity to correlation (Pinson and Tastu 2013)
  is why the variogram score (Scheuerer and Hamill 2015) on the same 64 numbers is a candidate
  secondary.
- **Threshold-weighted CRPS at 1 mm/h** on 8 km-pooled cells (Gneiting and Ranjan 2011; the
  sample form of Allen et al. 2023): CRPS after the chaining map max(x, 1 mm/h), so dry pixels,
  about 92% of the prototype's, cannot dominate the ranking. The prototype found that plain
  per-pixel CRPS lets a mostly dry climatology look nearly as good as advection at long leads.

Secondary (reported):
- fair CRPS of fields average-pooled to 2, 8 and 32 km, and max-pooled to 8 and 32 km
  (pooled CRPS as in Ravuri et al. 2021);
- fractions skill score (Roberts and Lean 2008) of the ensemble neighbourhood exceedance
  probability (Schwartz et al. 2010) at 1, 4 and 8 mm/h over 2, 10 and 34 km. Not proper, so
  never ranked on; reported because it is the field's common language;
- Brier score and reliability of exceedance at 1 and 4 mm/h on 8 km cells, and the PIT of
  pooled cells for calibration;
- fair CRPS at the station's own pixel and, when added, against the ASOS gauge.

Conditioning: scores are also reported on the rows where rain was observed in the scored box
at the init (known at the init, so the subset is chosen without the outcome and the score stays
proper), never on rows selected by the truth.

## Baselines

| Baseline | Method | Built |
| --- | --- | --- |
| `persistence` | the latest frame, the same in every sample (Eulerian persistence) | prototype |
| `climatology` | the observed sequences at the same time of day in the past four years at offsets up to two days (20 analogues), reserve offsets for missing frames | prototype |
| `advection` | Lagrangian persistence (Germann and Zawadzki 2002): one cross-correlation motion vector per tile (a global form of TREC, Rinehart and Garvey 1978), perturbed per sample as STEPS perturbs motion (Bowler et al. 2006) | prototype |
| `steps` | pySTEPS (Pulkkinen et al. 2019; BSD-3-Clause): dense optical flow (Lucas-Kanade or VET), STEPS cascade with stochastic noise (Bowler et al. 2006; Seed 2003) | to build; the licence permits use and redistribution |
| `dgmr` | DGMR (Ravuri et al. 2021) as an entrant, not a baseline: code Apache 2.0; the released snapshot was trained on UK radar and its terms need checking before use; it would need fine-tuning on MRMS, which needs a GPU | candidate |
| `hrrr` | NOAA HRRR forecasts (public on the same open-data programme) as an NWP reference for 3 to 6 h | not checked |

## Cost per round on free hardware

A 56-day round, 19 tiles, four inits a day (224 inits), from the prototype's measured rates:

| Item | Size or time |
| --- | --- |
| Inputs and truth, downloaded | 144 CONUS files a day x 0.45 MB = 64 MB a day; about 3.6 GB a round, 12 s a day to fetch, decode and cut |
| Analogue frames for `climatology` | about 10,000 past frames, about 4.7 GB downloaded once, about 15 minutes |
| Tiles kept | about 0.45 GB a round at 256 pixels, about 1.8 GB at 512 |
| Forecasts per entry | about 4 to 8 MB per init as uint16 (19 tiles), about 1 to 2 GB a round |
| Baselines | about 4 s per init for all three on 19 tiles on one CPU (1.4 s measured for 6); about 15 minutes a round |
| Scoring | about 0.13 s per (entry, tile, init) measured, so about 10 minutes per entry a round |

All of it fits a laptop or a free GitHub Actions runner (public repository); nothing needs a
GPU except training a learned entry. Release assets hold the forecasts (each under the 2 GB
asset limit). The bucket needs no account and no credentials.

## Data terms

MRMS and GOES are distributed by the NOAA Open Data Dissemination (NODD) programme on the AWS
Open Data Registry (`s3://noaa-mrms-pds`, `s3://noaa-goes19`). The registry entries state:
"NOAA data disseminated through NODD are open to the public and can be used as desired. NOAA
makes data openly available to ensure maximum use of our data, and to spur and encourage
exploration and innovation throughout the industry. NOAA requests attribution for the use or
dissemination of unaltered NOAA data. However, it is not permissible to state or imply
endorsement by or affiliation with NOAA. If you modify NOAA data, you may not state or imply
that it is original, unaltered NOAA data." (read 2026-10-30). So tiles and scores can be
published with attribution, marked as modified, with no implied endorsement. pySTEPS is
BSD-3-Clause; the DGMR code is Apache 2.0. The MRMS software itself is licensed by the
University of Oklahoma; that concerns running MRMS, not using its published fields.

## Open decisions

1. Input box: 512-pixel tiles (proposed) or the whole CONUS mosaic (about 25x the storage).
2. Inits: four a day (proposed) or hourly, which multiplies scoring and forecast storage by 6
   with strongly dependent rows.
3. Primary horizon: 3 h (proposed), with 4 to 6 h exploratory.
4. Whether `satellite` is served in the first WM-2 round (a NetCDF dependency and about
   1 GB a day of downloads for one band).
5. Station gauge truth from ASOS, and how to treat trace and missing reports.
6. Whether a round needs a minimum of rain: dry weeks give rows that rank nothing; the
   conditioning rule above reports them separately rather than dropping them.

## Recommendation

**Go, as a prototype-backed plan, with the first WM-2 round after WM-1 has run.** The data are
free, credential-free, redistributable with attribution, archived since 2020 (so capture
failures are recoverable) and small at tile scale; the full pipeline runs on one CPU; the
forecasts are the only large object and fit free release storage once quantised. The risks are
scientific, not infrastructural: the truth is a radar estimate with regional biases, dry rows
dominate pixel scores (hence the threshold-weighted primary), and a sealed round needs the
manifest runner to admit the new inputs, which is the next piece of work.

## References

- Allen, S., Ginsbourger, D. and Ziegel, J. (2023). Evaluating forecasts for high-impact events
  using transformed kernel scores. *SIAM/ASA JUQ* 11(3).
- Bowler, N. E., Pierce, C. E. and Seed, A. W. (2006). STEPS: a probabilistic precipitation
  forecasting scheme which merges an extrapolation nowcast with downscaled NWP. *QJRMS*
  132(620).
- Ferro, C. A. T. (2014). Fair scores for ensemble forecasts. *QJRMS* 140(683).
- Germann, U. and Zawadzki, I. (2002). Scale-dependence of the predictability of precipitation
  from continental radar images. Part I: description of the methodology. *Monthly Weather
  Review* 130(12).
- Gneiting, T. and Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and
  estimation. *JASA* 102(477).
- Gneiting, T. and Ranjan, R. (2011). Comparing density forecasts using threshold- and
  quantile-weighted scoring rules. *JBES* 29(3).
- Pinson, P. and Tastu, J. (2013). Discrimination ability of the energy score. Technical
  University of Denmark.
- Pulkkinen, S. et al. (2019). Pysteps: an open-source Python library for probabilistic
  precipitation nowcasting (v1.0). *Geoscientific Model Development* 12(10).
- Ravuri, S. et al. (2021). Skilful precipitation nowcasting using deep generative models of
  radar. *Nature* 597.
- Rinehart, R. E. and Garvey, E. T. (1978). Three-dimensional storm motion detection by
  conventional weather radar. *Nature* 273.
- Roberts, N. M. and Lean, H. W. (2008). Scale-selective verification of rainfall accumulations
  from high-resolution forecasts of convective events. *Monthly Weather Review* 136(1).
- Scheuerer, M. and Hamill, T. M. (2015). Variogram-based proper scoring rules for
  probabilistic forecasts of multivariate quantities. *Monthly Weather Review* 143(4).
- Schwartz, C. S. et al. (2010). Toward improved convection-allowing ensembles: model physics
  sensitivities and optimizing probabilistic guidance with small ensemble membership.
  *Weather and Forecasting* 25(1).
- Seed, A. W. (2003). A dynamic and spatial scaling approach to advection forecasting.
  *Journal of Applied Meteorology* 42(3).
- Zhang, J. et al. (2016). Multi-Radar Multi-Sensor (MRMS) quantitative precipitation
  estimation: initial operating capabilities. *BAMS* 97(4).
- Zhang, Y. et al. (2023). Skilful nowcasting of extreme precipitation with NowcastNet.
  *Nature* 619.
