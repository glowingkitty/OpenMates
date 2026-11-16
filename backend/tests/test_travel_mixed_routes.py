"""Mixed travel routes for owned passes: coverage, hubs, transfers, composition, ranking, bounds.

Results follow the generic connection contract of operator-installed providers;
provider ids are synthetic. The delegate test runs the installed-provider skill
for travel.search_connections with a faked runner.
"""
from __future__ import annotations

import asyncio

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from backend.apps.travel.routing import planner
from backend.apps.travel.routing.compose import (
    PASS_THEN_PAID,
    annotate_savings,
    compose_routes,
    effective_price,
    prune_composed,
    rank_results,
    transfer_minutes_needed,
)
from backend.apps.travel.routing.hubs import GeoPoint, select_hubs
from backend.apps.travel.routing.passes import PASSES, covering_pass, resolve_passes
from backend.shared.app_packages import delegate_skill, loader, provider_dispatch
from backend.shared.app_packages.delegate_skill import InstalledProviderSkill
from backend.shared.app_packages.generic_contract import SKILL_REQUESTS_V1
from backend.shared.app_packages.runner_client import RunnerResult
from backend.tests.app_packages_test_support import enable, manifest, write_package, write_registry

D_TICKET = PASSES["deutschland_ticket"]
MUNICH = GeoPoint(48.1402, 11.5600, "DE")
ZURICH = GeoPoint(47.3779, 8.5403, "CH")
DATE = "2026-11-23"


def _segment(origin: str, destination: str, dep: str, arr: str, *, product: Optional[str] = "regional",
             mode: str = "train", countries: tuple = ("DE", "DE"), coords: tuple = (None, None, None, None),
             **extra: Any) -> Dict[str, Any]:
    return {
        "carrier": "Example rail", "carrier_code": "RE", "mode": mode, "product_class": product,
        "departure_station": origin, "arrival_station": destination,
        "departure_time": f"{DATE}T{dep}:00+01:00", "arrival_time": f"{DATE}T{arr}:00+01:00",
        "departure_country_code": countries[0], "arrival_country_code": countries[1],
        "departure_latitude": coords[0], "departure_longitude": coords[1],
        "arrival_latitude": coords[2], "arrival_longitude": coords[3], **extra,
    }


def _result(segments: List[Dict[str, Any]], *, price: Optional[str] = None, provider: str = "my_provider",
            method: str = "train", **extra: Any) -> Dict[str, Any]:
    first, last = segments[0], segments[-1]
    return {
        "type": "connection", "transport_method": method, "source_provider": provider, "provider_id": provider,
        "total_price": price, "currency": "EUR" if price else None,
        "origin": first["departure_station"], "destination": last["arrival_station"],
        "departure": first["departure_time"], "arrival": last["arrival_time"],
        "hash": f"{provider}-{first['departure_time']}-{last['arrival_time']}-{price}",
        "booking_url": f"https://example.org/book/{provider}", "booking_provider": "Example tickets",
        "legs": [{"origin": first["departure_station"], "destination": last["arrival_station"],
                  "departure": first["departure_time"], "arrival": last["arrival_time"],
                  "segments": segments, "layovers": None}],
        **extra,
    }


def _regional(dep: str = "07:53", arr: str = "10:41") -> Dict[str, Any]:
    return _result([_segment("Munich Hbf", "Lindau-Reutin", dep, arr)])


def _bus(origin: str, dep: str, arr: str, price: str) -> Dict[str, Any]:
    return _result([_segment(origin, "Zurich", dep, arr, product="long_distance_bus", mode="bus",
                             countries=(None, None))], price=price, provider="my_other_provider", method="bus")


# --------------------------------------------------------------------------- passes


# contract-test: direct surface=rest_api assertions=travel-search.mixed-routes.pass-coverage-conservative
def test_pass_covers_only_regional_segments_inside_its_area() -> None:
    assert resolve_passes(["Deutschlandticket", "unknown pass"]) == [D_TICKET]
    assert covering_pass([_segment("Munich Hbf", "Lindau-Reutin", "07:00", "09:00")], [D_TICKET]) is D_TICKET
    eurocity = _segment("Munich Hbf", "Lindau-Reutin", "06:48", "08:50", product="intercity")
    assert covering_pass([eurocity], [D_TICKET]) is None
    abroad = _segment("Lindau-Reutin", "Bregenz", "09:00", "09:20", countries=("DE", "AT"))
    assert covering_pass([abroad], [D_TICKET]) is None
    unknown = _segment("Munich Hbf", "Lindau-Reutin", "07:00", "09:00", product=None)
    assert covering_pass([unknown], [D_TICKET]) is None
    marked = _segment("A", "B", "07:00", "08:00", product=None, fare_coverage="pass:deutschland_ticket")
    assert covering_pass([marked], [D_TICKET]) is D_TICKET


