# forward: world-model track ledger

One manifest per read (20:00 UTC) in `wm/YYYY-MM-DD.json`: when the capture ran, each
ensemble's run initialisation and availability times, and the sha256 of the day's trajectories.
The trajectories themselves (`wm-YYYY-MM-DD.parquet`, every member's hourly 2 m temperature and
precipitation for 7 days at the 19 stations) are assets of the
[`wm-ledger` release](https://github.com/physicalreasoning/forward/releases/tag/wm-ledger).

A commit here is the proof that a capture existed before the outcomes it is scored on; check an
asset with `sha256sum` against its manifest. Written by `scripts/capture_wm.py` on `main`.
Source: [Open-Meteo Ensemble API](https://open-meteo.com/en/docs/ensemble-api) (CC BY 4.0).
