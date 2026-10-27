import numpy as np
import pandas as pd
import pytest
from wm_fixtures import INIT, STATIONS, FakeStore, truth

from forward.wm import baselines as b
from forward.wm import scores
from forward.wm.access import Inputs


@pytest.fixture(scope="module")
def tr():
    return truth()


@pytest.fixture(scope="module")
def store(tr):
    return FakeStore(tr, pd.date_range("2026-10-18", "2026-10-25"))


def test_analogues_are_fifty_real_weeks(tr):
    starts = b.analog_starts(INIT)
    assert len(starts) == 70 and starts[0] == pd.Timestamp("2025-10-25T20:00Z")
    x = b.climatology(INIT, STATIONS, Inputs(INIT, ["truth"], truth=tr))
    assert x.shape == (50, 2, 168, 1) and np.isfinite(x).all()
    # Sample 0 is exactly the week after the same time last year.
    want = tr["NY"].reindex(b.lead_times(starts[0])).to_numpy()
    np.testing.assert_allclose(x[0, 0, :, 0], want)


def test_analogue_with_a_long_gap_is_replaced(tr):
    t = tr["NY"].copy()
    gap = b.lead_times(pd.Timestamp("2025-10-25T20:00Z"))[10:15]
    t[gap] = np.nan
    w = b._analogues(t, INIT)
    assert w[0][0] != pd.Timestamp("2025-10-25T20:00Z") and len(w) == 50


def test_persistence_starts_from_the_last_observation(tr):
    x = b.persistence(INIT, STATIONS, Inputs(INIT, ["truth"], truth=tr))
    assert np.isfinite(x).all()
    last = tr["NY"][INIT - pd.Timedelta(hours=1)]
    # One hour ahead the sample spread is small and centred near the last value.
    assert abs(np.median(x[:, 0, 0, 0]) - last) < 3
    assert x[:, 0, 0, 0].std() < x[:, 0, -1, 0].std()


def test_allocation_is_equal_weight():
    assert b.allocation(["a", "b", "c", "d", "e", "f"]) == {"a": 9, "b": 9, "c": 8, "d": 8, "e": 8, "f": 8}


def test_short_models_are_dropped_and_draw_is_coherent():
    rng = np.random.default_rng(0)
    full = rng.normal(size=(10, 2, 168))
    short = full.copy()
    short[:, :, 160:] = np.nan
    x = b.draw({"full": full, "short": short}, INIT)
    assert x.shape == (50, 2, 168) and np.isfinite(x).all()
    # Every sample is one member's whole trajectory at both stations.
    for s in x[:5]:
        assert any(np.array_equal(s, m) for m in full)


def test_raw_reads_the_init_day_capture(tr, store):
    x = b.raw(INIT, STATIONS, Inputs(INIT, ["ensembles"], captures=store))
    assert x.shape == (50, 2, 168, 1)
    # The fake capture covers 8 days from 00:00 UTC, so all 168 leads after 20:00.
    assert np.isfinite(x).all()


def test_ecc_keeps_template_ranks_and_target_margins():
    rng = np.random.default_rng(1)
    tmpl = rng.normal(size=(50, 3, 4))
    out = b.ecc(tmpl, np.full((3, 4), 10.0), np.full((3, 4), 2.0), rng)
    assert (np.argsort(out, axis=0) == np.argsort(tmpl, axis=0)).all()
    q = 10 + 2 * b.norm.ppf(np.arange(1, 51) / 51)
    np.testing.assert_allclose(np.sort(out[:, 1, 2]), q)


def test_emos_recovers_a_known_bias_and_spread():
    rng = np.random.default_rng(2)
    n = 3000
    st = rng.integers(0, 2, n)
    m = rng.normal(50, 10, n)
    v = np.full(n, 1.0)
    y = m + np.where(st == 0, -3.0, 2.0) + rng.normal(0, 2.0, n)
    p = b.fit_emos(st, m, v, y, 2)
    assert abs(p["a"][0] - -3) < 0.6 and abs(p["a"][1] - 2) < 0.6 and abs(p["b"] - 1) < 0.02
    assert abs(np.sqrt(p["c"] ** 2 + p["d"] ** 2) - 2) < 0.15


def test_emos_blocks_fall_back_to_the_longest_fitted():
    pairs = pd.DataFrame({"st": 0, "lead": np.tile(np.arange(1, 25), 30), "m": 50.0, "v": 1.0, "y": 52.0})
    fits = b.fit_blocks(pairs, 1)
    assert fits[0]["fit"] == 0 and all(f["fit"] == 0 for f in fits[1:])
    assert b.fit_blocks(pairs.iloc[:0], 1)[3]["fit"] is None


def test_emos_ecc_beats_raw_on_a_biased_ensemble(tr, store):
    # The fake members run 1.5 F warm; calibration on past captures should remove most of it.
    inp = Inputs(INIT, ["ensembles", "truth"], truth=tr, captures=store)
    cal = b.emos_ecc(INIT, STATIONS, inp)[..., 0]
    raw = b.raw(INIT, STATIONS, inp)[..., 0]
    y = np.stack([tr[s].reindex(b.lead_times(INIT)).to_numpy() for s in STATIONS])
    day1 = slice(0, 24)
    assert scores.crps(cal[:, :, day1], y[:, day1]).mean() < scores.crps(raw[:, :, day1], y[:, day1]).mean()