# --------------------------------------------------------------------------- hubs


# contract-test: direct surface=rest_api assertions=travel-search.mixed-routes.pass-hub-composition
def test_hubs_follow_the_trip_with_bounded_detour() -> None:
    names = [hub.name for hub in select_hubs(MUNICH, ZURICH, D_TICKET.countries)]
    assert "Lindau (Bodensee)" in names and len(names) <= 3
    assert all(name not in {"Hamburg", "Berlin", "Zurich"} for name in names)
    assert select_hubs(MUNICH, GeoPoint(48.15, 11.6, "AT"), D_TICKET.countries) == []


# --------------------------------------------------------------------------- transfers


# contract-test: direct surface=rest_api assertions=travel-search.mixed-routes.transfer-buffer
def test_transfer_buffer_grows_for_stop_or_mode_changes() -> None:
    train = _segment("Munich Hbf", "Lindau-Reutin", "07:53", "10:41")
    same_station = _segment("Lindau-Reutin", "Zurich", "11:10", "13:00", product="intercity")
    bus = _bus("Lindau (Blaukreuzstrasse)", "11:45", "14:10", "8.98")["legs"][0]["segments"][0]
    assert transfer_minutes_needed(train, same_station, 10) == 20
    assert transfer_minutes_needed(train, same_station, 30) == 30
    assert transfer_minutes_needed(train, bus, 10) == 45


# contract-test: direct surface=rest_api assertions=travel-search.mixed-routes.transfer-buffer,travel-search.mixed-routes.per-ticket-display
def test_composition_keeps_only_reachable_departures_and_lists_tickets() -> None:
    routes = compose_routes(
        [_regional()],
        [_bus("Lindau (Blaukreuzstrasse)", "11:00", "13:25", "7.99"),
         _bus("Lindau (Blaukreuzstrasse)", "11:45", "14:10", "8.98")],
        PASS_THEN_PAID, [D_TICKET], "Lindau", 10,
    )
    assert len(routes) == 1
    route = routes[0]
    assert route["departure"].endswith("07:53:00+01:00") and route["arrival"].endswith("14:10:00+01:00")
    assert route["total_price"] == "8.98" and route["fare"]["is_partial"] is True
    composition = route["route_composition"]
    assert composition["separate_tickets"] is True and composition["transfer_minutes"] == 64
    first, second = route["tickets"]
    assert first["coverage"] == "pass" and first["pass_label"] == "Deutschland-Ticket" and first["price"] is None
    assert first["route"] == "Munich Hbf -> Lindau-Reutin"
    assert second["coverage"] == "paid" and second["price"] == 8.98 and second["booking_url"]
    hub = route["legs"][0]["layovers"][0]
    assert hub["station_change"] == {"from": "Lindau-Reutin", "to": "Lindau (Blaukreuzstrasse)"}
    assert [s["fare_coverage"] for s in route["legs"][0]["segments"]] == ["pass:deutschland_ticket", "paid"]


# --------------------------------------------------------------------------- ranking


# contract-test: direct surface=rest_api assertions=travel-search.mixed-routes.total-price-ranking
def test_ranking_by_amount_paid_and_savings_against_cheapest_direct() -> None:
    direct = _bus("Munich central bus station", "08:20", "13:25", "18.98")
    unknown = _result([_segment("Munich Hbf", "Zurich HB", "07:30", "11:00", product="intercity",
                                countries=("DE", "CH"))])
    regional_only = _regional("06:00", "09:00")
    composed = compose_routes([_regional()], [_bus("Lindau (Blaukreuzstrasse)", "11:45", "14:10", "8.98")],
                              PASS_THEN_PAID, [D_TICKET], "Lindau", 10)[0]
    results = [unknown, direct, composed, regional_only]
    annotate_savings(results, [D_TICKET])
    ranked = rank_results(results, [D_TICKET])
    assert effective_price(regional_only, [D_TICKET]) == 0.0
    assert [effective_price(r, [D_TICKET]) for r in ranked] == [0.0, 8.98, 18.98, None]
    savings = composed["route_composition"]["savings"]
    assert savings["amount"] == 10.0 and savings["compared_to"]["price"] == 18.98


# contract-test: direct surface=rest_api assertions=travel-search.mixed-routes.pass-hub-composition
def test_composed_routes_beaten_on_price_and_duration_are_dropped() -> None:
    composed = compose_routes([_regional()], [_bus("Lindau (Blaukreuzstrasse)", "11:45", "14:10", "8.98")],
                              PASS_THEN_PAID, [D_TICKET], "Lindau (Bodensee)", 10)
    cheaper_and_faster = _bus("Munich central bus station", "08:20", "12:00", "7.50")
    dearer = _bus("Munich central bus station", "08:20", "13:25", "18.98")
    assert prune_composed(composed, [cheaper_and_faster], [D_TICKET]) == []
    assert prune_composed(composed, [dearer], [D_TICKET]) == composed


