"""What a WM-2 entry may read at its init time, and nothing else (mirrors forward/wm/access.py).

`Inputs.radar(times)` serves captured MRMS context tiles (forward/wm2/store.py) for frames
valid strictly before the init time. MRMS publishes a frame about three minutes after its valid
time, so the frame valid at the init itself would not exist at a live read; at the 10-minute
cadence the latest frame an entry sees is init - 10 min. A request for a frame at or after the
init raises `LeakageError`. Past years' frames are allowed (they are before the init), which is
what an analogue climatology reads.

The guard, the protected data directories and `LeakageError` are WM-1's own
(`forward.wm.access`), imported, not changed: while `predict` runs, network connections,
subprocesses and opening files under the data directories are refused.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..wm.access import LeakageError, _shim, guard, protect

__all__ = ["Inputs", "LeakageError", "guard", "protect"]


def _naive(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t


class Inputs:
    def __init__(self, init_time, store, declared=("radar",)):
        t = pd.Timestamp(init_time)
        self.init_time = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
        self._naive = self.init_time.tz_localize(None)
        self._store = store
        self.declared = frozenset(declared)
        self.tiles = list(store.keys)
        self.station_rc = {t.key: t.station_rc for t in store.tiles}
        self.log: list[dict] = []

    def radar(self, times) -> np.ndarray:
        """float32 [len(times), tile, CONTEXT, CONTEXT] rain rate (mm/h); NaN if not captured."""
        if "radar" not in self.declared:
            raise LeakageError("entry did not declare input 'radar'")
        ts = [_naive(t) for t in times]
        late = [t for t in ts if t >= self._naive]
        if late:
            raise LeakageError(f"radar frame {late[0]} requested at init {self.init_time}")
        with _shim():
            x = self._store.load(ts)
        if ts:
            self.log.append({"radar": len(ts), "first": str(min(ts)), "last": str(max(ts))})
        return x
