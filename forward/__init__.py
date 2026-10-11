"""Sealed forward tests for world models."""

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
# isotherm's HTTP cache would otherwise land inside site-packages.
os.environ.setdefault("ISOTHERM_CACHE", str(DATA / "http"))
