import json
import subprocess
import textwrap

import numpy as np
import pandas as pd
import pytest
from wm_fixtures import INIT, STATIONS, FakeStore, truth

from forward import ROOT
from forward.wm import access, entry, runner
from forward.wm.access import LeakageError
from forward.wm.entry import EntryRefused, write_manifest

BASELINES = ["climatology", "persistence", "raw", "emos-ecc"]


def make_entry(root, body, inputs=("truth",), name="toy", leads=168, extra=None):
    d = root / "entries" / name
    d.mkdir(parents=True)
    (d / "entry.py").write_text(textwrap.dedent(body))
    code = [f"entries/{name}/entry.py"]
    weights = None
    if extra:
        (root / "w.bin").write_bytes(extra)
        weights = ["w.bin"]
    write_manifest(
        d,
        root,
        id=f"wm1-{name}",
        family="wm1",
        inputs=list(inputs),
        code=code,
        weights=weights,
        K=3,
        leads=leads,
        variables=["tmpf"],
    )
    return entry.load(d, root)


OK = """
import numpy as np

def predict(init_time, stations, inputs):
    last = [inputs.truth(s).iloc[-1] for s in stations]
    return np.broadcast_to(np.array(last)[None, :, None, None], (3, len(stations), 168, 1)).copy()
"""


@pytest.fixture(scope="module")
def tr():
    return truth()


def test_runs_and_writes_a_hashed_forecast(tmp_path, tr):
    e = make_entry(tmp_path, OK)
    x, rec = runner.run(e, INIT, STATIONS, truth=tr, out=tmp_path / "out")
    assert x.shape == (3, 2, 168, 1)
    f = tmp_path / "out" / "wm1-toy" / "2026-10-25T20Z.json"
    y, rec2 = runner.load_forecast(f)
    assert np.array_equal(x, y) and rec2 == json.loads(f.read_text())
    assert rec["manifest_sha256"] == e.manifest_sha256 and rec["read"][0]["truth"] == "NY"
    f.with_suffix(".npy").write_bytes(runner.npy_bytes(x + 1))
    with pytest.raises(runner.BadForecast):
        runner.load_forecast(f)


def test_changed_code_is_refused(tmp_path, tr):
    e = make_entry(tmp_path, OK)
    (e.dir / "entry.py").write_text(OK + "\n# tuned after the freeze\n")
    with pytest.raises(EntryRefused, match="changed"):
        runner.run(e, INIT, STATIONS, truth=tr)


def test_changed_weights_are_refused(tmp_path, tr):
    e = make_entry(tmp_path, OK, extra=b"weights")
    assert e.weights_sha256 is not None
    (tmp_path / "w.bin").write_bytes(b"other weights")
    with pytest.raises(EntryRefused, match="w.bin"):
        runner.run(e, INIT, STATIONS, truth=tr)


def test_wrong_shape_is_refused(tmp_path, tr):
    e = make_entry(tmp_path, OK, leads=24)
    with pytest.raises(runner.BadForecast, match="shape"):
        runner.run(e, INIT, STATIONS, truth=tr)


# Leakage -----------------------------------------------------------------------------------

FUTURE_TRUTH = """
def predict(init_time, stations, inputs):
    import pandas as pd
    return inputs.truth(stations[0], end=init_time + pd.Timedelta(hours=24))
"""
NETWORK = """
def predict(init_time, stations, inputs):
    import urllib.request
    urllib.request.urlopen("https://mesonet.agron.iastate.edu/")
"""
SUBPROCESS = """
def predict(init_time, stations, inputs):
    import subprocess
    subprocess.run(["true"])
"""


@pytest.mark.parametrize(
    "body", [FUTURE_TRUTH, NETWORK, SUBPROCESS], ids=["future-truth", "network", "subprocess"]
)
def test_reading_around_the_shim_is_refused(tmp_path, tr, body):
    e = make_entry(tmp_path, body)
    with pytest.raises(LeakageError):
        runner.run(e, INIT, STATIONS, truth=tr)


def test_opening_a_data_file_is_refused(tmp_path, tr):
    data = tmp_path / "data"
    data.mkdir()
    (data / "truth.csv").write_text("hour,tmpf\n")
    access.protect(data)
    e = make_entry(
        tmp_path,
        f"""
def predict(init_time, stations, inputs):
    open({str(data / "truth.csv")!r}).read()
""",
    )
    with pytest.raises(LeakageError, match="open"):
        runner.run(e, INIT, STATIONS, truth=tr)


def test_tomorrows_capture_is_refused(tmp_path, tr):
    e = make_entry(
        tmp_path,
        """
def predict(init_time, stations, inputs):
    return inputs.ensembles("2026-10-26")
""",
        inputs=("ensembles",),
    )
    st = FakeStore(tr, ["2026-10-25", "2026-10-26"])
    with pytest.raises(LeakageError):
        runner.run(e, INIT, STATIONS, captures=st)


@pytest.mark.parametrize("name", BASELINES)
def test_baselines_do_not_see_the_future(tr, name):
    """Replace every truth value at or after the init, and every later capture, with nonsense:
    a baseline that read any of it would change its forecast."""
    days = pd.date_range("2026-10-20", "2026-10-28")
    future = {s: v.where(v.index < INIT, v + 100.0) for s, v in tr.items()}
    a = FakeStore(tr, days)
    b = FakeStore(tr, days)
    for d in days[days > INIT.tz_localize(None).normalize()]:
        b.frames[d] = b.frames[d].assign(temperature_2m=-40.0)
    e = entry.load(ROOT / "entries" / "wm1" / name)
    x, _ = runner.run(e, INIT, STATIONS, truth=tr, captures=a)
    y, _ = runner.run(e, INIT, STATIONS, truth=future, captures=b)
    assert np.isfinite(x).mean() > 0.8
    np.testing.assert_array_equal(x, y)


# Sealing -----------------------------------------------------------------------------------


def _git(root, *args, date=None):
    env = None
    if date:
        import os

        env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


def test_sealed_before_the_window(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    e = make_entry(tmp_path, OK)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "entry", date="2026-10-20T12:00:00Z")
    assert e.sealed_before("2026-10-25T20:00Z") == pd.Timestamp("2026-10-20T12:00Z")
    with pytest.raises(EntryRefused, match="not before"):
        e.sealed_before("2026-10-19T20:00Z")
    (e.dir / "entry.py").write_text(OK + "\n")
    with pytest.raises(EntryRefused, match="uncommitted"):
        e.sealed_before("2026-10-25T20:00Z")


def test_committed_manifests_match_the_baselines():
    for name in BASELINES:
        entry.load(ROOT / "entries" / "wm1" / name).verify()


def test_the_invariance_check_catches_a_leak(tmp_path, tr):
    """An entry that reaches past the shim's cut (here through a private attribute) is caught by
    the same comparison the baselines pass."""
    e = make_entry(
        tmp_path,
        """
import numpy as np
import pandas as pd

def predict(init_time, stations, inputs):
    nxt = [inputs._truth[s][init_time + pd.Timedelta(hours=1)] for s in stations]
    return np.broadcast_to(np.array(nxt)[None, :, None, None], (3, len(stations), 168, 1)).copy()
""",
    )
    future = {s: v.where(v.index < INIT, v + 100.0) for s, v in tr.items()}
    x, _ = runner.run(e, INIT, STATIONS, truth=tr)
    y, _ = runner.run(e, INIT, STATIONS, truth=future)
    assert not np.array_equal(x, y)
