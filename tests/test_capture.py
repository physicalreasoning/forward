import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import capture  # noqa: E402

from forward import isotherm_live  # noqa: E402


def run(monkeypatch, tmp_path, iso_capture):
    monkeypatch.setattr(capture.openmeteo, "live", lambda st: {"day": "2026-11-02", "aifs": 60.0})
    monkeypatch.setattr(isotherm_live, "capture", iso_capture)
    monkeypatch.setattr(sys, "argv", ["capture.py", "--out", str(tmp_path)])
    capture.main()
    (f,) = tmp_path.glob("*.json")
    return json.loads(f.read_text())


def test_model_runs_and_the_isotherm_block_land_in_one_file(monkeypatch, tmp_path):
    seen = {}

    def iso(days):
        seen.update(days)
        return {"health": {}, "rows": [{"station": "NY", "day": days["NY"], "response": {}}]}

    rec = run(monkeypatch, tmp_path, iso)
    assert len(rec["rows"]) == 19 and rec["rows"][0]["aifs"] == 60.0
    assert rec["isotherm"]["rows"][0]["station"] == "NY"
    assert len(seen) == 19  # every station is offered; the entry skips those it does not cover


def test_a_failing_live_entry_never_costs_the_model_runs(monkeypatch, tmp_path):
    def broken(days):
        raise RuntimeError("boom")

    rec = run(monkeypatch, tmp_path, broken)
    assert len(rec["rows"]) == 19
    assert rec["isotherm"] == {"error": "boom", "rows": []}
