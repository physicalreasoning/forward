"""WM-1 baseline entry: see forward/wm/baselines.py, function `climatology`."""

from forward.wm import baselines


def predict(init_time, stations, inputs):
    return baselines.climatology(init_time, stations, inputs)
