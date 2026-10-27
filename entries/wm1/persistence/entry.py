"""WM-1 baseline entry: see forward/wm/baselines.py, function `persistence`."""

from forward.wm import baselines


def predict(init_time, stations, inputs):
    return baselines.persistence(init_time, stations, inputs)
