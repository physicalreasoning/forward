"""WM-2 prototype: the MRMS reader, the tile store, the input shim, the baselines and the scores."""

import io
import struct

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from forward.wm2 import access, baselines, evaluate, mrms, scores, store

T0 = pd.Timestamp("2026-10-14 12:00")


def grib(values_x: np.ndarray, t=T0, ref=-30.0, d=1, template5=41) -> bytes:
    """A minimal MRMS-like GRIB2 message: regular lat/lon grid, PNG-packed uint16 values."""
    nj, ni = values_x.shape
    b = io.BytesIO()
    Image.fromarray(values_x.astype(np.uint16)).save(b, format="PNG")
    png = b.getvalue()
    when = (t.year, t.month, t.day, t.hour, t.minute, 0)
    s1 = struct.pack(">IBHHBBBHBBBBBBB", 21, 1, 161, 0, 2, 1, 3, *when, 0, 1)
    tmpl = struct.pack(">BBIBIBI", 6, 0, 0, 0, 0, 0, 0)
    tmpl += struct.pack(">IIII", ni, nj, 0, 0xFFFFFFFF)
    tmpl += struct.pack(">IIBIIIIB", 54995000, 230005000, 48, 20005000, 300005000, 10000, 10000, 0)
    s3 = struct.pack(">IBBIBBH", 72, 3, 0, ni * nj, 0, 0, 0) + tmpl
    s4 = struct.pack(">IB", 34, 4) + bytes(29)
    s5 = struct.pack(">IBIHfHHBB", 21, 5, ni * nj, template5, ref, 0, d, 16, 0)
    s6 = struct.pack(">IBB", 6, 6, 255)
    s7 = struct.pack(">IB", 5 + len(png), 7) + png
    body = s1 + s3 + s4 + s5 + s6 + s7 + b"7777"
    return b"GRIB" + bytes([0, 0, 209, 2]) + struct.pack(">Q", 16 + len(body)) + body


def test_decode_png_packed_grid_and_flags():
    x = np.array([[0, 30, 31], [50, 20, 1030]], dtype=np.uint16)  # -3.0, 0.0, 0.1, 2.0, -1.0, 100.0
    f = mrms.decode(grib(x))
    assert f.ref_time == T0
    assert (f.lat0, f.lon0, f.step) == (54.995, -129.995, 0.01)
    want = np.array([[np.nan, 0.0, 0.1], [2.0, np.nan, 100.0]], dtype=np.float32)
    np.testing.assert_allclose(f.values, want, atol=1e-5)


def test_decode_refuses_other_packing():
    with pytest.raises(mrms.NotMRMS, match="PNG"):
        mrms.decode(grib(np.zeros((2, 2)), template5=0))


def test_tiles_stay_inside_the_grid_and_know_the_station_pixel():
    class S:
        lat, lon = 47.44, -122.31  # near the west edge (SEA)

    t = mrms.tiles({"SEA": S})[0]
    assert t.col0 >= 0 and t.row0 >= 0
    lat, lon = t.latlon(*t.station_rc)
    assert abs(lat - S.lat) < 0.02 and abs(lon - S.lon) < 0.02


def test_pack_round_trip():
    x = np.array([0.0, 0.1, 2.34, np.nan, 150.0], dtype=np.float32)
    y = mrms.unpack(mrms.pack(x))
    assert np.isnan(y[3])
    np.testing.assert_allclose(y[[0, 1, 2, 4]], [0.0, 0.1, 2.3, 150.0], atol=1e-5)


class FakeStore:
    """Frames keyed by time; a blob moving one pixel east per 10 minutes."""

    def __init__(self, missing=()):
        self.tiles = [mrms.Tile("A", 0, 0, (128, 128))]
        self.keys = ["A"]
        self.missing = {pd.Timestamp(t) for t in missing}

    def frame(self, t):
        x = np.zeros((mrms.CONTEXT, mrms.CONTEXT), np.float32)
        step = int((pd.Timestamp(t) - T0) / pd.Timedelta(minutes=10))
        c = 100 + step
        if 0 <= c < mrms.CONTEXT - 20:
            x[110:140, c : c + 20] = 5.0
        return x

    def load(self, times):
        out = np.stack([self.frame(t)[None] for t in times]).astype(np.float32)
        for i, t in enumerate(times):
            if pd.Timestamp(t) in self.missing:
                out[i] = np.nan
        return out


def test_shim_refuses_frames_at_or_after_the_init():
    inp = access.Inputs(T0, FakeStore())
    assert inp.radar([T0 - pd.Timedelta(minutes=10)]).shape == (1, 1, mrms.CONTEXT, mrms.CONTEXT)
    with pytest.raises(access.LeakageError):
        inp.radar([T0])
    with pytest.raises(access.LeakageError, match="declare"):
        access.Inputs(T0, FakeStore(), declared=()).radar([T0 - pd.Timedelta(hours=1)])


def test_cross_correlation_recovers_a_shift():
    rng = np.random.default_rng(1)
    a = ndimage_blobs(rng)
    b = np.roll(a, (3, -5), axis=(0, 1))
    np.testing.assert_allclose(baselines.xcorr_shift(a, b), [3, -5], atol=0.3)


def ndimage_blobs(rng):
    from scipy import ndimage

    return ndimage.gaussian_filter(rng.random((128, 128)), 4)


