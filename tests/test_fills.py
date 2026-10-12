import gzip
import json
import math

import numpy as np
import pandas as pd
import pytest

from forward import fills
from forward.fills import ADD, CANCEL, DELTA, EXEC, LEVEL, NO, SNAP, THROUGH, TRADE, YES

MIN = 60_000


def test_executions_fill_the_queue_ahead_first_then_us():
    ts, vs, _ = fills.simulate([(1, EXEC, 3), (2, EXEC, 4)], ahead=5, level=5)
    assert list(ts) == [2] and list(vs) == [2]
    assert fills.fill_time(ts, vs, 2) == 2
    assert fills.fill_time(ts, vs, 3) == -1


def test_orders_added_behind_us_do_not_delay_us():
    ts, vs, _ = fills.simulate([(1, ADD, 100), (2, EXEC, 6)], ahead=5, level=5)
    assert list(vs) == [1]


def test_cancellations_pro_rata_versus_back_of_queue():
    # 10 ahead of us, 10 join behind, 10 cancel, then 10 execute.
    ev = [(1, ADD, 10), (2, CANCEL, 10), (3, EXEC, 10)]
    _, pro, _ = fills.simulate(ev, ahead=10, level=10, rule="pro_rata")
    _, back, _ = fills.simulate(ev, ahead=10, level=10, rule="back")
    assert pro[-1] == pytest.approx(5)  # half the cancellations were ahead of us
    assert len(back) == 0  # all from behind: still 10 ahead, all executed before us


def test_with_nobody_behind_us_both_rules_agree():
    ev = [(1, CANCEL, 4), (2, EXEC, 8)]
    for rule in fills.RULES:
        _, vs, _ = fills.simulate(ev, ahead=10, level=10, rule=rule)
        assert vs[-1] == pytest.approx(2)


def test_a_trade_through_our_price_reaches_us_whatever_the_queue():
    ts, vs, _ = fills.simulate([(5, THROUGH, 7)], ahead=50, level=50)
    assert list(ts) == [5] and list(vs) == [7]


def test_unknown_rule_is_refused():
    with pytest.raises(ValueError):
        fills.simulate([], 0, 0, rule="front")


def _book():
    """One market, hand built. YES bids 40c x5, 39c x3; NO bid 55c x10 (a YES offer at 45c).

    t0 = 40 min. Then: 41 min the 5 at 40c trade; 42 min 4 more join at 40c; 43 min 3 of those
    trade; 46 min a NO bid at 57c (YES offer 43c); 49 min the last 1 at 40c cancels; 50 min a NO
    bid of 20 at 60c rests (a YES offer at 40c, which would cross a YES bid at 40c or above);
    55 min one contract trades at 39c.
    """
    p = fills.PU
    rows = [
        (1 * MIN, SNAP, -1, 0, 0.0),
        (1 * MIN, LEVEL, YES, 40 * p, 5.0),
        (1 * MIN, LEVEL, YES, 39 * p, 3.0),
        (1 * MIN, LEVEL, NO, 55 * p, 10.0),
        (41 * MIN, DELTA, YES, 40 * p, -5.0),
        (41 * MIN, TRADE, YES, 40 * p, 5.0),
        (42 * MIN, DELTA, YES, 40 * p, 4.0),
        (43 * MIN, TRADE, YES, 40 * p, 3.0),  # a trade may arrive before its delta
        (43 * MIN, DELTA, YES, 40 * p, -3.0),
        (46 * MIN, DELTA, NO, 57 * p, 10.0),
        (49 * MIN, DELTA, YES, 40 * p, -1.0),
        (50 * MIN, DELTA, NO, 60 * p, 20.0),
        (55 * MIN, DELTA, YES, 39 * p, -1.0),
        (55 * MIN, TRADE, YES, 39 * p, 1.0),
        (240 * MIN, DELTA, YES, 20 * p, 1.0),  # keeps the record going past every horizon
    ]
    ev = pd.DataFrame(rows, columns=["recv", "kind", "side", "px", "qty"])
    ev = ev.assign(ts=ev["recv"], tk="KXHIGHTEST-26OCT12-B40.5")
    ev["tk"] = ev["tk"].astype("category")
    return fills.mark_exec(ev)