# --------------------------------------------------------------------------- planner bounds


class _FakeCache:
    def __init__(self) -> None:
        self.data: Dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.data.get(key)

    async def set(self, key: str, value: Any, ttl: int = 0) -> None:
        self.data[key] = value


def _fake_search(calls: List[Dict[str, Any]]):
    async def search(item: Dict[str, Any]) -> List[Dict[str, Any]]:
        calls.append(item)
        leg = item["legs"][0]
        if item.get("rail_products"):
            return [_regional()] if leg["destination"].startswith("Lindau") else []
        if leg["origin"].startswith("Lindau"):
            return [_bus("Lindau (Blaukreuzstrasse)", "11:45", "14:10", "8.98")]
        return []
    return search


def _direct_group() -> Dict[str, Any]:
    direct = _bus("Munich central bus station", "08:20", "13:25", "18.98")
    segment = direct["legs"][0]["segments"][0]
    segment.update({"departure_latitude": MUNICH.latitude, "departure_longitude": MUNICH.longitude,
                    "departure_country_code": "DE", "arrival_latitude": ZURICH.latitude,
                    "arrival_longitude": ZURICH.longitude, "arrival_country_code": "CH"})
    return {"id": 1, "results": [direct], "providers": ["my_other_provider"]}


REQUEST = {"origin": "Munich", "destination": "Zurich", "date": DATE, "transport_methods": ["train", "bus"],
           "owned_passes": ["deutschland_ticket"], "min_transfer_minutes": 10}


# contract-test: direct surface=rest_api assertions=travel-search.mixed-routes.provider-neutral-and-bounded,travel-search.mixed-routes.pass-hub-composition
@pytest.mark.asyncio
async def test_planner_composes_through_hubs_within_bounds_and_reuses_searches() -> None:
    calls: List[Dict[str, Any]] = []
    cache = _FakeCache()
    group = _direct_group()
    await planner.plan_mixed_routes(group, dict(REQUEST), _fake_search(calls), cache_service=cache)
    hubs = group["mixed_routes"]["hubs"]
    assert 1 <= len(hubs) <= 3 and len(calls) <= 2 * len(hubs)
    first = group["results"][0]
    assert first["route_composition"]["hub"] == "Lindau (Bodensee)" and first["total_price"] == "8.98"
    assert group["results"][1]["total_price"] == "18.98"
    covered_item = next(item for item in calls if item.get("rail_products"))
    assert covered_item["countries"] == ["DE"] and "intercity" not in covered_item["rail_products"]

    again: List[Dict[str, Any]] = []
    await planner.plan_mixed_routes(_direct_group(), dict(REQUEST), _fake_search(again), cache_service=cache)
    assert again == []


# contract-test: direct surface=rest_api assertions=travel-search.mixed-routes.pass-hub-composition
@pytest.mark.asyncio
async def test_planner_ignores_parts_that_resolved_to_a_place_far_from_the_hub() -> None:
    async def search(item: Dict[str, Any]) -> List[Dict[str, Any]]:
        leg = item["legs"][0]
        if item.get("rail_products"):
            wrong_place = _result([_segment("Munich Hbf", "Lindau village", "07:53", "10:41",
                                            coords=(48.14, 11.56, 48.85, 15.5))])
            return [wrong_place] if leg["destination"].startswith("Lindau") else []
        return [_bus("Lindau (Blaukreuzstrasse)", "11:45", "14:10", "8.98")] if leg["origin"].startswith("Lindau") else []

    group = _direct_group()
    await planner.plan_mixed_routes(group, dict(REQUEST), search)
    assert group["mixed_routes"]["composed"] == 0
    assert not any(result.get("route_composition") for result in group["results"])


# contract-test: direct surface=rest_api assertions=travel-search.mixed-routes.provider-neutral-and-bounded
@pytest.mark.asyncio
async def test_slow_hub_searches_stop_at_the_budget_and_keep_the_direct_results(monkeypatch) -> None:
    monkeypatch.setattr(planner, "COMPOSE_BUDGET_SECONDS", 0.05)

    async def slow(_item: Dict[str, Any]) -> List[Dict[str, Any]]:
        await asyncio.sleep(5)
        return []

    group = _direct_group()
    await planner.plan_mixed_routes(group, dict(REQUEST), slow)
    assert group["mixed_routes"]["timed_out"] is True and group["mixed_routes"]["composed"] == 0
    assert [result["total_price"] for result in group["results"]] == ["18.98"]


