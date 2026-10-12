"""Task 3: fills under intervention. Counterfactual ground truth for a hypothetical limit order.

The action is a passive limit order (market, time, side, price relative to the best bid on its
side, size). Kalshi's matching engine is price-time priority and deterministic, so given the
recorded order flow we can replay what would have happened to that order: where it sits in the
queue, whether and when it fills, and how the mid-price moves after the fill.

Data: isotherm's order-book recorder (scripts/book/record.py), raw websocket messages with our
receive time, read only. `read_lines` and `file_order` are copied from isotherm's
scripts/book/replay.py (a script, not part of the installed package).

Units: prices in hundredths of a cent (PU per cent), so sub-cent ticks stay exact; times in ms
of our receive clock. Both sides of a Kalshi book are bids: a NO bid at p is a YES offer at
100 - p cents, so an order of either side is a bid resting on its own side.

The simulator's assumptions (docs/TASK3_FILLS.md has the reasoning and the limits):
1. Price-time priority. Our order joins the back of the queue at its price at t0.
2. A negative delta at a level is an execution iff a trade with the same market, resting side,
   price, size and exchange timestamp exists (true for every trade checked); otherwise it is a
   cancellation.
3. Cancellations at our level come from ahead of us in proportion to the share of the level
   ahead ("pro_rata", the primary labels) or only from behind us until the level is smaller
   than our position ("back", a lower bound on fills).
4. Executions at our price fill the queue ahead first, then us. Executions on our side at a
   worse price, and resting orders added on the other side that would cross our price, would
   have traded with us first: all of their size reaches us.
5. Nobody reacts to our order. This cannot be checked from the record and is the main limit.
"""

from __future__ import annotations

import json
import math
import pathlib
import zlib
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

PU = 100  # price units per cent
FULL = 100 * PU  # $1

HORIZONS = {"5m": 300_000, "30m": 1_800_000, "2h": 7_200_000}
MOVE_MS = 300_000  # mid move measured this long after the fill
GRID_MS = 600_000  # one decision time per market every 10 minutes
LOOKBACK_MS = 1_800_000  # features see the 30 minutes before t0, which must be gap-free too
SIZES = (1, 10, 100)
LEVELS = (1, 0, -1, -3)  # cents relative to the best bid on the order's side
MID_RANGE = (5, 95)  # cents; outside it the book is a settled tail
SILENCE_MS = 60_000  # no message from any market for this long counts as a gap
PAD_MS = 60_000  # a logged disconnect is detected up to a ping timeout after the link died
RULES = ("pro_rata", "back")
COMMODITIES = ("KXWTI", "KXGOLDD", "KXSILVERD", "KXCOPPERD", "KXBRENTD", "KXNATGASD")

SUB, SNAP, LEVEL, DELTA, TRADE = 0, 1, 2, 3, 4  # row kinds
YES, NO = 0, 1
CANCEL, EXEC, ADD, THROUGH = 0, 1, 2, 3  # simulator events


# Reading the recorder's files ---------------------------------------------------------------


def read_lines(path, chunk=1 << 14):
    """Every line recoverable from a gzip file, even one with an unfinished stream inside.

    Copied from isotherm scripts/book/replay.py: a killed recorder can leave a cut stream with a
    new one appended after it; each stream is decompressed until it breaks, then we resume at
    the next gzip header.
    """
    data = pathlib.Path(path).read_bytes()
    pos = 0
    while pos < len(data):
        d, out, end = zlib.decompressobj(31), [], None
        i = pos
        try:
            while i < len(data) and not d.eof:
                out.append(d.decompress(data[i : i + chunk]))
                i += chunk
            end = len(data) - len(d.unused_data) if d.eof else len(data)
        except zlib.error:
            nxt = data.find(b"\x1f\x8b\x08", max(i - chunk, pos + 1))
            end = nxt if nxt > 0 else len(data)
        text = b"".join(out).decode("utf-8", errors="replace")
        yield from text.splitlines()
        pos = end


def file_order(f: pathlib.Path):
    """(date, hour, run start); files from before per-run naming (HH.jsonl.gz) count as run 0."""
    hour, _, run = f.name.split(".")[0].partition("-")
    return f.parent.name, int(hour), int(run or 0)


