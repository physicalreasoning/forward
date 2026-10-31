"""Read NOAA MRMS fields from the public AWS bucket and cut tiles around the stations.

MRMS (Zhang et al. 2016) is on the NOAA Open Data Dissemination program's bucket
`s3://noaa-mrms-pds` (us-east-1), readable over plain HTTPS without credentials:

    https://noaa-mrms-pds.s3.amazonaws.com/CONUS/<product>/<YYYYMMDD>/MRMS_<product>_<YYYYMMDD-HHMMSS>.grib2.gz

Each file is one gzipped GRIB2 message on the CONUS grid: 7000 x 3500 points at 0.01 deg,
north-west corner (54.995 N, 129.995 W), rows north to south. MRMS packs values as PNG
(GRIB2 data template 5.41); this module reads that template and the regular lat/lon grid
(template 3.0) and nothing else, refusing any other. Values below zero are flags (-3: no radar
coverage, -1: missing) and become NaN.

Tiles: the native grid is averaged 2 x 2 to 0.02 deg (about 2 km), then a CONTEXT x CONTEXT
box is cut around each station. A box that would leave the CONUS grid is shifted inside it, so
a coastal station is off-centre in its tile; the station's pixel is recorded per tile.
"""

from __future__ import annotations

import gzip
import io
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import numpy as np
import pandas as pd

BUCKET = "https://noaa-mrms-pds.s3.amazonaws.com"
PRODUCT = "PrecipRate_00.00"  # instantaneous surface rain rate, mm/h, every 2 minutes
NI, NJ = 7000, 3500
LAT0, LON0, STEP = 54.995, -129.995, 0.01  # centre of the first (north-west) point
COARSEN = 2  # native points per tile pixel along each axis: 0.02 deg
CONTEXT = 256  # tile pixels per side served as inputs (5.12 deg)
TARGET = 128  # central pixels per side that are scored (2.56 deg)


class NotMRMS(ValueError):
    """The file is not a GRIB2 message this reader understands."""


def key(time, product: str = PRODUCT) -> str:
    t = pd.Timestamp(time)
    return f"CONUS/{product}/{t:%Y%m%d}/MRMS_{product}_{t:%Y%m%d-%H%M%S}.grib2.gz"


def url(time, product: str = PRODUCT) -> str:
    return f"{BUCKET}/{key(time, product)}"