def _samples_at(t0, gaps=None):
    ev = _book()
    t = ev["recv"].to_numpy()
    gaps = fills.merge([(-(2**62), int(t[0])), (int(t[-1]), 2**62), *(gaps or [])])
    df = pd.DataFrame(fills.market_samples("KXHIGHTEST-26OCT12-B40.5", ev.drop(columns=["tk"]), gaps))
    return df[df["t0"] == t0].set_index(["side", "level", "size"]).sort_index()


def _samples(gaps=None):
    ev = _book()
    t = ev["recv"].to_numpy()
    gaps = fills.merge([(-(2**62), int(t[0])), (int(t[-1]), 2**62), *(gaps or [])])
    g = ev.drop(columns=["tk"])
    df = pd.DataFrame(fills.market_samples("KXHIGHTEST-26OCT12-B40.5", g, gaps))
    return df[df["t0"] == 40 * MIN].set_index(["side", "level", "size"]).sort_index()


def test_trades_are_matched_to_their_deltas():
    ev = _book()
    ex = ev[ev["exec"]]
    assert list(ex["recv"]) == [41 * MIN, 43 * MIN, 55 * MIN]
    assert not ev.loc[ev["recv"] == 49 * MIN, "exec"].any()  # no trade: a cancellation


def test_hand_built_book_joining_the_best_bid():
    df = _samples()
    r = df.loc[(YES, 0)]
    assert r.loc[1, "queue"] == 5 and r.loc[1, "better"] == 0
    assert r.loc[1, "mid"] == 42.5 and r.loc[1, "spread"] == 5
    assert r.loc[1, "t_fill_pro_rata"] == 43 * MIN  # 5 ahead traded at 41, then 3 of 4 behind at 43
    assert r.loc[10, "t_fill_pro_rata"] == 50 * MIN  # 3 + the crossing 20 at 50
    assert r.loc[100, "t_fill_pro_rata"] == -1
    assert list(r["how_pro_rata"]) == ["at_price", "cross", ""]
    # Mid 42.5 at the fill (best bid 40c, offer 45c), 41.5 five minutes later (offer 43c).
    assert r.loc[1, "move_pro_rata"] == pytest.approx(-1.0)


def test_hand_built_book_improving_and_behind_the_best():
    df = _samples()
    up = df.loc[(YES, 1)]  # 41c: alone; the trade at 40c would have hit us first
    assert up.loc[1, "queue"] == 0 and up.loc[1, "t_fill_pro_rata"] == 41 * MIN
    assert up.loc[1, "how_pro_rata"] == "through"
    assert up.loc[10, "t_fill_pro_rata"] == 50 * MIN  # 5 + 3 through, then 20 crossing 59c+
    down = df.loc[(YES, -1)]  # 39c: 5 better and 3 ahead; nothing ever trades at or through 39c
    assert down.loc[1, "queue"] == 3 and down.loc[1, "better"] == 5
    assert down.loc[1, "t_fill_pro_rata"] == -1
    assert (YES, -3) in df.index  # 37c is a valid price with an empty queue


def test_no_side_orders_and_marketable_prices():
    df = _samples()
    # NO best bid 55c; NO +1 = 56c is still below the YES bid's mirror (60c), so it is passive.
    assert (NO, 1) in df.index and (NO, 0) in df.index
    assert df.loc[(NO, 0, 1), "price"] == 55


def test_lookback_features_see_only_the_past():
    df = _samples()
    r = df.loc[(YES, 0, 1)]
    assert r["n_exec"] == 0 and r["n_exec_at"] == 0 and not r["crossed"]
    later = _samples_at(60 * MIN)  # best YES bid 39c; trades at 40c (41, 43 min) and 39c (55 min)
    r = later.loc[(YES, 0, 1)]
    assert r["price"] == 39 and r["n_exec"] == 3 and r["v_exec"] == 9
    assert r["n_exec_at"] == 1 and r["v_exec_at"] == 1 and r["crossed"]
    assert not later.loc[(YES, -1, 1), "crossed"]  # nothing traded at or below 38c


