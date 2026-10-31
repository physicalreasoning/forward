"""WM-2 truth: the MRMS rain rate on each tile's scored box at the init plus each lead.

The rule, fixed before any round: truth for lead L is the PrecipRate frame valid exactly at
init + L, averaged to 0.02 deg (forward/wm2/mrms.py). A frame absent from the bucket drops that
(init, lead) for every entry; a pixel MRMS flags (no coverage, missing) drops that pixel for
every entry. Nothing is interpolated.
"""

from __future__ import annotations

import numpy as np

from . import baselines


def truth(init_time, store) -> np.ndarray:
    """float32 [tile, lead, TARGET, TARGET] rain rate (mm/h), NaN where there is no truth."""
    x = store.load(baselines.lead_times(baselines._naive(init_time)))  # [lead, tile, C, C]
    return np.moveaxis(baselines._target(x), 0, 1)
