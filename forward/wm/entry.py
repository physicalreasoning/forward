"""A frozen WM-1 entry: a directory with a manifest, hashed and committed before the window.

    entries/wm1/<name>/entry.json   the manifest
    entries/wm1/<name>/entry.py     defines predict(init_time, stations, inputs)

The manifest names the entry and pins everything that decides its forecasts:

    id          unique name, e.g. wm1-climatology
    family      "wm1"
    created_at  ISO time the manifest was written
    inputs      the sources it reads through the shim: "truth", "ensembles" (forward/wm/access.py)
    code        {path relative to the repo root: sha256} for every file its forecasts depend on
                beyond the pinned environment (entry.py first)
    weights     null, or {"path": ..., "sha256": ...} for a weights file (or a list of them)
    K, leads, variables   the forecast shape it promises: (K, stations, leads, variables)

`code_sha256` and `weights_sha256` are hashes of those blocks (JSON, sorted keys), and
`manifest_sha256` hashes the whole manifest; all three are written next to every forecast.

`verify` refuses an entry whose code or weights differ from the manifest. `sealed_before`
refuses one whose files were committed after a deadline or have uncommitted changes, so an entry
can only be scored on a window that opened after its last commit. The runner calls both.

`predict(init_time, stations, inputs) -> array[K, len(stations), leads, len(variables)]` gets the
init time (a UTC Timestamp, the 20:00 UTC read), the station keys (forward/stations.py), and the
shim, its only door to data. NaN means no forecast; a NaN in a scored window drops that row for
every entry.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import pathlib
import subprocess
from dataclasses import dataclass

import pandas as pd

from .. import ROOT

FIELDS = ("id", "family", "created_at", "inputs", "code", "weights", "K", "leads", "variables")
SOURCES = {"truth", "ensembles"}


class EntryRefused(RuntimeError):
    """The entry's files do not match its manifest, or were not sealed in time."""


def blob_sha256(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _weights(w) -> list[dict]:
    return [] if w is None else (w if isinstance(w, list) else [w])


def write_manifest(entry_dir: pathlib.Path, root: pathlib.Path = ROOT, **fields) -> dict:
    """Write entry.json with the current hashes of `code` (a list of paths) and `weights`.

    created_at is kept if the manifest exists, so rehashing does not move the creation time;
    the commit time is what the seal checks.
    """
    entry_dir = pathlib.Path(entry_dir)
    f = entry_dir / "entry.json"
    old = json.loads(f.read_text()) if f.exists() else {}
    code = fields.pop("code")
    weights = fields.pop("weights", None)
    man = {
        "created_at": old.get("created_at", dt.datetime.now(dt.UTC).isoformat(timespec="seconds")),
        **fields,
        "code": {p: file_sha256(root / p) for p in code},
        "weights": [{"path": w, "sha256": file_sha256(root / w)} for w in weights] if weights else None,
    }
    missing = [k for k in FIELDS if k not in man]
    if missing:
        raise ValueError(f"manifest lacks {missing}")
    f.write_text(json.dumps(man, indent=1) + "\n")
    return man


@dataclass
class Entry:
    dir: pathlib.Path
    manifest: dict
    root: pathlib.Path

    @property
    def id(self) -> str:
        return self.manifest["id"]

    @property
    def code_sha256(self) -> str:
        return blob_sha256(self.manifest["code"])

    @property
    def weights_sha256(self) -> str | None:
        w = self.manifest["weights"]
        return None if w is None else blob_sha256(w)

    @property
    def manifest_sha256(self) -> str:
        return blob_sha256(self.manifest)

    def files(self) -> list[str]:
        """Every file the seal covers, relative to the root."""
        rel = (self.dir / "entry.json").resolve().relative_to(self.root.resolve())
        return [str(rel), *self.manifest["code"], *(w["path"] for w in _weights(self.manifest["weights"]))]

    def verify(self) -> None:
        """Refuse unless every code and weights file hashes as the manifest says."""
        m = self.manifest
        missing = [k for k in FIELDS if k not in m]
        if missing:
            raise EntryRefused(f"{self.dir}: manifest lacks {missing}")
        if not set(m["inputs"]) <= SOURCES:
            raise EntryRefused(f"{self.id}: unknown inputs {set(m['inputs']) - SOURCES}")
        entry_py = (self.dir / "entry.py").resolve().relative_to(self.root.resolve())
        if str(entry_py) not in m["code"]:
            raise EntryRefused(f"{self.id}: entry.py is not hashed in the manifest")
        bad = []
        for p, h in [*m["code"].items(), *((w["path"], w["sha256"]) for w in _weights(m["weights"]))]:
            f = self.root / p
            if not f.exists() or file_sha256(f) != h:
                bad.append(p)
        if bad:
            raise EntryRefused(f"{self.id}: changed since the manifest: {bad}")

    def sealed_before(self, deadline) -> pd.Timestamp:
        """Refuse unless every sealed file is committed, unchanged, with its last commit before
        `deadline` (the window's first init). Returns the latest commit time."""
        deadline = pd.Timestamp(deadline)
        deadline = deadline.tz_localize("UTC") if deadline.tzinfo is None else deadline
        files = self.files()
        git = ["git", "-C", str(self.root)]
        dirty = subprocess.run([*git, "status", "--porcelain", "--", *files], capture_output=True, text=True)
        if dirty.returncode or dirty.stdout.strip():
            raise EntryRefused(
                f"{self.id}: uncommitted changes: {dirty.stdout.strip() or dirty.stderr.strip()}"
            )
        latest = None
        for p in files:
            out = subprocess.run([*git, "log", "-1", "--format=%cI", "--", p], capture_output=True, text=True)
            if out.returncode or not out.stdout.strip():
                raise EntryRefused(f"{self.id}: {p} is not committed")
            t = pd.Timestamp(out.stdout.strip()).tz_convert("UTC")
            latest = t if latest is None or t > latest else latest
        if latest >= deadline:
            raise EntryRefused(f"{self.id}: last committed {latest}, not before {deadline}")
        return latest

    def module(self):
        """Import entry.py (call verify first: the runner does)."""
        spec = importlib.util.spec_from_file_location(
            f"wm_entry_{self.id.replace('-', '_')}", self.dir / "entry.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not callable(getattr(mod, "predict", None)):
            raise EntryRefused(f"{self.id}: entry.py has no predict")
        return mod


def load(entry_dir, root: pathlib.Path = ROOT) -> Entry:
    entry_dir = pathlib.Path(entry_dir)
    if not entry_dir.is_absolute():
        entry_dir = pathlib.Path(root) / entry_dir
    return Entry(entry_dir, json.loads((entry_dir / "entry.json").read_text()), pathlib.Path(root))
