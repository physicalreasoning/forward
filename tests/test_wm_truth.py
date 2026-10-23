import pandas as pd

from forward.wm import truth


def test_nearest_report_within_ten_minutes():
    obs = pd.DataFrame(
        {
            "valid": pd.to_datetime(
                ["2026-10-23T00:51Z", "2026-10-23T01:05Z", "2026-10-23T01:51Z", "2026-10-23T03:30Z"]
            ),
            "tmpf": [50.0, 51.0, 52.0, 60.0],
        }
    )
    t = truth.match_hours(obs)
    h = pd.Timestamp("2026-10-23T01:00Z")
    assert t[h] == 51.0  # 01:05 is nearer than 00:51
    assert t[h + pd.Timedelta(hours=1)] == 52.0  # 01:51 is nine minutes before 02:00
    # 03:00 has no report within ten minutes: no truth, never interpolated.
    assert h + pd.Timedelta(hours=2) not in t.index
