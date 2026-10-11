# Round 2: station highs again, and price ladders against copying

Status: **draft**. Frozen, with its sha256 and every scoring file's hash in `frozen/round2.json`,
no later than 2027-01-03 23:59 UTC. Deviations are reported beside the original text.

Window: target days and ladder closes from 2027-01-04 to 2027-02-28 inclusive (8 weeks).

## Task 1: station highs

As in [ROUND1.md](ROUND1.md), with the entries refit on data settled by 2027-01-02. The same four
tests (H1 to H4) are run again; a result that holds in both rounds counts for more than either.

## Task 2: Kalshi price ladders

- **Ladders:** Kalshi's daily ladders on the S&P 500 (KXINX), Nasdaq-100 (KXNASDAQ100), EUR/USD,
  USD/JPY, WTI, Brent, gold, silver, copper and natural gas, every event that closes in the window.
- **Reads:** 24 h and 6 h before the ladder closes. 24 h is primary.
- **Inputs:** the underlying's hourly closes from Yahoo up to the read (`forward/prices.py`; the
  bar that closed by the read, no later). A learned entry sees the last 512 bars.
- **Truth:** each market's Kalshi result.
- **Problems:** a ladder needs at least two two-sided quotes at the read and at least 256 bars of
  context; the same problems are scored for every entry.

### Entries

| Entry | What it is |
| --- | --- |
| copy | lognormal centred on the last price, spread from same-clock-window log moves over the previous 60 days, no drift |
| chronos-bolt-small, chronos-bolt-base | Chronos-Bolt, zero-shot, revisions pinned in `forward/tsfm.py` |
| timesfm-2.5 | TimesFM 2.5 200M, zero-shot, revision pinned |
| each learned model's "-centre" | its median with the copy baseline's spread: does it know where the price goes? |

A learned entry's 10th, 50th and 90th percentiles at the close are read as a lognormal (median,
and the 10-to-90 width). The round scores only the entries above.

### Pre-registered tests (24 h primary, 6 h secondary)

- **P1 (does it beat copying?):** each learned entry's log score minus copy. Passes if the CI is
  above 0.
- **P2 (direction):** each learned entry's "-centre" variant minus copy. Passes if the CI is above 0.
  Also reported: the share of ladders where the median move points the way the price went.
- **P3 (market):** copy minus the bid-priced market. Reported as context; the round 0 dry run
  found +1.30 at 24 h.
- **P4 (decision value):** each entry's taker P&L after Kalshi fees and 1 cent of slippage, with
  a per-ladder CI. Passes if the CI is above 0.

What the dry run found (2,609 past ladders, not sealed): no learned entry beats copy, direction
hit rates are 49 to 50%, and every "-centre" variant is below copy. The round tests that on
ladders none of the models could have seen.

## Scoring

After 2027-03-02: `uv run scripts/score.py --round 2` for task 1 (with the round 2 ledger) and
`uv run --extra tsfm scripts/score_prices.py --round 2` for task 2. Both check every hash first.
