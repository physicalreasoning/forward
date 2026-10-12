"""isotherm as a live ladder entry: the probabilities it serves for each Kalshi ladder at the read.

isotherm (github.com/physicalreasoning/isotherm) is a calibrated model of Kalshi's daily-high
ladders, served free at https://isotherm.onrender.com. It answers with one probability per
ladder bucket, not a distribution over the integer high, so it is a ladder entry: scored on the
ladder columns only (log score against the market, taker P&L) and absent from the integer-grid
columns (`forward/registry.py`).

The service covers 7 of the 19 stations (NY, CHI, MIA, AUS, LAX, DEN, PHIL; `GET /health` lists
them). At each read `scripts/capture.py` calls `GET /health`, then `GET /ladder/{city}?day=D` for
every covered station, then `GET /health` again, and stores the responses under the ledger file's
"isotherm" key, with each bucket's market fields removed (`public`). A stored ladder counts only if

- it was fetched before 22:00 UTC on D-1, the rule every captured input follows
  (`forward/ledger.py`), and
- /health reported MODEL_HASH both before and after the calls: the model this round entered.
  A redeployed model is a different entry, so its answers are dropped, not scored.

Free hosting sleeps after 15 idle minutes and the first request can take a minute, hence the
long timeouts and retries.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request

NAME = "isotherm"
URL = "https://isotherm.onrender.com"
MODEL_HASH = "b200c51ce4ee"  # FINDINGS §9's frozen strategy, fit before 2026-06-29
TIMEOUT = 90  # seconds per request; a cold start takes up to about 60
RETRIES = 4
DEADLINE = 15 * 60  # stop calling after this many seconds, well inside the 22:00 UTC limit


# Kalshi's quotes are not ours to republish (docs/DATA_TERMS.md), and the ledger is public: each
# stored bucket keeps isotherm's own numbers and the bucket's definition, never the market's.
KEEP = ("ticker", "lo", "hi", "p_forecast", "p_model")


def public(response: dict) -> dict:
    """The response with each bucket's market fields (bid, ask, p_market) removed."""
    out = dict(response)
    out["buckets"] = [{k: b.get(k) for k in KEEP} for b in response.get("buckets", [])]
    return out


class Unavailable(Exception):
    """The service answered, but has no ladder for this city-day (HTTP 404 or 409)."""


def _get(path: str, params: dict | None = None, retries: int = RETRIES) -> dict:
    q = URL + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for i in range(retries):
        try:
            with urllib.request.urlopen(q, timeout=TIMEOUT) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as ex:
            if ex.code in (404, 409, 422):  # a clear answer: retrying will not change it
                raise Unavailable(f"HTTP {ex.code}: {ex.read()[:200].decode(errors='replace')}") from ex
            if i == retries - 1:
                raise
        except Exception:
            if i == retries - 1:
                raise
        time.sleep(5 * 2**i)
    raise RuntimeError("unreachable")


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def capture(days: dict[str, str], get=_get, now=_now, clock=time.monotonic) -> dict:
    """Call the service for each station's target day; the ledger block, market fields removed.

    days: station key (isotherm's city key) -> target day, YYYY-MM-DD. Stations the service
    does not cover are left out: absent, not errors.
    """
    start = clock()
    block: dict = {"url": URL}
    try:
        block["health"] = get("/health")
    except Exception as ex:  # noqa: BLE001 (record and move on; the other inputs must still land)
        block["health"] = {"error": str(ex)[:200]}
        block["rows"] = []
        return block
    covered = set(block["health"].get("cities", []))
    rows = []
    for st, day in days.items():
        if st not in covered:
            continue
        if clock() - start > DEADLINE:
            rows.append({"station": st, "day": day, "error": "deadline"})
            continue
        try:
            r = get(f"/ladder/{st}", {"day": day})
            rows.append({"station": st, "day": day, "fetched_at": now(), "response": public(r)})
        except Exception as ex:  # noqa: BLE001 (one city failing must not lose the rest)
            rows.append({"station": st, "day": day, "fetched_at": now(), "error": str(ex)[:200]})
    block["rows"] = rows
    try:
        block["health_after"] = get("/health")
    except Exception as ex:  # noqa: BLE001
        block["health_after"] = {"error": str(ex)[:200]}
    return block


def accept(block: dict) -> bool:
    """The block was served by the entered model, by /health before and after the calls."""
    return all(block.get(k, {}).get("model_hash") == MODEL_HASH for k in ("health", "health_after"))


def probs(row: dict) -> dict[str, float] | None:
    """{bucket ticker: isotherm's probability} from one stored ladder; None if unusable."""
    r = row.get("response") or {}
    if r.get("city") != row["station"] or r.get("day") != row["day"]:
        return None
    out = {b["ticker"]: b.get("p_model") for b in r.get("buckets", [])}
    if not out or any(p is None for p in out.values()):
        return None
    return {t: float(p) for t, p in out.items()}
