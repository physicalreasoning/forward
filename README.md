# Ledger

Model forecasts captured live at each read (20:00 UTC, the day before the target day). The commit time is the evidence that the inputs predate the outcome. Written by scripts/capture.py on main; never edited by hand.

## Data and attribution

The values here are derived (maximum over the station's local day of hourly 2 m temperature) from
[Weather data by Open-Meteo.com](https://open-meteo.com/), licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Upstream models: ECMWF AIFS and IFS
(Copyright © 2024-2026 European Centre for Medium-Range Weather Forecasts (ECMWF). Source:
www.ecmwf.int. Licence: CC BY 4.0. ECMWF does not accept any liability for the accuracy or
completeness of the data, for any errors, or for any direct or indirect consequences of using it),
DWD ICON (CC BY 4.0), NOAA GFS and NBM (public domain). The `isotherm` blocks hold isotherm's own
probabilities (github.com/physicalreasoning/isotherm); Kalshi's quotes are not stored here.
