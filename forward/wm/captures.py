"""The captured ensemble reads (scripts/capture_wm.py), loaded and checked against their hashes.

Each read is two files: the manifest `wm/YYYY-MM-DD.json` on the public `ledger-wm` branch and
the trajectories `wm-YYYY-MM-DD.parquet`, an asset of the `wm-ledger` release. A file whose
sha256 differs from its manifest is refused, so every forecast made from a capture is tied to
the commit that proves the capture predates the outcomes.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import urllib.request

import pandas as pd

REPO = "physicalreasoning/forward"
ASSET = "https://github.com/{repo}/releases/download/wm-ledger/wm-{day}.parquet"
MANIFEST = "https://raw.githubusercontent.com/{repo}/ledger-wm/wm/{day}.json"


class HashMismatch(RuntimeError):
    pass


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def download(days, out: pathlib.Path, repo: str = REPO) -> None:
    """Fetch the manifests and assets of `days` (YYYY-MM-DD) into out/ and out/wm/."""
    (out / "wm").mkdir(parents=True, exist_ok=True)
    for day in days:
        for url, dest in (
            (MANIFEST.format(repo=repo, day=day), out / "wm" / f"{day}.json"),
            (ASSET.format(repo=repo, day=day), out / f"wm-{day}.parquet"),
        ):
            if not dest.exists():
                with urllib.request.urlopen(url, timeout=120) as r:
                    dest.write_bytes(r.read())


class Store:
    """Captures in a directory laid out as the capture writes them: wm/D.json and wm-D.parquet."""

    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root)
        self._cache: dict[pd.Timestamp, tuple[dict, pd.DataFrame]] = {}

    def days(self) -> list[pd.Timestamp]:
        return sorted(
            pd.Timestamp(f.stem)
            for f in (self.root / "wm").glob("*.json")
            if (self.root / f"wm-{f.stem}.parquet").exists()
        )

    def manifest(self, day) -> dict:
        return json.loads((self.root / "wm" / f"{pd.Timestamp(day).date()}.json").read_text())

    def load(self, day) -> tuple[dict, pd.DataFrame]:
        day = pd.Timestamp(day).normalize()
        if day not in self._cache:
            man = self.manifest(day)
            pq = self.root / man["file"]
            got = sha256(pq)
            if got != man["sha256"]:
                raise HashMismatch(f"{pq.name}: sha256 {got[:12]} but the manifest says {man['sha256'][:12]}")
            self._cache[day] = (man, pd.read_parquet(pq))
        return self._cache[day]
