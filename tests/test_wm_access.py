import pandas as pd
import pytest
from wm_fixtures import INIT, FakeStore, truth

from forward.wm.access import Inputs, LeakageError


@pytest.fixture(scope="module")
def tr():
    return truth(start="2026-10-01")


def test_truth_stops_before_the_init_hour(tr):
    inp = Inputs(INIT, ["truth"], truth=tr)
    s = inp.truth("NY")
    assert s.index.max() == INIT - pd.Timedelta(hours=1)
    with pytest.raises(LeakageError):
        inp.truth("NY", end=INIT)


def test_undeclared_source_is_refused(tr):
    inp = Inputs(INIT, ["ensembles"], truth=tr, captures=FakeStore(tr, ["2026-10-25"]))
    with pytest.raises(LeakageError, match="declare"):
        inp.truth("NY")


def test_later_and_late_captures_are_refused(tr):
    st = FakeStore(tr, ["2026-10-24", "2026-10-25", "2026-10-26"])
    inp = Inputs(INIT, ["ensembles"], captures=st)
    assert inp.capture_days() == [pd.Timestamp("2026-10-24"), pd.Timestamp("2026-10-25")]
    with pytest.raises(LeakageError):
        inp.ensembles("2026-10-26")
    # The init day's capture taken after 22:00 UTC was not available at the read.
    late = Inputs(
        INIT, ["ensembles"], captures=FakeStore(tr, ["2026-10-24", "2026-10-25"], late=["2026-10-25"])
    )
    assert late.capture_days() == [pd.Timestamp("2026-10-24")]
    with pytest.raises(LeakageError):
        late.ensembles()


def test_reads_are_logged(tr):
    inp = Inputs(INIT, ["ensembles", "truth"], truth=tr, captures=FakeStore(tr, ["2026-10-25"]))
    inp.ensembles()
    inp.truth("CHI")
    assert inp.log[0] == {"capture": "2026-10-25", "sha256": "fake-2026-10-25"}
    assert inp.log[1]["truth"] == "CHI"