def file_start_ms(f: pathlib.Path) -> int:
    d, h, _ = file_order(f)
    return int(pd.Timestamp(f"{d} {h:02d}:00", tz="UTC").value // 1_000_000)


def _px(s) -> int:
    return int(round(float(s) * FULL))


def parse_file(path) -> pd.DataFrame:
    """One row per book event: subscriptions (session starts), snapshot markers and levels,
    deltas and trades. Trades carry the side and price of the order they executed against."""
    rows = []
    for n, line in enumerate(read_lines(path)):
        try:
            rec = json.loads(line)
            m = rec["m"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue  # a line cut off at a crash
        t, msg, recv = m.get("type"), m.get("msg") or {}, rec["recv_ms"]
        tk = msg.get("market_ticker", "")
        if t == "subscribed":
            rows.append((n, recv, recv, SUB, "", -1, 0, 0.0))
        elif t == "orderbook_snapshot":
            rows.append((n, recv, recv, SNAP, tk, -1, 0, 0.0))
            for side, key in ((YES, "yes_dollars_fp"), (NO, "no_dollars_fp")):
                for p, q in msg.get(key) or []:
                    rows.append((n, recv, recv, LEVEL, tk, side, _px(p), float(q)))
        elif t == "orderbook_delta":
            side = YES if msg["side"] == "yes" else NO
            ts = msg.get("ts_ms", recv)
            rows.append((n, recv, ts, DELTA, tk, side, _px(msg["price_dollars"]), float(msg["delta_fp"])))
        elif t == "trade":
            # The taker bought `taker_side`, so the resting order was a bid on the other side.
            side = NO if msg["taker_side"] == "yes" else YES
            px = msg["no_price_dollars"] if side == NO else msg["yes_price_dollars"]
            rows.append((n, recv, msg.get("ts_ms", recv), TRADE, tk, side, _px(px), float(msg["count_fp"])))
    cols = ["n", "recv", "ts", "kind", "tk", "side", "px", "qty"]
    df = pd.DataFrame(rows, columns=cols)
    return df.astype({"n": "int32", "kind": "int8", "side": "int8", "px": "int32"})


def raw_files(raw: pathlib.Path, end_ms: int) -> list[pathlib.Path]:
    """Closed hourly files only: anything starting at or after `end_ms` may still be written."""
    files = sorted(pathlib.Path(raw).glob("*/*.jsonl.gz"), key=file_order)
    return [f for f in files if file_start_ms(f) + 3_600_000 <= end_ms]


def load_events(raw: pathlib.Path, end_ms: int, workers: int = 8) -> pd.DataFrame:
    """All events from closed files, in recording order (file order, then line)."""
    files = raw_files(raw, end_ms)
    with ProcessPoolExecutor(workers) as ex:
        parts = list(ex.map(parse_file, files))
    for i, p in enumerate(parts):
        p.insert(0, "f", np.int16(i))
    ev = pd.concat(parts, ignore_index=True)
    ev = ev[ev["recv"] < end_ms].reset_index(drop=True)
    # Receive times step back by a few ms once in a while (clock adjustments); keep the
    # recording order and make the clock monotone so times can be searched.
    ev["recv"] = np.maximum.accumulate(ev["recv"].to_numpy())
    ev["tk"] = ev["tk"].astype("category")
    return mark_exec(ev)


def mark_exec(ev: pd.DataFrame) -> pd.DataFrame:
    """Flag negative deltas that are executions: a trade with the same market, side, price,
    size and exchange time. Duplicates are matched one to one."""
    keys = ["tk", "side", "px", "ts", "qty"]
    neg = ev.index[(ev["kind"] == DELTA) & (ev["qty"] < 0)]
    d = ev.loc[neg, keys].assign(qty=-ev.loc[neg, "qty"])
    tr = ev.loc[ev["kind"] == TRADE, keys]
    d["k"] = d.groupby(keys, observed=True).cumcount()
    tr = tr.assign(k=tr.groupby(keys, observed=True).cumcount(), hit=True)
    m = d.reset_index().merge(tr, on=[*keys, "k"], how="left").set_index("index")
    ev["exec"] = False
    ev.loc[m.index[m["hit"].fillna(False).astype(bool)], "exec"] = True
    return ev


# Gaps ---------------------------------------------------------------------------------------


def logged_gaps(path) -> list[tuple[int, int]]:
    """Disconnects and sequence jumps from the recorder's log, each until the next reconnect."""
    out, start = [], None
    p = pathlib.Path(path)
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = int(pd.Timestamp(r["ts"]).value // 1_000_000)
        if r.get("kind") in ("disconnect", "seq_jump") and start is None:
            start = ts - PAD_MS
        elif r.get("kind") == "reconnected" and start is not None:
            out.append((start, ts))
            start = None
    if start is not None:
        out.append((start, 2**62))
    return out


def merge(iv: Iterable[tuple[int, int]]) -> np.ndarray:
    iv = sorted(iv)
    out: list[list[int]] = []
    for a, b in iv:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return np.array(out, dtype=np.int64).reshape(-1, 2)


def gap_intervals(ev: pd.DataFrame, log_path, end_ms: int) -> np.ndarray:
    """Every stretch where the record may be incomplete, merged: logged disconnects and sequence
    jumps; session restarts seen in the data (a new subscription, which the old recorder did not
    always log); any silence across all markets over SILENCE_MS; before the first message and
    after the last one (or `end_ms`)."""
    t = ev["recv"].to_numpy()
    iv = list(logged_gaps(log_path))
    iv += [(-(2**62), int(t[0])), (int(min(t[-1], end_ms)), 2**62)]
    d = np.diff(t)
    for i in np.flatnonzero(d > SILENCE_MS):
        iv.append((int(t[i]), int(t[i + 1])))
    subs = np.flatnonzero(ev["kind"].to_numpy() == SUB)
    for i in subs[subs > 0]:
        iv.append((int(t[i - 1]), int(t[i])))
    # A session after a restart is valid only from its snapshots, which come right after the
    # subscription; each market's own snapshot time is enforced in `market_samples`.
    return merge(iv)


def next_gap(gaps: np.ndarray, t: int) -> int:
    """Start of the first gap ending after t (t itself may be inside it)."""
    i = np.searchsorted(gaps[:, 1], t, side="right")
    return int(gaps[i, 0]) if i < len(gaps) else 2**62


def clean(gaps: np.ndarray, a: int, b: int) -> bool:
    """True iff [a, b] touches no gap."""
    i = np.searchsorted(gaps[:, 1], a, side="left")
    return i >= len(gaps) or gaps[i, 0] > b


# The queue simulator ------------------------------------------------------------------------


def simulate(events, ahead: float, level: float, rule: str = "pro_rata"):
    """Cumulative volume that reaches our order, assuming it were unboundedly large.

    events: (t, kind, qty) in arrival order, kind in CANCEL, EXEC, ADD (at our price, others'
    orders), THROUGH (an execution at a worse price on our side, or a crossing order added on the
    other side). ahead: others' size ahead of us at t0 (the whole level: we join at the back).
    level: others' total size at our price. Returns (times, volumes), volume non-decreasing.

    Our order of size q is completely filled at the first time the volume reaches q.
    """
    if rule not in RULES:
        raise ValueError(rule)
    a, lv, v = float(ahead), float(level), 0.0
    ts, vs = [], []
    for t, kind, q in events:
        before = v
        if kind == EXEC:
            hit = min(a, q)
            a -= hit
            v += q - hit
            lv = max(lv - q, 0.0)
        elif kind == CANCEL:
            if rule == "pro_rata":
                a -= q * a / lv if lv > 0 else 0.0
            lv = max(lv - q, 0.0)
        elif kind == ADD:
            lv += q
        elif kind == THROUGH:
            a = 0.0  # anyone left ahead at our price would have traded first
            v += q
        a = max(min(a, lv), 0.0)  # the queue ahead is never more than the level
        if v > before:
            ts.append(t)
            vs.append(v)
    return np.array(ts, dtype=np.int64), np.array(vs, dtype=float)


def fill_time(ts: np.ndarray, vs: np.ndarray, q: float) -> int:
    """First time the cumulative volume reaching us covers size q (-1 if never)."""
    i = int(np.searchsorted(vs, q - 1e-9, side="left"))
    return int(ts[i]) if i < len(ts) else -1


def window_events(arr: dict, i0: int, i1: int, side: int, p: int) -> list[tuple[int, int, float]]:
    """The simulator's events for a bid at price p on `side`, from rows i0:i1 of one market."""
    t, k, s, px, q, ex = (arr[c][i0:i1] for c in ("recv", "kind", "side", "px", "qty", "exec"))
    delta = k == DELTA
    own = delta & (s == side)
    at = own & (px == p)
    through = own & ex & (px < p)
    cross = delta & (s != side) & (q > 0) & (px >= FULL - p)
    idx = np.flatnonzero(at | through | cross)
    out = []
    for j in idx:
        if at[j]:
            kind = ADD if q[j] > 0 else (EXEC if ex[j] else CANCEL)
            out.append((int(t[j]), kind, abs(float(q[j]))))
        elif through[j]:
            out.append((int(t[j]), THROUGH, -float(q[j])))
        else:
            out.append((int(t[j]), THROUGH, float(q[j])))
    return out


# Replaying one market -----------------------------------------------------------------------


def series_of(tk: str) -> str:
    return tk.split("-")[0]


def _best(book: dict) -> int:
    return max(book) if book else -1


def _mid(by: int, bn: int) -> float:
    if by < 0 or bn < 0:
        return math.nan
    return (by + FULL - bn) / 2 / PU  # cents


def market_samples(tk: str, g: pd.DataFrame, gaps: np.ndarray) -> list[dict]:
    """Every action at every valid decision time of one market, with its features and its
    counterfactual fill times under each cancellation rule.

    A decision time t0 is valid if the market's book came from a snapshot taken before the
    lookback started, no gap touches [t0 - LOOKBACK, t0], both sides have bids and the mid is
    inside MID_RANGE. The forward record is used only until the next gap (`valid_until`);
    labels whose window reaches past it are dropped when scoring.
    """
    arr = {c: g[c].to_numpy() for c in ("recv", "kind", "side", "px", "qty", "exec")}
    t, kind = arr["recv"], arr["kind"]
    n = len(t)
    books = ({}, {})
    snap_t = -1
    mids_t, mids_v = [], []
    states = {}  # t0 -> (books copy, snapshot time)
    grid = iter(range(int((t[0] // GRID_MS + 1) * GRID_MS), int(t[-1]), GRID_MS))
    t0 = next(grid, None)
    snaps = t[kind == SNAP]
    for i in range(n):
        while t0 is not None and t[i] > t0:
            states[t0] = (dict(books[YES]), dict(books[NO]), snap_t)
            t0 = next(grid, None)
        k = kind[i]
        if k == SNAP:
            books = ({}, {})
            snap_t = int(t[i])
        elif k == LEVEL:
            books[arr["side"][i]][int(arr["px"][i])] = float(arr["qty"][i])
        elif k == DELTA and snap_t >= 0:
            b = books[arr["side"][i]]
            p = int(arr["px"][i])
            b[p] = b.get(p, 0.0) + float(arr["qty"][i])
            if b[p] <= 1e-9:
                del b[p]
        else:
            continue
        m = _mid(_best(books[YES]), _best(books[NO]))
        if not mids_v or not (m == mids_v[-1] or (math.isnan(m) and math.isnan(mids_v[-1]))):
            mids_t.append(int(t[i]))
            mids_v.append(m)
    mids_t, mids_v = np.array(mids_t, dtype=np.int64), np.array(mids_v)

    def mid_at(x):
        j = np.searchsorted(mids_t, x, side="right") - 1
        return mids_v[j] if j >= 0 else math.nan

    is_exec = (kind == DELTA) & arr["exec"]
    is_cancel = (kind == DELTA) & ~arr["exec"] & (arr["qty"] < 0)
    out = []
    for t0, (by, bn, st) in states.items():
        if st < 0 or st > t0 - LOOKBACK_MS or not clean(gaps, t0 - LOOKBACK_MS, t0):
            continue
        books0 = (by, bn)
        best = (_best(by), _best(bn))
        if min(best) < 0:
            continue
        mid = _mid(*best)
        if not MID_RANGE[0] <= mid <= MID_RANGE[1]:
            continue
        later = snaps[snaps > t0]
        resnap = int(later[0]) if len(later) else 2**62
        until = min(next_gap(gaps, t0), resnap, t0 + max(HORIZONS.values()) + MOVE_MS)
        i0 = int(np.searchsorted(t, t0, side="right"))
        i1 = int(np.searchsorted(t, until, side="right"))
        l0, l1 = int(np.searchsorted(t, t0 - LOOKBACK_MS, side="left")), i0
        lb = slice(l0, l1)
        n_exec_all = int(is_exec[lb].sum())
        for side in (YES, NO):
            own_lb = arr["side"][lb] == side
            ex_lb, ca_lb = is_exec[lb] & own_lb, is_cancel[lb] & own_lb
            v_exec = float(-arr["qty"][lb][ex_lb].sum())
            v_cancel = float(-arr["qty"][lb][ca_lb].sum())
            min_exec_px = int(arr["px"][lb][ex_lb].min()) if ex_lb.any() else FULL
            depth = float(sum(books0[side].values()))
            ask = FULL - best[1 - side]  # lowest price we could pay without crossing
            for lvl in LEVELS:
                p = best[side] + lvl * PU
                if p < PU or p >= ask:
                    continue
                level = books0[side].get(p, 0.0)
                better = float(sum(q for x, q in books0[side].items() if x > p))
                evs = window_events(arr, i0, i1, side, p)
                fills = {r: simulate(evs, level, level, r) for r in RULES}
                base = {
                    "tk": tk,
                    "series": series_of(tk),
                    "t0": t0,
                    "valid_until": until,
                    "side": side,
                    "level": lvl,
                    "price": p / PU,
                    "mid": mid,
                    "spread": (ask - best[side]) / PU,
                    "queue": level,
                    "better": better,
                    "depth": depth,
                    "depth_other": float(sum(books0[1 - side].values())),
                    "n_exec": int(ex_lb.sum()),
                    "v_exec": v_exec,
                    "v_cancel": v_cancel,
                    "n_exec_all": n_exec_all,
                    "crossed": bool(min_exec_px <= p),
                }
                for q in SIZES:
                    row = {**base, "size": q}
                    for r in RULES:
                        tf = fill_time(*fills[r], q)
                        row[f"t_fill_{r}"] = tf
                        ok = tf >= 0 and tf + MOVE_MS <= until
                        sign = 1 if side == YES else -1
                        row[f"move_{r}"] = sign * (mid_at(tf + MOVE_MS) - mid_at(tf)) if ok else math.nan
                    out.append(row)
    return out


def _market_job(args):
    tk, g, gaps = args
    return market_samples(tk, g, gaps)


def build_samples(ev: pd.DataFrame, gaps: np.ndarray, workers: int = 8) -> pd.DataFrame:
    jobs = [
        (str(tk), g.drop(columns=["tk"]), gaps)
        for tk, g in ev[ev["kind"] != SUB].groupby("tk", observed=True, sort=True)
    ]
    with ProcessPoolExecutor(workers) as ex:
        rows = [r for part in ex.map(_market_job, jobs, chunksize=4) for r in part]
    return pd.DataFrame(rows)


def labels(df: pd.DataFrame, h: str, rule: str = "pro_rata") -> pd.DataFrame:
    """Rows with a label at horizon h: the record is clean until t0 + h. y = 1 iff the whole
    order filled by then; `move` is defined for filled rows whose post-fill window is clean."""
    hm = HORIZONS[h]
    d = df[df["t0"] + hm <= df["valid_until"]].copy()
    tf = d[f"t_fill_{rule}"]
    d["y"] = ((tf >= 0) & (tf <= d["t0"] + hm)).astype(int)
    d["move"] = np.where(d["y"] == 1, d[f"move_{rule}"], np.nan)
    return d
