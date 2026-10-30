"""Captured MRMS tiles: one compressed file per UTC day, with a manifest tying it to NOAA's files.

    data/wm2/tiles/YYYY-MM-DD.npz    times (int64 ns), tiles (keys), q uint16 [time, tile, C, C]
    data/wm2/tiles/YYYY-MM-DD.json   manifest: captured_at, product, grid, the npz's sha256 and,
                                     per frame, the source key, size and S3 ETag

Values are packed by `mrms.pack` (tenths of mm/h, 65535 for NaN). A frame that is not in the
bucket is recorded in the manifest's `missing` list and is NaN when loaded; nothing is
interpolated. Unlike WM-1's ensembles, MRMS is archived on the bucket back to 2020-10-14, so a
capture is a convenience and a hash record, not the only copy (docs/WM2_DRAFT.md).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import urllib.error
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from . import mrms


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


class HashMismatch(RuntimeError):
    pass


def _get(t: pd.Timestamp, product: str, tiles: list[mrms.Tile]):
    try:
        raw = mrms.fetch(t, product)
    except urllib.error.HTTPError as ex:
        if ex.code in (403, 404):  # S3 answers 403 to anonymous requests for absent keys
            return t, None, None
        raise
    f = mrms.decode(raw)
    if f.ref_time != t:
        raise mrms.NotMRMS(f"{mrms.key(t, product)} holds {f.ref_time}")
    return t, mrms.pack(mrms.cut(f.values, tiles)), len(raw)


class Store:
    def __init__(self, root: pathlib.Path, tiles: list[mrms.Tile], product: str = mrms.PRODUCT):
        self.root = pathlib.Path(root)
        self.tiles = list(tiles)
        self.keys = [t.key for t in self.tiles]
        self.product = product
        self._cache: dict[str, tuple[dict, dict[pd.Timestamp, np.ndarray]]] = {}

    def _paths(self, day: str) -> tuple[pathlib.Path, pathlib.Path]:
        return self.root / f"{day}.npz", self.root / f"{day}.json"

    def days(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json") if (self.root / f"{p.stem}.npz").exists())

    def _load_day(self, day: str) -> tuple[dict, dict[pd.Timestamp, np.ndarray]]:
        if day not in self._cache:
            npz, man_p = self._paths(day)
            if not man_p.exists():
                self._cache[day] = ({}, {})
                return self._cache[day]
            man = json.loads(man_p.read_text())
            got = sha256(npz)
            if got != man["sha256"]:
                raise HashMismatch(f"{npz.name}: sha256 {got[:12]}, manifest {man['sha256'][:12]}")
            z = np.load(npz, allow_pickle=False)
            if list(z["tiles"]) != self.keys:
                raise ValueError(f"{npz.name} holds tiles {list(z['tiles'])}, store wants {self.keys}")
            times = pd.to_datetime(z["times"])
            q = z["q"]  # decompress once, not once per frame
            self._cache[day] = (man, {t: q[i] for i, t in enumerate(times)})
        return self._cache[day]

    def times(self) -> list[pd.Timestamp]:
        """Every captured frame time, oldest first."""
        return sorted(t for d in self.days() for t in self._load_day(d)[1])

    def has(self, t) -> bool:
        t = pd.Timestamp(t)
        return t in self._load_day(str(t.date()))[1]

    def load(self, times) -> np.ndarray:
        """float32 [len(times), tile, CONTEXT, CONTEXT]; NaN for a frame not captured."""
        out = np.full((len(times), len(self.tiles), mrms.CONTEXT, mrms.CONTEXT), np.nan, np.float32)
        for i, t in enumerate(times):
            t = pd.Timestamp(t)
            q = self._load_day(str(t.date()))[1].get(t)
            if q is not None:
                out[i] = mrms.unpack(q)
        return out

    def capture(self, times, workers: int = 6) -> dict:
        """Fetch, decode and cut every time not yet captured; rewrite each touched day's file.

        A frame absent from the bucket is listed as missing; any other failure raises, so a day
        file never silently lacks a frame that exists.
        """
        want = sorted({pd.Timestamp(t) for t in times})
        todo = [t for t in want if not self.has(t)]
        stats = {"requested": len(want), "fetched": 0, "missing": [], "bytes": 0}
        if not todo:
            return stats
        listing: dict[str, dict] = {}
        for day in sorted({str(t.date()) for t in todo}):
            listing.update({str(k): v for k, v in mrms.list_day(day, self.product).items()})
        got: dict[pd.Timestamp, np.ndarray | None] = {}
        with ThreadPoolExecutor(workers) as ex:
            for t, q, n in ex.map(lambda t: _get(t, self.product, self.tiles), todo):
                got[t] = q
                stats["bytes"] += n or 0
        self.root.mkdir(parents=True, exist_ok=True)
        for day in sorted({str(t.date()) for t in todo}):
            man, frames = self._load_day(day)
            frames = dict(frames)
            sources = dict(man.get("sources", {}))
            missing = set(man.get("missing", []))
            for t in (t for t in todo if str(t.date()) == day):
                if got[t] is None:
                    missing.add(str(t))
                    stats["missing"].append(str(t))
                else:
                    frames[t] = got[t]
                    sources[str(t)] = listing.get(str(t), {"key": mrms.key(t, self.product)})
                    missing.discard(str(t))
                    stats["fetched"] += 1
            ts = sorted(frames)
            npz, man_p = self._paths(day)
            np.savez_compressed(
                npz,
                times=np.array([t.value for t in ts], dtype=np.int64),
                tiles=np.array(self.keys),
                q=np.stack([frames[t] for t in ts]),
            )
            man = {
                "captured_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "product": self.product,
                "grid": {"coarsen": mrms.COARSEN, "context": mrms.CONTEXT, "scale": mrms.SCALE},
                "tiles": {t.key: [t.row0, t.col0] for t in self.tiles},
                "file": npz.name,
                "sha256": sha256(npz),
                "frames": len(ts),
                "missing": sorted(missing),
                "sources": dict(sorted(sources.items())),
            }
            man_p.write_text(json.dumps(man, indent=1) + "\n")
            self._cache.pop(day, None)
        return stats
