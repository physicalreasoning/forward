"""WM-1 baseline entry: see forward/wm/baselines.py, function `emos_ecc`."""

from forward.wm import baselines


def predict(init_time, stations, inputs):
    return baselines.emos_ecc(init_time, stations, inputs)
