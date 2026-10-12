import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import leaderboard  # noqa: E402


def test_interval_formatting():
    assert leaderboard.ci({"diff": 0.1334, "ci": [0.0894, 0.178]}) == "**+0.133 [+0.089, +0.178]**"
    assert leaderboard.ci({"diff": -0.01, "ci": [-0.05, 0.03]}) == "-0.010 [-0.050, +0.030]"
    assert leaderboard.ci({"diff": 0.0, "ci": [0.0, 0.0]}) == "baseline"
    assert leaderboard.ci({"mean": -0.021, "ci": [-0.061, 0.019]}) == "-0.021 [-0.061, +0.019]"
