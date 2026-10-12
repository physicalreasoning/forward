import json

from forward import ledger


def write(d, name, captured_at, rows):
    (d / name).write_text(json.dumps({"captured_at": captured_at, "rows": rows}))


def row(station, day, v=70.0):
    return {"station": station, "day": day, "aifs": v, "ifs": v, "gfs": v, "icon": v, "nbm": v}


def test_on_time_capture_counts_late_one_does_not(tmp_path):
    write(tmp_path, "2026-11-01.json", "2026-11-01T20:05:00+00:00", [row("NY", "2026-11-02")])
    write(tmp_path, "2026-11-02.json", "2026-11-02T22:30:00+00:00", [row("NY", "2026-11-03")])
    df, log = ledger.load(tmp_path, "2026-11-01", "2026-11-30")
    assert list(df["day"].dt.strftime("%Y-%m-%d")) == ["2026-11-02"]
    assert log == {"files": 2, "late": 1, "errors": 0}


def test_errors_and_out_of_window_rows_are_dropped(tmp_path):
    rows = [row("NY", "2026-11-02"), {"station": "CHI", "error": "timeout"}, row("MIA", "2027-01-05")]
    write(tmp_path, "2026-11-01.json", "2026-11-01T20:05:00+00:00", rows)
    df, log = ledger.load(tmp_path, "2026-11-01", "2026-12-26")
    assert list(df["station"]) == ["NY"]
    assert log["errors"] == 1


def test_a_rerun_keeps_the_earlier_capture(tmp_path):
    write(tmp_path, "a.json", "2026-11-01T20:05:00+00:00", [row("NY", "2026-11-02", 70.0)])
    write(tmp_path, "b.json", "2026-11-01T21:00:00+00:00", [row("NY", "2026-11-02", 75.0)])
    df, _ = ledger.load(tmp_path, "2026-11-01", "2026-11-30")
    assert len(df) == 1 and df["aifs"].iat[0] == 70.0
