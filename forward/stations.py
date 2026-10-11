"""The 19 settlement stations of Kalshi's daily-high ladders: the first task's sites.

Truth is the NWS Daily Climatological Report (CLI) high, which is also what the Kalshi ladders
settle on, so every entry and the market are scored against the same number.
"""

from __future__ import annotations

from dataclasses import dataclass

from isotherm.weather import ALL_CITIES

# Station coordinates (IEM station metadata, as in isotherm's data/corpus_stations.json).
COORDS = {
    "KNYC": (40.779, -73.9693),
    "KMDW": (41.786, -87.7524),
    "KMIA": (25.7881, -80.3169),
    "KAUS": (30.1945, -97.6699),
    "KLAX": (33.9382, -118.3865),
    "KDEN": (39.8328, -104.6575),
    "KPHL": (39.8683, -75.2311),
    "KATL": (33.6301, -84.4418),
    "KBOS": (42.3606, -71.0097),
    "KDFW": (32.8968, -97.038),
    "KDCA": (38.8472, -77.0346),
    "KLAS": (36.0801, -115.1523),
    "KMSP": (44.8854, -93.2313),
    "KMSY": (29.9933, -90.2511),
    "KOKC": (35.3889, -97.6006),
    "KPHX": (33.4343, -112.0116),
    "KSAT": (29.5337, -98.4698),
    "KSEA": (47.4447, -122.3144),
    "KSFO": (37.619, -122.3749),
}


@dataclass(frozen=True)
class Station:
    key: str  # isotherm city key, e.g. NY
    icao: str  # CLI station, e.g. KNYC
    tz: str
    lat: float
    lon: float
    series: str  # Kalshi daily-high series


STATIONS = {k: Station(k, c.station, c.tz, *COORDS[c.station], c.series) for k, c in ALL_CITIES.items()}
