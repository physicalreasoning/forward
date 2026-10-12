import pytest

from forward import isotherm_live as iso

HEALTH = {"status": "ok", "model_hash": iso.MODEL_HASH, "cities": ["NY", "CHI"]}


def ladder(city="NY", day="2026-11-02", p=(0.2, 0.5, 0.3)):
    tick = [f"KXHIGH{city}-26NOV02-T60", f"KXHIGH{city}-26NOV02-B61.5", f"KXHIGH{city}-26NOV02-T62"]
    edges = [(None, 60.5), (60.5, 62.5), (62.5, None)]
    return {
        "city": city,
        "day": day,
        "event": f"KXHIGH{city}-26NOV02",
        "buckets": [
            {"ticker": t, "lo": lo, "hi": hi, "bid": 0.1, "ask": 0.2, "p_market": 0.3, "p_model": pi}
            for t, (lo, hi), pi in zip(tick, edges, p, strict=True)
        ],
    }


def fake_get(fail=()):
    calls = []

    def get(path, params=None):
        calls.append(path)
        if path == "/health":
            return HEALTH
        city = path.rsplit("/", 1)[1]
        if city in fail:
            raise iso.Unavailable("HTTP 409: no_ladder")
        return ladder(city, params["day"])

    return get, calls


def test_capture_calls_only_covered_cities_and_stores_responses_as_returned():
    get, calls = fake_get()
    days = {"NY": "2026-11-02", "CHI": "2026-11-02", "SEA": "2026-11-02"}
    b = iso.capture(days, get=get, now=lambda: "2026-11-01T20:01:00+00:00")
    assert calls == ["/health", "/ladder/NY", "/ladder/CHI", "/health"]
    assert [r["station"] for r in b["rows"]] == ["NY", "CHI"]  # SEA is not covered: absent
    assert b["rows"][0]["response"] == ladder("NY")
    assert b["health"] == b["health_after"] == HEALTH
    assert iso.accept(b)


def test_one_city_failing_keeps_the_rest():
    get, _ = fake_get(fail=("NY",))
    b = iso.capture({"NY": "2026-11-02", "CHI": "2026-11-02"}, get=get, now=lambda: "t")
    assert "409" in b["rows"][0]["error"] and "response" in b["rows"][1]


def test_service_down_records_an_error_block():
    def down(path, params=None):
        raise TimeoutError("timed out")

    b = iso.capture({"NY": "2026-11-02"}, get=down)
    assert b["rows"] == [] and "timed out" in b["health"]["error"]
    assert not iso.accept(b)


def test_deadline_stops_calling():
    get, calls = fake_get()
    t = iter([0, iso.DEADLINE + 1, iso.DEADLINE + 2])
    b = iso.capture(
        {"NY": "2026-11-02", "CHI": "2026-11-02"}, get=get, now=lambda: "t", clock=lambda: next(t)
    )
    assert calls == ["/health", "/health"]
    assert b["rows"][0]["error"] == "deadline"


@pytest.mark.parametrize("which", ["health", "health_after"])
def test_a_different_served_model_is_not_accepted(which):
    b = {"health": HEALTH, "health_after": HEALTH} | {which: HEALTH | {"model_hash": "000000000000"}}
    assert not iso.accept(b)


def test_probs_by_ticker():
    row = {"station": "NY", "day": "2026-11-02", "response": ladder()}
    p = iso.probs(row)
    assert list(p.values()) == [0.2, 0.5, 0.3]
    assert next(iter(p)).startswith("KXHIGHNY-26NOV02")


def test_probs_refuses_a_mismatched_or_incomplete_answer():
    assert iso.probs({"station": "CHI", "day": "2026-11-02", "response": ladder("NY")}) is None
    assert iso.probs({"station": "NY", "day": "2026-11-03", "response": ladder("NY")}) is None
    bad = ladder()
    bad["buckets"][1]["p_model"] = None
    assert iso.probs({"station": "NY", "day": "2026-11-02", "response": bad}) is None
