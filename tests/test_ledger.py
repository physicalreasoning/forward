import json

import pandas as pd

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


def ladder_block(fetched_at, station="NY", day="2026-11-02", p=0.5, model="m1"):
    return {
        "health": {"model_hash": model},
        "health_after": {"model_hash": model},
        "rows": [{"station": station, "day": day, "fetched_at": fetched_at, "response": {"p": p}}],
    }


def write_ladder(d, name, captured_at, block, rows=()):
    (d / name).write_text(json.dumps({"captured_at": captured_at, "rows": list(rows), "iso": block}))


def accept_m1(block):
    return block["health"]["model_hash"] == "m1"


def test_files_without_a_ladder_block_load_as_before(tmp_path):
    write(tmp_path, "2026-11-01.json", "2026-11-01T20:05:00+00:00", [row("NY", "2026-11-02")])
    out, log = ledger.load_ladder(tmp_path, "iso", "2026-11-01", "2026-11-30")
    assert out == {} and log["files"] == 0


def test_a_ladder_block_does_not_change_the_model_rows(tmp_path):
    write_ladder(
        tmp_path,
        "a.json",
        "2026-11-01T20:05:00+00:00",
        ladder_block("2026-11-01T20:06:00+00:00"),
        [row("NY", "2026-11-02")],
    )
    df, log = ledger.load(tmp_path, "2026-11-01", "2026-11-30")
    assert list(df["station"]) == ["NY"] and log == {"files": 1, "late": 0, "errors": 0}


def test_ladder_rows_use_their_own_fetch_time_for_the_deadline(tmp_path):
    # The file was started on time, but this answer arrived after 22:00 UTC on D-1.
    write_ladder(tmp_path, "a.json", "2026-11-01T20:05:00+00:00", ladder_block("2026-11-01T22:00:00+00:00"))
    out, log = ledger.load_ladder(tmp_path, "iso", "2026-11-01", "2026-11-30")
    assert out == {} and log["late"] == 1


def test_ladder_rows_from_another_model_are_rejected(tmp_path):
    write_ladder(
        tmp_path, "a.json", "2026-11-01T20:05:00+00:00", ladder_block("2026-11-01T20:06:00+00:00", model="m2")
    )
    out, log = ledger.load_ladder(tmp_path, "iso", "2026-11-01", "2026-11-30", accept=accept_m1)
    assert out == {} and log["rejected"] == 1


def test_ladder_rerun_keeps_the_earlier_fetch_and_errors_are_counted(tmp_path):
    b = ladder_block("2026-11-01T20:30:00+00:00", p=0.9)
    b["rows"].append({"station": "CHI", "day": "2026-11-02", "error": "HTTP 409"})
    write_ladder(tmp_path, "a.json", "2026-11-01T20:05:00+00:00", b)
    write_ladder(tmp_path, "b.json", "2026-11-01T20:05:00+00:00", ladder_block("2026-11-01T20:06:00+00:00"))
    out, log = ledger.load_ladder(tmp_path, "iso", "2026-11-01", "2026-11-30", accept=accept_m1)
    assert out[("NY", pd.Timestamp("2026-11-02"))]["response"] == {"p": 0.5}
    assert log == {"files": 2, "late": 0, "errors": 1, "rejected": 0}
