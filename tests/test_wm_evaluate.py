import numpy as np

from forward.wm import evaluate, scores


def _setup(n_init=3, k=8, st=2, lead=48, seed=0):
    rng = np.random.default_rng(seed)
    y = rng.normal(size=(n_init, st, lead))
    fc = {
        "climatology": rng.normal(size=(n_init, k, st, lead)),
        "model": y[:, None] + 0.3 * rng.normal(size=(n_init, k, st, lead)),
    }
    return fc, y


def test_window_rows_coverage_threshold():
    mask = np.ones((1, 3, 40), dtype=bool)
    mask[0, 1, :2] = False  # 22 of 24 hours, 91.7%: dropped from the 24 h window
    mask[0, 2, 5] = False  # 39 of 40 hours, 97.5%: kept in a 40 h window
    rows24 = evaluate.window_rows(mask, 24)
    assert rows24.tolist() == [[True, False, True]]
    assert evaluate.window_rows(mask, 40).tolist() == [[True, True, True]]  # 38 of 40 is 95%
    assert not evaluate.window_rows(mask, 48).any()  # leads shorter than the window


def test_missing_hour_scores_on_observed_hours_only():
    fc, y = _setup()
    y[0, 0, 70 % 48] = np.nan  # one missing hour of 48 (97.9%)
    out = evaluate.score(fc, y, ["d0", "d1", "d2"])
    w = out["windows"]["48"]
    assert w["rows"] == 6 and w["rows_complete"] == 5
    h = np.isfinite(y[0, 0])
    x = fc["model"][0, :, 0][:, h]
    expect = scores.energy(x[:, None], y[0, 0][h][None])[0]
    es, _ = evaluate._window_scores(np.moveaxis(fc["model"][[0], :, 0, :], 1, 0), y[[0], 0], h[None])
    assert np.isclose(es[0], expect)


def test_complete_rows_match_batched_scores():
    fc, y = _setup(seed=1)
    out = evaluate.score(fc, y, ["d0", "d1", "d2"])
    xx = np.moveaxis(fc["model"], 1, 0).reshape(8, -1, 48)[:, :, :24]
    es = scores.energy(xx, y.reshape(-1, 48)[:, :24])
    assert np.isclose(out["windows"]["24"]["entries"]["model"]["energy"], es.mean())


def test_missing_forecast_hour_still_drops_the_row():
    fc, y = _setup(seed=2)
    fc["model"][1, :, 0, 10] = np.nan  # an entry may not choose which hours are scored
    out = evaluate.score(fc, y, ["d0", "d1", "d2"])
    assert out["windows"]["24"]["rows"] == 5
