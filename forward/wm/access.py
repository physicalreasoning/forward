"""What a WM-1 entry may read at the read, and nothing else.

An entry's `predict` gets an `Inputs` object as its only door to data. It serves:

- `truth(station, start, end)`: hourly ASOS truth (`forward/wm/truth.py`) for hours strictly
  before the init time. The truth for the init hour itself can come from a report up to ten
  minutes after it, so it is not available at the read.
- `ensembles(day)`: a captured ensemble file (`forward/wm/captures.py`) for a read on or before
  the init day. The init day's own capture counts only if it was taken before 22:00 UTC, the
  deadline the station-highs ledger uses (`forward/ledger.py`).

A request for anything later raises `LeakageError`; a source the entry did not declare in its
manifest raises it too. While `predict` runs, `guard()` also refuses network connections,
subprocesses and opening files under the data directories, so an entry cannot read around the
shim. Python cannot sandbox code it runs in-process, so the guard is a tripwire, not a jail; the
seal is the hashed code, which anyone can read, plus the invariance test in
`tests/test_wm_runner.py` that runs every baseline with the future truth replaced and requires
identical forecasts.
"""

from __future__ import annotations

import contextlib
import contextvars
import pathlib
import sys

import pandas as pd

from .. import DATA

LATEST_HOUR_UTC = 22  # a capture of day D counts for the read of day D if taken before this hour


class LeakageError(RuntimeError):
    """An entry asked for data that did not exist at its init time."""


_guarded: contextvars.ContextVar[bool] = contextvars.ContextVar("wm_guarded", default=False)
_inside: contextvars.ContextVar[bool] = contextvars.ContextVar("wm_inside", default=False)
_roots: list[pathlib.Path] = [DATA.resolve()]
_hooked = False

_BLOCKED = {
    "socket.connect",
    "socket.getaddrinfo",
    "subprocess.Popen",
    "os.system",
    "os.exec",
    "os.posix_spawn",
}


def _hook(event: str, args: tuple) -> None:
    if not _guarded.get() or _inside.get():
        return
    if event in _BLOCKED:
        raise LeakageError(f"entry tried {event} during predict")
    if event == "open" and args and isinstance(args[0], str | bytes | pathlib.Path):
        try:
            p = pathlib.Path(args[0].decode() if isinstance(args[0], bytes) else args[0]).resolve()
        except (OSError, ValueError):
            return
        if any(p == r or r in p.parents for r in _roots):
            raise LeakageError(f"entry tried to open {p} during predict")


def protect(path: pathlib.Path) -> None:
    """Add a directory the guard refuses to open files under (e.g. where captures are kept)."""
    p = pathlib.Path(path).resolve()
    if p not in _roots:
        _roots.append(p)


@contextlib.contextmanager
def guard():
    """Run an entry's predict with network, subprocesses and data files refused."""
    global _hooked
    if not _hooked:
        sys.addaudithook(_hook)  # permanent once added; it acts only inside guard()
        _hooked = True
    tok = _guarded.set(True)
    try:
        yield
    finally:
        _guarded.reset(tok)


@contextlib.contextmanager
def _shim():
    tok = _inside.set(True)
    try:
        yield
    finally:
        _inside.reset(tok)


class Inputs:
    """The data available at `init_time`, for one entry's declared sources.

    truth: {station key: hourly Series indexed by UTC hour}, possibly reaching past the init
    (the runner holds all of it; the shim cuts it). captures: an object with `days()` and
    `load(day) -> (manifest, frame)`, as `forward.wm.captures.Store`.
    """

    def __init__(self, init_time, declared, truth=None, captures=None):
        t = pd.Timestamp(init_time)
        self.init_time = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
        self.declared = frozenset(declared)
        self._truth = truth or {}
        self._captures = captures
        self.log: list[dict] = []

    def _need(self, source: str) -> None:
        if source not in self.declared:
            raise LeakageError(f"entry did not declare input {source!r}")

    def truth(self, station: str, start=None, end=None) -> pd.Series:
        """Hourly truth at a station for hours in [start, end]; end defaults to the last hour
        before the init and may not be later."""
        self._need("truth")
        last = self.init_time - pd.Timedelta(hours=1)
        end = last if end is None else pd.Timestamp(end)
        if end > last:
            raise LeakageError(f"truth requested to {end}, after the last hour before init {self.init_time}")
        s = self._truth.get(station)
        if s is None:
            return pd.Series(dtype=float, name=station)
        with _shim():
            out = s.loc[(pd.Timestamp(start) if start is not None else s.index.min()) : end].copy()
        self.log.append({"truth": station, "end": str(end)})
        return out

    def _on_time(self, day: pd.Timestamp, manifest: dict) -> bool:
        captured = pd.Timestamp(manifest["captured_at"]).tz_convert("UTC")
        return captured < day.tz_localize("UTC") + pd.Timedelta(hours=LATEST_HOUR_UTC)

    def capture_days(self) -> list[pd.Timestamp]:
        """Days whose capture was available at the init, oldest first."""
        self._need("ensembles")
        if self._captures is None:
            return []
        init_day = self.init_time.tz_convert("UTC").tz_localize(None).normalize()
        with _shim():
            days = [d for d in self._captures.days() if d < init_day]
            if init_day in self._captures.days() and self._on_time(
                init_day, self._captures.manifest(init_day)
            ):
                days.append(init_day)
        return days

    def ensembles(self, day=None) -> pd.DataFrame:
        """One read's captured ensembles (default: the init day's). Later reads are refused."""
        self._need("ensembles")
        init_day = self.init_time.tz_convert("UTC").tz_localize(None).normalize()
        day = init_day if day is None else pd.Timestamp(day).normalize()
        if day > init_day:
            raise LeakageError(f"capture of {day.date()} requested at init {self.init_time}")
        if day not in self.capture_days():
            raise LeakageError(f"capture of {day.date()} was not available at init {self.init_time}")
        with _shim():
            man, frame = self._captures.load(day)
        self.log.append({"capture": str(day.date()), "sha256": man["sha256"]})
        return frame.copy()
