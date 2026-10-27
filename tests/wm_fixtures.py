"""Synthetic truth and captures for the WM-1 tests: no network, no data files."""

from __future__ import annotations

import numpy as np
import pandas as pd

INIT = pd.Timestamp("2026-10-25T20:00Z")
STATIONS = ["NY", "CHI"]


def truth(stations=STATIONS, start="2015-01-01", end="2026-11-05", seed=0) -> dict[str, pd.Series]:
    idx = pd.date_range(start, end, freq="h", tz="UTC")
    rng = np.random.default_rng(seed)
    out = {}
    for i, s in enumerate(stations):
        doy, hr = idx.dayofyear.to_numpy(), idx.hour.to_numpy()
        base = (
            55 + 20 * np.sin(2 * np.pi * (doy - 110) / 365) + 8 * np.sin(2 * np.pi * (hr - 15) / 24) + 3 * i
        )
        noise = np.cumsum(rng.normal(0, 0.5, len(idx)))
        noise -= pd.Series(noise).rolling(240, min_periods=1).mean().to_numpy()
        out[s] = pd.Series((base + noise).round(1), index=idx, name=s)
    return out


class FakeStore:
    """In-memory captures with the Store interface: two models, every day in `days`."""

    def __init__(self, tr: dict[str, pd.Series], days, members=None, late=(), seed=1):
        self.members = members or {"model_a": 5, "model_b": 3}
        self._days = [pd.Timestamp(d) for d in days]
        self.late = {pd.Timestamp(d) for d in late}
        self.frames = {}
        rng = np.random.default_rng(seed)
        for d in self._days:
            valid = pd.date_range(d.tz_localize("UTC"), periods=8 * 24, freq="h")
            parts = []
            for m, n in self.members.items():
                for s, ser in tr.items():
                    y = ser.reindex(valid).to_numpy()
                    for k in range(n):
                        v = y + 1.5 + rng.normal(0, 1, len(valid)).cumsum() * 0.2
                        parts.append(
                            pd.DataFrame(
                                {"station": s, "model": m, "valid": valid, "member": k, "temperature_2m": v}
                            )
                        )
            self.frames[d] = pd.concat(parts, ignore_index=True)

    def days(self):
        return list(self._days)

    def manifest(self, day):
        day = pd.Timestamp(day)
        t = day.tz_localize("UTC") + pd.Timedelta(hours=23 if day in self.late else 20, minutes=6)
        return {"captured_at": t.isoformat(), "sha256": f"fake-{day.date()}"}

    def load(self, day):
        day = pd.Timestamp(day)
        return self.manifest(day), self.frames[day]
