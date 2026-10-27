"""WM-1 baseline entry: see forward/wm/baselines.py, function `raw`."""

from forward.wm import baselines


def predict(init_time, stations, inputs):
    return baselines.raw(init_time, stations, inputs)
