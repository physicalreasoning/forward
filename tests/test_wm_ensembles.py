import pandas as pd

from forward.wm import ensembles


def _js():
    return {
        "hourly": {
            "time": ["2026-10-23T00:00", "2026-10-23T01:00"],
            "temperature_2m": [50.0, 49.5],
            "temperature_2m_member01": [51.0, None],
            "temperature_2m_member02": [49.0, 48.0],
            "precipitation": [0.0, 0.1],
            "precipitation_member01": [0.2, 0.0],
            "precipitation_member02": [0.0, 0.0],
        }
    }


def test_frame_members_and_control():
    d = ensembles._frame(_js(), "NY", "ifs_ens")
    assert sorted(d.member.unique()) == [0, 1, 2]
    assert len(d) == 6
    r = d[(d.member == 1) & (d.valid == pd.Timestamp("2026-10-23T00:00", tz="UTC"))].iloc[0]
    assert r.temperature_2m == 51.0 and r.precipitation == 0.2
    # A missing member value stays missing; it is never filled.
    assert d[(d.member == 1)].temperature_2m.isna().sum() == 1


def test_to_array_shape():
    a, valid, members = ensembles.to_array(ensembles._frame(_js(), "NY", "ifs_ens"))
    assert a.shape == (3, 2) and members == [0, 1, 2] and len(valid) == 2


def test_no_model_without_a_domain_fetches_metadata():
    assert ensembles.meta(None) == {}