# contract-test: direct surface=rest_api assertions=travel-search.mixed-routes.provider-neutral-and-bounded
def test_connection_searches_with_an_owned_pass_get_room_for_hub_searches() -> None:
    from backend.apps.ai.processing.skill_executor import DEFAULT_SKILL_TIMEOUT, get_skill_timeout

    with_pass = {"requests": [{**REQUEST}]}
    assert get_skill_timeout("travel", "search_connections", with_pass) == 60.0
    assert get_skill_timeout("travel", "search_connections", {"requests": [{**REQUEST, "owned_passes": []}]}) \
        == DEFAULT_SKILL_TIMEOUT
    # The skill timeout leaves room for the providers' first answer before the hub budget.
    assert planner.COMPOSE_BUDGET_SECONDS <= 60.0 - 25.0


# contract-test: direct surface=rest_api assertions=travel-search.mixed-routes.provider-neutral-and-bounded
@pytest.mark.asyncio
async def test_planner_without_owned_pass_changes_nothing() -> None:
    calls: List[Dict[str, Any]] = []
    group = _direct_group()
    before = [dict(result) for result in group["results"]]
    await planner.plan_mixed_routes(group, {**REQUEST, "owned_passes": []}, _fake_search(calls))
    assert calls == [] and group["results"] == before and "mixed_routes" not in group


# --------------------------------------------------------------------------- delegate hook


@pytest.fixture
def travel_providers(monkeypatch, tmp_path):
    entries = [{"app": "travel", "skill": "search_connections", "contract": SKILL_REQUESTS_V1, "id": pid,
                "name": name, "runtime": "executable", "entrypoint": "bin/provider"}
               for pid, name in (("my_provider", "Example rail"), ("my_other_provider", "Example coach"))]
    sha = write_package(tmp_path, manifest(package_id="my.package", providers=entries), package_id="my.package")
    write_registry(tmp_path, {"my.package": {"version": "1.0.0", "sha256": sha}})
    enable(monkeypatch, tmp_path)
    loader.reset_installed_packages_cache()
    delegate_skill.resolve_original_skill_models.cache_clear()
    yield
    loader.reset_installed_packages_cache()


def _travel_delegate() -> InstalledProviderSkill:
    skill = object.__new__(InstalledProviderSkill)
    skill.app_id, skill.skill_id = "travel", "search_connections"
    skill.app = SimpleNamespace(get_skill_by_id=lambda _sid: SimpleNamespace(
        delegated_class_path="backend.apps.travel.skills.search_connections.SearchConnectionsSkill"))
    return skill


# contract-test: direct surface=rest_api assertions=travel-search.mixed-routes.pass-hub-composition,travel-search.mixed-routes.provider-neutral-and-bounded
@pytest.mark.asyncio
async def test_installed_provider_search_adds_mixed_routes(monkeypatch, travel_providers) -> None:
    calls: List[Dict[str, Any]] = []
    direct_group = _direct_group()["results"]

    async def fake_run_provider(provider, input_item, secrets, **_kwargs):
        calls.append({"provider": provider.provider_id, "input": input_item})
        if provider.provider_id != "my_other_provider":
            if input_item.get("rail_products") and input_item["legs"][0]["destination"].startswith("Lindau"):
                return RunnerResult(ok=True, results=[_regional()])
            return RunnerResult(ok=True, results=[])
        leg = (input_item.get("legs") or [{}])[0]
        if str(leg.get("origin")).startswith("Lindau"):
            return RunnerResult(ok=True, results=[_bus("Lindau (Blaukreuzstrasse)", "11:45", "14:10", "8.98")])
        return RunnerResult(ok=True, results=[{k: v for k, v in r.items() if k != "provider_id"} for r in direct_group]
                            if "legs" not in input_item or leg.get("origin") == "Munich" else [])

    async def no_cache_refiner(group, contract_input, search, secrets_manager=None):
        await planner.plan_mixed_routes(group, contract_input, search, cache_service=None)

    monkeypatch.setattr(provider_dispatch, "run_provider", fake_run_provider)
    models = delegate_skill.resolve_original_skill_models(
        "backend.apps.travel.skills.search_connections.SearchConnectionsSkill")
    assert models.group_refiner is not None
    monkeypatch.setattr(delegate_skill, "resolve_original_skill_models",
                        lambda _path: delegate_skill.OriginalSkillModels(
                            item_model=models.item_model, response_defaults=models.response_defaults,
                            provider_objects=models.provider_objects, group_refiner=no_cache_refiner))

    response = await _travel_delegate().execute([dict(REQUEST)])
    group = response["results"][0]
    composed = [r for r in group["results"] if r.get("route_composition")]
    assert composed and composed[0]["tickets"][0]["coverage"] == "pass"
    assert group["results"][0] is composed[0]

    named = await _travel_delegate().execute([{**REQUEST, "providers": ["my_other_provider"]}])
    assert not any(r.get("route_composition") for r in named["results"][0]["results"])
