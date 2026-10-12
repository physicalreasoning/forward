# Task 3: fills under intervention

A world model should be judged by whether the outcome it imagines for an action matches what
actually happens when the action is taken. Tasks 1 and 2 score forecasts of systems nobody
acts on. Task 3 scores forecasts of how an order book reacts to an action: a hypothetical
limit order.

The trick that makes it cheap: Kalshi matches orders by price and then time, and the matching
is deterministic. If we hold everyone else's orders fixed, the order flow we recorded tells us
what would have happened to an order we did not send. That gives counterfactual ground truth
for every action we care to imagine, without trading.

**Status:** a dry run on the first 27 hours of recorded books. It checks the pipeline end to end;
it is not a result. The section on Round 3 is a draft spec and is not frozen.

## The task

**Action.** A passive limit order `(market, t0, side, level, size)`. `side` is YES or NO (both
are bids on Kalshi's book: a NO bid at p is a YES offer at 100 - p). `level` is in cents relative
to the best bid on that side: +1 (improve by a cent, only if that does not cross the spread),
0 (join the best bid), -1, -3. `size` is 1, 10 or 100 contracts.

**Decision times.** Every 10 minutes (UTC) for every recorded market where the book has bids on
both sides and the mid is between 5 and 95 cents. The market's book must come from a snapshot
taken before the 30-minute lookback started, and no gap may touch `[t0 - 30 min, t0]`.

**Outcomes**, for horizons of 5 minutes, 30 minutes and 2 hours:

1. **Fill.** `y = 1` iff the whole order would have filled by `t0 + h`.
2. **Move after the fill.** The mid five minutes after the fill minus the mid at the fill, in
   cents, signed in the order's favour (negative is adverse selection). Measured on rows that
   filled within h. The mid comes from the recorded book, without our order in it.

A row has a label at horizon h only if the record is clean, meaning no gap, from t0 - 30 min to
t0 + h. A move needs a clean record to the fill + 5 min. No label spans a gap.

**What an entry sees.** The book at t0 and the 30 minutes of flow before it: its own queue, size
at better prices, depth on both sides, spread, mid, executions and cancellations on its side,
and executions at or through its price. An entry returns a fill probability for each horizon
and an expected move.

## Data

isotherm's recorder (`scripts/book/record.py` there) subscribes to Kalshi's `orderbook_delta`
and `trade` channels for every open weather and commodity ladder (about 640 markets at a time;
1,042 over the dry run). It writes the raw messages, with our receive time, to
`data/book/raw/YYYY-MM-DD/HH[-run].jsonl.gz`. `forward/fills.py` reads these files and never
writes to them. It skips the hour still being written. It copies `read_lines` and `file_order`
from isotherm's `scripts/book/replay.py`, which recovers files cut by a crash. That script
rebuilds books that match Kalshi's REST book (34 of 40 identical, 40 of 40 at the best bids).

**Executions and cancellations.** The feed has no order IDs. A level shrinks by a negative
delta, which is either an execution or a cancellation. In the dry run's record, every trade
(96,047 of 96,047) had exactly one negative delta with the same market, resting side, price,
size and exchange timestamp. So a negative delta counts as an execution iff such a trade exists,
matched one to one. Everything else is a cancellation.

**Gaps.** A gap is any stretch where the record may be incomplete. There are four sources,
merged:

1. **Logged outages.** The recorder's `gaps.jsonl`: each disconnect or sequence jump, from 60 s
   before it is logged (a keepalive timeout is detected late) until the reconnect.
2. **Session restarts.** Restarts visible in the data: a new subscription means a new session,
   with fresh snapshots. The first recorder version did not log every outage. For example, its
   file for 18:00 UTC on 10-11 stops at 18:43 and nothing is logged until 19:31.
3. **Silence.** Any 60 s with no message from any market. This is conservative at night, when
   quiet markets can look like a dead link.
4. **The edges.** Before the first message and after the last.

In the dry run, 13.4 of 26.9 recorded hours were clean.

## The simulator and its assumptions

`fills.simulate` follows the volume that would have reached our order (assumptions 1 to 5 below
spell out what reaches us):

| Event after t0 | Effect on the queue ahead of us (A) | Volume reaching us |
| --- | --- | --- |
| Execution at our price, size v | A falls by min(A, v) | the rest, v - min(A, v) |
| Cancellation at our price, size c | pro rata: A falls by c A / L; back of queue: A = min(A, L - c) | none |
| Order added at our price | none (it queues behind us) | none |
| Execution on our side at a worse price, size v | A = 0 | v |
| Order added on the other side at a price that crosses ours, size v | A = 0 | v (primary labels only) |

L is everyone else's size at our price. An order of size q is completely filled at the first
time the cumulative volume reaching it is at least q.

1. **Price-time priority, and we join the back.** At t0 our order sits behind everything at its
   price. This is Kalshi's matching rule; the time at which our order would arrive is the one
   point of discretion. We use our receive clock, which lags the exchange by tens of
   milliseconds, so a real order would arrive later still.
2. **Executions are identified exactly** by matching trades to deltas, as above.
3. **Cancellations are pro rata (primary) or from the back (lower bound).** The feed does not
   say whose order was cancelled. Pro rata says each contract resting at the level is equally
   likely to be the one cancelled, which is the assumption that adds the least. Back of queue
   says no cancellation ever comes from ahead of us until the level is smaller than our
   position, which is the worst case for us.

   The two barely differ in the dry run: fill rates of 23.5% and 23.2% at 30 minutes. The
   reason is that we join at the back, so the rules diverge only once someone queues behind us.
4. **A trade through our price would have hit us first.** A seller who traded below our price
   would, by price priority, have traded with our order first.
5. **A crossing order would have traded with us (primary).** Sometimes a market reprices
   without trading through us: the best bid on our side vanishes and an offer appears at or
   through our price. In the record the new offer rested, because nothing was there to match
   it. With our order there, a plain limit order would have executed against us.

   This mechanism completes **54 to 57% of all counterfactual fills** in the dry run. That
   makes it the assumption that matters most. A post-only order would instead have been
   rejected, and a market maker who saw our bid might have quoted a cent higher. The
   `_no_cross` label variants drop these fills, as if every crossing order had been post-only.
   Under them, the 30-minute fill rate falls from 23.5% to 13.4%. We report every entry's score
   under all four variants (two cancellation rules, with and without crossing orders).
6. **Nobody reacts to our order.** This is the main limit, and we cannot test it from the
   record. A real order is visible. A 100-lot at the best bid changes the depth others see:
   market makers may step ahead of it, pull their quotes, or lean on it. Takers may pick it
   over others, and an informed trader may hit it precisely because it is there. None of this
   is in the record, because the order was never sent. The labels are first-order
   counterfactuals: what the matching engine would have done with everyone else's actions held
   fixed. They are exact under that assumption and say nothing about second-order reactions.
   The larger the order relative to the level, the less they should be trusted.

Other limits:

- **Fees.** Kalshi charges fees on some maker fills; the move is measured in mid-price cents
  before fees.
- **The mid excludes our order.** It is the recorded book's mid.
- **Market close.** An order whose market closes inside the horizon simply stops filling.
- **Selection by gaps.** Excluding windows with gaps may favour calm periods, if disconnects
  cluster when traffic is heavy.
- **One venue, two kinds of ladder.** The record covers weather and commodity ladders only.

The offline tests (`tests/test_fills.py`) build a book by hand and check each rule against
answers worked out on paper:

- the queue ahead clearing before us
- orders added behind us
- pro rata against back-of-queue cancellations
- trades through our price, and crossing orders
- the price-improving and deeper levels
- trade-to-delta matching when the trade arrives first
- lookback features that see only the past
- labels cut by a gap
- gaps from the log, from silences and from restarts
- reading a file with a stream cut by a crash

## Entries

| Entry | Fill probability | Move |
| --- | --- | --- |
| base-rate | training fill frequency by level and size (Laplace-smoothed) | training mean move by level, shrunk to 0 |
| copy | training fill frequency given one bit: did anything trade at or through our price in the last 30 minutes | 0 (the mid is a martingale) |
| queue | Cont, Stoikov and Talreja (2010) queue depletion: see below | 0 |
| queue-cal | the queue model's log-odds recalibrated on training days, a + b logit(p) (Platt 1999) | 0 |
| logistic | L2-penalised logistic regression on 19 book and flow features | ridge regression on the same features |

**copy** is the analogue of copying yesterday's high in Task 1: it assumes the next window
repeats the last one.

**queue** treats the size ahead of us at our price as a death process, as in Cont, Stoikov and
Talreja (2010):

- Executions that reach our price arrive as a Poisson process at rate mu, with mean size m.
- Each contract ahead of us cancels at rate theta.
- The time to fill is a sum of exponentials, with rates mu + theta j for the j contracts' worth
  ahead and mu for each of our own. We read it as a gamma with the same mean and variance, which
  is exact when nobody is ahead.
- mu, m and theta come from the market's own last 30 minutes, shrunk to the training averages,
  with a gamma posterior on mu integrated out.

Raw against calibrated mirrors Task 1's raw and EMOS entries. It separates whether the queue
model ranks orders well from whether its probabilities are right.

Entries are fit on rows whose labels and moves resolved before the cutoff and scored on decision
times after it, on the same rows for every entry.

## Metrics

Per horizon, per entry:

- **Proper scores.** Log score of the binary fill outcome (floored at 1e-6) and the Brier score,
  each with a 95% block-bootstrap interval (`metrics.block_ci`). Differences against base-rate
  and copy use the same blocks.
- **Calibration.** A ten-bin reliability table and the expected calibration error.
- **Trivial solutions.** base-rate and copy for fills; a zero move for the move.
- **Label sensitivity.** The fill rate and every entry's log score under all four label variants.
- **Move.** Mean absolute error and RMSE in cents on filled rows, and the squared-error
  difference against predicting no move. Also the realised mean move, which is the adverse
  selection a passive order pays.

Blocks are dates (America/New_York) in a round. The dry run has one test date, so it uses hour
blocks and marks every horizon `"intervals_meaningful": false`, because there are fewer than 10
blocks. Read its intervals as a check that the code runs, not as uncertainty.

Of the six columns in the README, there is no market to compare against here, since nothing on
Kalshi prices a fill. Decision value is left for Round 3 (below).

## Dry run (pipeline check, not a result)

Recorded 2026-10-11 16:07 to 2026-10-12 19:00 UTC; 18.5 million events; 13.4 clean hours.
337,761 actions (market, t0, side, level, size). Training data is the ET evening of 10-11 and
the test data is the ET morning of 10-12, so the test spans 21 decision times at 5 minutes and
5 at 2 hours. Full output: [results/fills_dry_run.json](../results/fills_dry_run.json).

Fill rates on the test rows:

| Horizon | Test rows (fills) | Fill rate | Without crossing orders | Fills completed by: crossing order / trade through / execution at our price |
| --- | --- | --- | --- | --- |
| 5 min | 158,052 (12,884) | 8.2% | 4.3% | 54% / 26% / 20% |
| 30 min | 116,094 (27,305) | 23.5% | 13.4% | 57% / 20% / 23% |
| 2 h | 40,059 (16,374) | 40.9% | 26.9% | 56% / 19% / 25% |

Log score minus base-rate (nats per action; hour blocks: 5, 5 and 2 of them, so the intervals
are not meaningful):

| Entry | 5 min | 30 min | 2 h |
| --- | --- | --- | --- |
| base-rate (log score) | -0.267 | -0.520 | -0.653 |
| copy | +0.016 [+0.006, +0.028] | +0.029 [+0.020, +0.042] | +0.032 [+0.015, +0.037] |
| queue | -0.541 [-0.560, -0.523] | -0.865 [-0.900, -0.827] | -0.926 [-0.932, -0.902] |
| queue-cal | -0.008 [-0.012, -0.002] | +0.007 [+0.003, +0.014] | +0.029 [+0.017, +0.033] |
| logistic | +0.067 [+0.058, +0.081] | +0.118 [+0.110, +0.131] | +0.139 [+0.138, +0.141] |

Expected calibration error at 30 minutes:

| Entry | ECE |
| --- | --- |
| base-rate | 0.024 |
| copy | 0.017 |
| queue | 0.393 |
| queue-cal | 0.062 |
| logistic | 0.035 |

Move after a fill, at 30 minutes:

| Measure | Value |
| --- | --- |
| Realised mean move | -0.08 cents [-0.29, -0.02] |
| RMSE, predicting no move | 2.74 cents |
| RMSE, base-rate | 2.74 cents |
| RMSE, logistic | 2.75 cents |

What the dry run shows about the pipeline (not about the world):

- **The queue model as specified is badly overconfident in both directions.** It knows nothing
  about the crossing mechanism that completes most fills. Once recalibrated it is close to the
  base rate, so its ranking carries little information here.
- **A logistic model on book features beats both trivial baselines** by a margin that would
  matter if it held on held-out dates.
- **Nothing beats predicting no move after a fill.**
- **The cancellation rule hardly matters; the crossing-order rule matters a lot.** Round 3 must
  pre-register which variant is primary.

## Round 3 (draft, not frozen)

- **Window.** Eight weeks of decision times after the freeze. The cutoff is the day before;
  entries are fit on every clean day recorded by then.
- **Primary label.** `pro_rata`, with crossing orders filling us. All four variants are scored
  and published.
- **Primary horizon.** 30 minutes. Sizes 1 and 10 are primary, and 100 is reported. A 100-lot is
  where "nobody reacts" is least credible.
- **Blocks.** America/New_York dates. A date counts only if it has at least 6 clean hours, and
  the round needs at least 28 such dates. If the recorder is down for more than a quarter of the
  window, the round is void and published as such.
- **Seal.** The truth here is our own recording, so the freeze must also cover the data:
  - Within an hour of each file closing, its sha256 is committed to the public `ledger` branch.
    The scorer refuses any file whose hash differs or whose ledger commit is late, and drops the
    hour.
  - `gaps.jsonl` is hashed the same way.
  - The frozen round records the sha256 of `forward/fills.py`, `forward/fill_entries.py`,
    `scripts/score_fills.py`, this spec, and every entry's fitted parameters.
- **Pre-registered tests.** Each is a log score (or squared error) difference with a 95%
  date-block interval:
  1. logistic minus base-rate at 30 minutes > 0;
  2. logistic minus copy at 30 minutes > 0;
  3. queue-cal minus base-rate at 30 minutes > 0, meaning the queue model's ranking carries
     information;
  4. the realised mean move after a fill at level 0 < 0, meaning passive fills are adversely
     selected;
  5. the ranking of the entries at 30 minutes is the same under `pro_rata_no_cross` labels.
- **Decision value**, to be specified before freezing: a quoting policy that posts at the level
  maximising predicted fill probability times (predicted move + half-spread), scored on the
  counterfactual fills it would have had, after Kalshi's maker fees.

## Reproduce

```bash
uv run pytest tests/test_fills.py tests/test_fill_entries.py   # offline, synthetic books
uv run scripts/score_fills.py --end 2026-10-12T19:00           # needs isotherm's data/book (read only)
```

The parsed events and samples are cached in `data/fills/` (git-ignored), about 250 MB for a
day of books. Parsing takes about a minute on 8 cores.

## References

- Cont, R., Stoikov, S. and Talreja, R. (2010). A stochastic model for order book dynamics.
  *Operations Research* 58(3), 549-563.
- Glosten, L. R. and Milgrom, P. R. (1985). Bid, ask and transaction prices in a specialist
  market with heterogeneously informed traders. *Journal of Financial Economics* 14(1), 71-100.
- Gneiting, T. and Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and
  estimation. *JASA* 102(477).
- Platt, J. (1999). Probabilistic outputs for support vector machines and comparisons to
  regularized likelihood methods. In *Advances in Large Margin Classifiers*, MIT Press.
- Physical Reasoning (2026). isotherm: the order-book recorder and replay
  (`scripts/book/record.py`, `scripts/book/replay.py`). https://github.com/physicalreasoning/isotherm