def test_a_gap_cuts_the_labels_that_reach_it():
    df = _samples(gaps=[(45 * MIN, 46 * MIN)])
    r = df.loc[(YES, 0, 1)]
    assert r["valid_until"] == 45 * MIN
    rows = df.reset_index()
    assert len(fills.labels(rows, "5m")) == len(rows)  # 40 + 5 = 45 min: still clean
    assert len(fills.labels(rows, "30m")) == 0
    # The fill at 43 min is inside the clean stretch; its 5-minute move is not.
    assert math.isnan(r["move_pro_rata"])


def test_no_decision_time_inside_or_just_after_a_gap():
    ev = _book()
    t = ev["recv"].to_numpy()
    gaps = fills.merge([(-(2**62), int(t[0])), (int(t[-1]), 2**62), (25 * MIN, 26 * MIN)])
    df = pd.DataFrame(fills.market_samples("X", ev.drop(columns=["tk"]), gaps))
    assert df.empty or (df["t0"] - fills.LOOKBACK_MS > 26 * MIN).all()


def test_labels_use_the_horizon():
    df = _samples().reset_index()
    y5 = fills.labels(df, "5m").set_index(["side", "level", "size"])["y"]
    y30 = fills.labels(df, "30m").set_index(["side", "level", "size"])["y"]
    assert y5[(YES, 0, 1)] == 1 and y5[(YES, 0, 10)] == 0  # 43 min within 5; 50 min is not
    assert y30[(YES, 0, 10)] == 1


def test_gaps_from_the_log_silences_and_restarts(tmp_path):
    log = tmp_path / "gaps.jsonl"
    log.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"ts": "2026-10-11T10:00:00+00:00", "kind": "disconnect"},
                {"ts": "2026-10-11T10:00:30+00:00", "kind": "reconnected"},
            ]
        )
    )
    base = int(pd.Timestamp("2026-10-11 09:00", tz="UTC").value // 1_000_000)
    s = np.arange(0, 240) * 30_000  # a message every 30 s for two hours...
    s = s[(s < 100 * MIN) | (s > 110 * MIN)]  # ...except a ten-minute silence
    kind = np.full(len(s), DELTA)
    kind[0] = kind[np.searchsorted(s, 90 * MIN)] = fills.SUB  # a restart at 90 min
    ev = pd.DataFrame({"recv": base + s, "kind": kind})
    g = fills.gap_intervals(ev, log, end_ms=base + 200 * MIN)
    assert fills.clean(g, base + MIN, base + 2 * MIN)
    assert not fills.clean(g, base + 59 * MIN + 30_000, base + 59 * MIN + 30_000)  # padded disconnect
    assert fills.clean(g, base + 61 * MIN, base + 89 * MIN)
    assert not fills.clean(g, base + 89 * MIN + 45_000, base + 89 * MIN + 45_000)  # the restart
    assert not fills.clean(g, base + 105 * MIN, base + 105 * MIN)  # the silence
    assert not fills.clean(g, base + 120 * MIN, base + 120 * MIN)  # after the last message
    assert fills.next_gap(g, base + 2 * MIN) == base + 59 * MIN


def test_parse_file_reads_a_cut_stream_and_maps_trades_to_the_resting_side(tmp_path):
    f = tmp_path / "10.jsonl.gz"
    msgs = [
        {"type": "subscribed", "msg": {"sid": 1}},
        {
            "type": "orderbook_snapshot",
            "msg": {"market_ticker": "M", "yes_dollars_fp": [["0.4000", "5.00"]], "no_dollars_fp": []},
        },
        {
            "type": "trade",
            "msg": {
                "market_ticker": "M",
                "taker_side": "yes",
                "yes_price_dollars": "0.4500",
                "no_price_dollars": "0.5500",
                "count_fp": "2.00",
                "ts_ms": 7,
            },
        },
    ]
    lines = "".join(json.dumps({"recv_ms": i, "m": m}) + "\n" for i, m in enumerate(msgs))
    cut = gzip.compress(b'{"recv_ms": 9, "m": {"ty')[:-12]  # a stream cut off by a crash
    f.write_bytes(cut + gzip.compress(lines.encode()))
    df = fills.parse_file(f)
    assert list(df["kind"]) == [fills.SUB, SNAP, LEVEL, TRADE]
    tr = df.iloc[-1]
    assert tr["side"] == NO and tr["px"] == 55 * fills.PU and tr["ts"] == 7  # hit a NO bid at 55c