def _read(u: str, timeout: int = 60, tries: int = 4) -> bytes:
    """GET with retries on network errors (not on HTTP errors: a 404 is an answer)."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(u, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if i == tries - 1:
                raise
            time.sleep(2**i)
    raise AssertionError("unreachable")


def list_day(day, product: str = PRODUCT) -> dict[pd.Timestamp, dict]:
    """{valid time: {"key", "size", "etag"}} for every file of a UTC day in the bucket."""
    d = pd.Timestamp(day)
    prefix = f"CONUS/{product}/{d:%Y%m%d}/"
    out, token = {}, None
    while True:
        q = {"list-type": "2", "prefix": prefix}
        if token:
            q["continuation-token"] = token
        x = _read(f"{BUCKET}/?{urllib.parse.urlencode(q)}").decode()
        for k, etag, size in re.findall(
            r"<Key>(.*?)</Key>.*?<ETag>(.*?)</ETag>.*?<Size>(\d+)</Size>", x, flags=re.S
        ):
            m = re.search(r"_(\d{8}-\d{6})\.grib2\.gz$", k)
            if m:
                t = pd.Timestamp(pd.to_datetime(m.group(1), format="%Y%m%d-%H%M%S"))
                out[t] = {"key": k, "size": int(size), "etag": etag.replace("&quot;", "").strip('"')}
        m = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", x)
        if not m:
            return out
        token = m.group(1)


def fetch(time, product: str = PRODUCT, timeout: int = 60) -> bytes:
    """The gzipped GRIB2 bytes of one file (raises urllib's HTTPError if it does not exist)."""
    return _read(url(time, product), timeout=timeout)


def _sm(b: bytes) -> int:
    """GRIB2 sign-and-magnitude integer."""
    v = int.from_bytes(b, "big")
    top = 1 << (8 * len(b) - 1)
    return -(v & (top - 1)) if v & top else v


@dataclass(frozen=True)
class Field:
    values: np.ndarray  # float32 [NJ, NI], NaN where flagged
    ref_time: pd.Timestamp
    lat0: float
    lon0: float
    step: float


def decode(raw: bytes) -> Field:
    """Decode one MRMS GRIB2 message (gzipped or not) on the regular lat/lon grid, PNG-packed."""
    from PIL import Image  # the wm2 dependency group; only the decoder needs it

    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    if raw[:4] != b"GRIB" or raw[7] != 2:
        raise NotMRMS("not a GRIB2 message")
    i, sec = 16, {}
    while raw[i : i + 4] != b"7777":
        n_bytes = struct.unpack(">I", raw[i : i + 4])[0]
        if n_bytes < 5 or i + n_bytes > len(raw):
            raise NotMRMS("truncated section")
        sec[raw[i + 4]] = raw[i : i + n_bytes]
        i += n_bytes
    s1, s3, s5, s6, s7 = (sec.get(k) for k in (1, 3, 5, 6, 7))
    if None in (s1, s3, s5, s6, s7):
        raise NotMRMS("missing section")
    year, month, day, hour, minute, second = struct.unpack(">HBBBBB", s1[12:19])
    if struct.unpack(">H", s3[12:14])[0] != 0:
        raise NotMRMS("grid is not template 3.0 (regular lat/lon)")
    ni, nj = struct.unpack(">II", s3[30:38])
    la1, lo1 = _sm(s3[46:50]) / 1e6, _sm(s3[50:54]) / 1e6
    di = struct.unpack(">I", s3[63:67])[0] / 1e6
    if s3[71] != 0:
        raise NotMRMS(f"scanning mode {s3[71]}, expected 0 (west to east, north to south)")
    if struct.unpack(">H", s5[9:11])[0] != 41:
        raise NotMRMS("data are not PNG-packed (template 5.41)")
    ref = struct.unpack(">f", s5[11:15])[0]
    e, d = _sm(s5[15:17]), _sm(s5[17:19])
    if s6[5] != 255:
        raise NotMRMS("bitmaps are not supported")
    img = np.asarray(Image.open(io.BytesIO(s7[5:])))
    if img.shape != (nj, ni):
        raise NotMRMS(f"image {img.shape}, grid {(nj, ni)}")
    v = ((ref + img.astype(np.float32) * np.float32(2.0**e)) / np.float32(10.0**d)).astype(np.float32)
    v[v < 0] = np.nan
    lon1 = lo1 - 360 if lo1 > 180 else lo1
    t = pd.Timestamp(year=year, month=month, day=day, hour=hour, minute=minute, second=second)
    return Field(v, t, la1, lon1, di)


def coarsen(v: np.ndarray, f: int = COARSEN) -> np.ndarray:
    """Mean over f x f blocks; a block with any NaN is NaN (no partial coverage)."""
    nj, ni = (v.shape[0] // f) * f, (v.shape[1] // f) * f
    return v[:nj, :ni].reshape(nj // f, f, ni // f, f).mean(axis=(1, 3))


@dataclass(frozen=True)
class Tile:
    """A CONTEXT x CONTEXT box of the coarsened grid; row 0 is the north edge."""

    key: str
    row0: int
    col0: int
    station_rc: tuple[int, int]  # the station's pixel inside the box

    @property
    def target(self) -> tuple[slice, slice]:
        """The scored central TARGET x TARGET pixels, as slices into the box."""
        a = (CONTEXT - TARGET) // 2
        return slice(a, a + TARGET), slice(a, a + TARGET)

    def latlon(self, r: int, c: int) -> tuple[float, float]:
        s = STEP * COARSEN
        lat = LAT0 - (STEP / 2) * (COARSEN - 1) - (self.row0 + r) * s
        lon = LON0 + (STEP / 2) * (COARSEN - 1) + (self.col0 + c) * s
        return lat, lon


def tile_for(key: str, lat: float, lon: float) -> Tile:
    s = STEP * COARSEN
    r = int(round((LAT0 - lat) / s))
    c = int(round((lon - LON0) / s))
    nr, nc = NJ // COARSEN, NI // COARSEN
    row0 = min(max(r - CONTEXT // 2, 0), nr - CONTEXT)
    col0 = min(max(c - CONTEXT // 2, 0), nc - CONTEXT)
    return Tile(key, row0, col0, (r - row0, c - col0))


def tiles(stations: dict) -> list[Tile]:
    """One tile per station (forward/stations.py STATIONS, or any {key: obj with lat, lon})."""
    return [tile_for(k, s.lat, s.lon) for k, s in stations.items()]


def cut(field: np.ndarray, ts: list[Tile]) -> np.ndarray:
    """[tile, CONTEXT, CONTEXT] boxes from a native [NJ, NI] field."""
    g = coarsen(field)
    return np.stack([g[t.row0 : t.row0 + CONTEXT, t.col0 : t.col0 + CONTEXT] for t in ts])


# Tiles are stored as uint16 tenths of mm/h, MISSING for NaN: the rate's own GRIB2 precision.
SCALE = 10.0
MISSING = np.uint16(65535)


def pack(x: np.ndarray) -> np.ndarray:
    q = np.where(np.isfinite(x), np.round(np.nan_to_num(x) * SCALE), MISSING)
    return np.clip(q, 0, MISSING).astype(np.uint16)


def unpack(q: np.ndarray) -> np.ndarray:
    x = q.astype(np.float32) / np.float32(SCALE)
    x[q == MISSING] = np.nan
    return x
