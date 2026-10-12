import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import score  # noqa: E402

DAYS = pd.to_datetime(["2026-11-02", "2026-11-03", "2026-11-04"])


def rows():
    """NY and SEA on three days; isotherm covers NY only, like the 7 of 19 stations it serves."""
    return pd.DataFrame(
        [{"station": st, "day": d} for d in DAYS for st in ("NY", "SEA")],
    )


def ladders():
    out = []
    for d in DAYS:
        for series in ("KXHIGHNY", "KXHIGHTSEA"):
            ev = f"{series}-{d:%y%b%d}".upper()
            for j, (lo, hi) in enumerate([(-np.inf, 60.5), (60.5, 62.5), (62.5, np.inf)]):
                out.append(
                    {
                        "series": series,
                        "event": ev,
                        "day": d,
                        "ticker": f"{ev}-{j}",
                        "lo": lo,
                        "hi": hi,
                        "bid": 0.30,
                        "ask": 0.35,
                        "yes": float(j == 1),
                    }
                )
    return pd.DataFrame(out)


def gaussian(n):
    return {
        "emos-all": (np.full(n, 61.5), np.full(n, 2.0)),
        "persistence": (np.full(n, 58.0), np.full(n, 3.0)),
    }


def iso(p=(0.1, 0.8, 0.1), days=DAYS):
    return {("NY", d): {f"KXHIGHNY-{d:%y%b%d}".upper() + f"-{j}": v for j, v in enumerate(p)} for d in days}


def test_without_ladder_entries_the_table_is_unchanged():
    d, lad = rows(), ladders()
    a = score.ladder_scores(d, gaussian(len(d)), lad)
    b = score.ladder_scores(d, gaussian(len(d)), lad, live={})
    assert a == b and a["ladders"] == 6 and "entries" not in a


def test_every_entry_is_scored_on_the_ladders_the_ladder_entry_covers():
    d, lad = rows(), ladders()
    full = score.ladder_scores(d, gaussian(len(d)), lad)
    com = score.ladder_scores(d, gaussian(len(d)), lad, live={"isotherm": iso()})
    assert com["ladders"] == 3  # NY only
    assert com["entries"] == {"emos-all": "gaussian", "persistence": "gaussian", "isotherm": "ladder"}
    assert {e: com[e]["log_vs_market_bid"]["n"] for e in com["entries"]} == dict.fromkeys(com["entries"], 3)
    # Same Gaussian entry, fewer ladders: the common table is its own comparison, not the full one.
    assert full["emos-all"]["log_vs_market_bid"]["n"] == 6
    # isotherm's log score is log(0.8) on every ladder; the bid market's is log(0.3 / 0.9).
    assert com["isotherm"]["log_vs_market_bid"]["diff"] == pytest.approx(np.log(0.8) - np.log(1 / 3))


def test_a_ladder_entry_missing_a_bucket_or_a_day_is_absent_there():
    d, lad = rows(), ladders()
    fc = iso(days=DAYS[:2])
    fc[("NY", DAYS[0])].popitem()  # one bucket short: not a forecast of this ladder
    com = score.ladder_scores(d, gaussian(len(d)), lad, live={"isotherm": fc})
    assert com["ladders"] == 1


def test_no_common_ladders_gives_an_empty_table_not_an_error():
    d, lad = rows(), ladders()
    assert score.ladder_scores(d, gaussian(len(d)), lad, live={"isotherm": {}}) == {"ladders": 0}


def test_h5_is_reported_only_when_isotherm_was_scored():
    d, lad = rows(), ladders()
    com = score.ladder_scores(d, gaussian(len(d)), lad, live={"isotherm": iso()})
    dates = d["day"].to_numpy()
    ls = {e: np.zeros(len(d)) for e in ("emos-aifs", "emos-ifs", "raw-aifs", "raw-ifs", "persistence")}
    t = score.tests(dates, ls, {}, com)
    assert t["H5_isotherm_minus_bid_market"]["verdict"] == "PASS"
    assert "H5_isotherm_minus_bid_market" not in score.tests(dates, ls, {}, {})
