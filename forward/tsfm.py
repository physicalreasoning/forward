"""Time-series foundation models as entries: Chronos-Bolt (Ansari et al. 2024) and TimesFM 2.5
(Das et al. 2024). Both are used zero-shot, as released; nothing is fit on our data.

Each returns quantiles of the price `h` hourly bars ahead. We read them as a lognormal: centre
at the median, spread from the 10th and 90th percentiles in log space. The models' own quantile
grid stops at 10% and 90%, so the tails have to come from somewhere; a lognormal is the same
family as the copy baseline, which keeps the comparison about location and spread.
"""

from __future__ import annotations

import numpy as np

# Hugging Face revisions, pinned so an upstream update cannot change a frozen entry.
REVISION = {
    "amazon/chronos-bolt-small": "772f3d25d38aec6d914c8949dab4462e2d46f5d8",
    "amazon/chronos-bolt-base": "5d9f166d69f47aef3401367a7b842e78fe97b121",
    "google/timesfm-2.5-200m-pytorch": "1d952420fba87f3c6dee4f240de0f1a0fbc790e3",
}

Z90 = 2.5631  # distance between the 10th and 90th percentiles of a standard normal


def _to_lognormal(q10, q50, q90):
    q10, q50, q90 = (np.maximum(np.asarray(x, float), 1e-12) for x in (q10, q50, q90))
    sigma = np.maximum((np.log(q90) - np.log(q10)) / Z90, 1e-4)
    return q50, sigma


class Chronos:
    def __init__(self, name="amazon/chronos-bolt-small"):
        import torch
        from chronos import BaseChronosPipeline

        self.name = name
        self.p = BaseChronosPipeline.from_pretrained(
            name, revision=REVISION[name], device_map="cpu", torch_dtype=torch.float32
        )

    def predict(self, contexts, horizons):
        import torch

        H = max(horizons)
        q, _ = self.p.predict_quantiles(
            [torch.tensor(c, dtype=torch.float32) for c in contexts],
            prediction_length=H,
            quantile_levels=[0.1, 0.5, 0.9],
        )
        q = q.numpy()
        idx = np.asarray(horizons) - 1
        r = np.arange(len(contexts))
        return _to_lognormal(q[r, idx, 0], q[r, idx, 1], q[r, idx, 2])


class TimesFM:
    def __init__(self, name="google/timesfm-2.5-200m-pytorch", max_horizon=64):
        import timesfm

        self.name = name
        self.m = timesfm.TimesFM_2p5_200M_torch.from_pretrained(name, revision=REVISION[name])
        self.m.compile(
            timesfm.ForecastConfig(
                max_context=512,
                max_horizon=max_horizon,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
                fix_quantile_crossing=True,
            )
        )

    def predict(self, contexts, horizons):
        H = max(horizons)
        _, q = self.m.forecast(horizon=H, inputs=[np.asarray(c, float) for c in contexts])
        idx = np.asarray(horizons) - 1
        r = np.arange(len(contexts))
        # q[..., 0] is the mean; 1..9 are the 10th..90th percentiles.
        return _to_lognormal(q[r, idx, 1], q[r, idx, 5], q[r, idx, 9])