def test_baselines_shapes_and_advection_moves_rain():
    inp = access.Inputs(T0, FakeStore())
    want = (baselines.K, 1, len(baselines.LEADS), mrms.TARGET, mrms.TARGET)
    p = baselines.persistence(T0, ["A"], inp)
    a = baselines.advection(T0, ["A"], inp)
    assert p.shape == a.shape == want
    v = baselines.motion(FakeStore().load([T0 - pd.Timedelta(minutes=m) for m in (30, 20, 10)]))
    np.testing.assert_allclose(v[0], [0, 1], atol=0.2)
    # the control member at lead 60 min matches the truth there better than persistence does
    y = baselines._target(FakeStore().frame(T0 + pd.Timedelta(minutes=60)))
    li = baselines.LEADS.index(60)
    assert np.abs(a[0, 0, li] - y).mean() < np.abs(p[0, 0, li] - y).mean()


def test_climatology_skips_analogues_with_missing_frames():
    lead0 = baselines.lead_times(T0.replace(year=T0.year - 1))[0]
    inp = access.Inputs(T0, FakeStore(missing=[lead0]))
    c = baselines.climatology(T0, ["A"], inp)
    assert np.isfinite(c).all()
    assert all(r["first"] != str(lead0) for r in inp.log[-baselines.K :])


def test_baselines_never_read_the_future():
    """Truth after the init replaced by nonsense must not change any forecast."""

    class Poisoned(FakeStore):
        def load(self, times):
            x = super().load(times)
            for i, t in enumerate(times):
                if pd.Timestamp(t) >= T0:
                    x[i] = 999.0
            return x

    for f in baselines.ENTRIES.values():
        a = f(T0, ["A"], access.Inputs(T0, FakeStore()))
        b = f(T0, ["A"], access.Inputs(T0, Poisoned()))
        np.testing.assert_array_equal(a, b)


def test_scores_reduce_and_reward_the_truth():
    rng = np.random.default_rng(0)
    y = rng.gamma(0.5, 2.0, (2, 32, 32))
    ok = np.ones_like(y, bool)
    perfect = np.repeat(y[None], 5, axis=0)
    noisy = perfect + rng.normal(0, 1, perfect.shape)
    assert np.nanmean(scores.pooled_crps(perfect, y, ok, 4)) == pytest.approx(0.0, abs=1e-12)
    assert np.nanmean(scores.pooled_crps(noisy, y, ok, 1)) > 0
    assert scores.fss([scores.fss_terms(perfect, y, ok, 1.0, 5)]) == pytest.approx(1.0)
    assert scores.fss([scores.fss_terms(noisy, y, ok, 1.0, 5)]) < 1.0
    es = scores.pooled_energy(noisy, y, ok, 8)
    assert es.shape == (2,) and (es > 0).all()
    ok[0, 0, 0] = False
    assert np.isnan(scores.pooled_energy(noisy, y, ok, 8)[0])


def test_evaluate_uses_the_same_cells_for_every_entry():
    rng = np.random.default_rng(0)
    y = rng.gamma(0.5, 2.0, (2, 1, 3, 16, 16))  # [init, tile, lead, H, W]
    y[0, 0, 1, :2] = np.nan
    a = rng.gamma(0.5, 2.0, (2, 4, 1, 3, 16, 16))  # [init, K, tile, lead, H, W]
    b = a.copy()
    b[1, :, 0, 2, 5, 5] = np.nan
    stats = [evaluate.init_stats({"a": a[i], "b": b[i]}, y[i], points=[(8, 8)]) for i in range(2)]
    res = evaluate.combine(stats, ["d1", "d2"], [10, 20, 30])
    assert res["cells"] == y.size - 32 - 1
    ea = res["entries"]["a"]
    assert ea["energy_rows"] == [2, 1, 1]  # a row with any unscored cell is dropped for everyone
    assert ea["station_rows"] == [2, 2, 2]
    assert res["entries"]["b"]["crps_1"][2] == pytest.approx(ea["crps_1"][2])  # same cells
    perfect = {"p": np.repeat(y[0][None], 3, axis=0)}
    one = evaluate.combine([evaluate.init_stats(perfect, y[0])], ["d1"], [10, 20, 30])
    assert one["entries"]["p"]["fss_1_5"][0] == pytest.approx(1.0)


def test_store_capture_writes_hash_checked_days(tmp_path, monkeypatch):
    times = [T0, T0 + pd.Timedelta(minutes=10), T0 + pd.Timedelta(minutes=20)]

    def fake_fetch(t, product=mrms.PRODUCT, timeout=60):
        if pd.Timestamp(t) == times[1]:
            import urllib.error

            raise urllib.error.HTTPError("u", 404, "absent", None, None)
        return b"x"

    def fake_decode(raw):
        v = np.zeros((mrms.NJ, mrms.NI), np.float32)
        v[1000:1010, 1000:1010] = 2.5
        return mrms.Field(v, fake_decode.t, mrms.LAT0, mrms.LON0, mrms.STEP)

    seen = iter([times[0], times[2]])

    def decode(raw):
        fake_decode.t = next(seen)
        return fake_decode(raw)

    monkeypatch.setattr(mrms, "fetch", fake_fetch)
    monkeypatch.setattr(mrms, "decode", decode)
    monkeypatch.setattr(mrms, "list_day", lambda day, product=mrms.PRODUCT: {})
    tl = [mrms.Tile("A", 495, 495, (5, 5))]
    st = store.Store(tmp_path, tl)
    s = st.capture(times, workers=1)
    assert s["fetched"] == 2 and s["missing"] == [str(times[1])]
    st2 = store.Store(tmp_path, tl)
    x = st2.load(times)
    assert np.isnan(x[1]).all() and x[0].max() == pytest.approx(2.5)
    npz = tmp_path / f"{T0.date()}.npz"
    npz.write_bytes(npz.read_bytes() + b"\0")
    with pytest.raises(store.HashMismatch):
        store.Store(tmp_path, tl).load(times)
