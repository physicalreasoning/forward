import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import leaderboard  # noqa: E402


def test_interval_formatting():
    assert leaderboard.ci({"diff": 0.1334, "ci": [0.0894, 0.178]}) == "**+0.133 [+0.089, +0.178]**"
    assert leaderboard.ci({"diff": -0.01, "ci": [-0.05, 0.03]}) == "-0.010 [-0.050, +0.030]"
    assert leaderboard.ci({"diff": 0.0, "ci": [0.0, 0.0]}) == "baseline"
    assert leaderboard.ci({"mean": -0.021, "ci": [-0.061, 0.019]}) == "-0.021 [-0.061, +0.019]"


def test_common_ladder_table_lists_every_entry_with_its_kind():
    x = {
        "log_vs_market_bid": {"diff": 0.1, "ci": [0.05, 0.15]},
        "log_vs_market_mid": {"diff": 0.0, "ci": [-0.1, 0.1]},
        "pnl_slip1": 3.0,
        "pnl_slip1_per_ladder": {"mean": 0.01, "ci": [-0.01, 0.03]},
    }
    r = {
        "ladders_common": {
            "ladders": 700,
            "entries": {"emos-all": "gaussian", "isotherm": "ladder"},
            "emos-all": x | {"log_vs_market_bid": {"diff": -0.1, "ci": [-0.2, -0.05]}},
            "isotherm": x,
            "market_bid_log": -1.2,
            "market_mid_log": -1.19,
        }
    }
    t = leaderboard.common_table(r)
    assert t[0] == "### Every entry on the 700 ladders isotherm also covers"
    rows = [line for line in t if line.startswith("| ") and "---" not in line][1:]
    assert rows[0].startswith("| isotherm | ladder | **+0.100") and rows[1].startswith(
        "| emos-all | gaussian"
    )
    assert (
        leaderboard.common_table({}) == []
        and leaderboard.common_table({"ladders_common": {"ladders": 0}}) == []
    )
