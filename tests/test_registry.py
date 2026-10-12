import json

import numpy as np
import pytest
from test_entries import synthetic

from forward import ROOT, entries, registry
from forward.registry import Entry


def test_seeded_station_entries_are_registered_in_order():
    assert [e.name for e in registry.entries("station-highs", "gaussian")] == entries.ENTRIES


def test_isotherm_is_a_live_ladder_entry():
    (e,) = registry.entries("station-highs", "ladder")
    assert (e.name, e.source, e.module) == ("isotherm", "live", "forward.isotherm_live")
    m = e.load()
    assert all(callable(getattr(m, f)) for f in ("capture", "accept", "probs"))


def test_every_entry_module_and_task_script_exists_and_names_are_unique():
    for e in registry.ENTRIES.values():
        assert (ROOT / e.path).exists(), e.path
        assert e.task in registry.TASKS
    for t in registry.TASKS.values():
        assert (ROOT / t.score).exists(), t.score
    with pytest.raises(ValueError, match="twice"):
        registry.add(registry.ENTRIES["isotherm"])


def test_without_extra_entries_fit_and_predict_are_the_seeded_ones():
    df = synthetic(n_days=300)
    p = json.loads(json.dumps(registry.fit(df)))
    assert p == json.loads(json.dumps(entries.fit(df)))
    a, b = registry.predict(p, df.tail(5)), entries.predict(p, df.tail(5))
    assert list(a) == list(b)
    for e in a:
        np.testing.assert_array_equal(a[e][0], b[e][0])


def test_an_extra_fit_entry_is_fit_and_predicted_beside_the_seeded_ones(monkeypatch):
    e = Entry("const", "station-highs", "gaussian", "fit", "test_registry", "70 +/- 5")
    monkeypatch.setitem(registry.ENTRIES, "const", e)
    df = synthetic(n_days=300)
    p = registry.fit(df)
    assert p["entry:const"] == {"mu": 70.0}
    mu, s = registry.predict(p, df.tail(3))["const"]
    assert list(mu) == [70.0] * 3 and list(s) == [5.0] * 3
    assert "test_registry.py" in registry.code_files()[-1]


# The module the extra entry above points at.
def fit(train):
    return {"mu": 70.0}


def predict(params, rows):
    return np.full(len(rows), params["mu"]), np.full(len(rows), 5.0)
