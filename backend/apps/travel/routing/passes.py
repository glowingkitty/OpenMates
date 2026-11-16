"""Owned travel passes and the conservative rule for when a pass covers a segment.

A pass covers a segment only when the provider marks it as covered, or when the
segment's product class is one the pass covers and both of its ends lie inside
the pass area. Unknown product class or country means not covered, never free.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence

# Stable OpenMates product classes (same values as the request's rail_products).
LOCAL_CLASSES: FrozenSet[str] = frozenset({"regional_express", "regional", "s_bahn", "subway", "tram", "local_bus"})
ALL_RAIL_CLASSES: FrozenSet[str] = LOCAL_CLASSES | {"high_speed", "intercity"}


@dataclass(frozen=True)
class TravelPass:
    pass_id: str
    label: str
    countries: FrozenSet[str]
    classes: FrozenSet[str]
    aliases: FrozenSet[str]

    @property
    def search_rail_products(self) -> List[str]:
        """Rail product filter for a search restricted to what the pass covers."""
        return sorted(product for product in self.classes if product != "local_bus")


PASSES: Dict[str, TravelPass] = {
    travel_pass.pass_id: travel_pass for travel_pass in (
        TravelPass("deutschland_ticket", "Deutschland-Ticket", frozenset({"DE"}), LOCAL_CLASSES,
                   frozenset({"deutschlandticket", "deutschland ticket", "d-ticket", "d ticket", "49 euro ticket",
                              "58 euro ticket", "germany ticket"})),
        TravelPass("klimaticket_oesterreich", "KlimaTicket Österreich", frozenset({"AT"}), ALL_RAIL_CLASSES,
                   frozenset({"klimaticket", "klimaticket ö", "klimaticket austria", "klimaticket oe"})),
        TravelPass("swiss_ga", "Swiss GA travelcard", frozenset({"CH", "LI"}), ALL_RAIL_CLASSES,
                   frozenset({"ga", "generalabonnement", "ga travelcard", "swiss travel pass"})),
    )
}


def _normalize(value: str) -> str:
    return " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())


def resolve_passes(values: Iterable[Any]) -> List[TravelPass]:
    """Known passes named by id, label or alias; unknown names are ignored."""
    lookup: Dict[str, TravelPass] = {}
    for travel_pass in PASSES.values():
        for name in (travel_pass.pass_id, travel_pass.label, *travel_pass.aliases):
            lookup[_normalize(name)] = travel_pass
    found = [lookup[key] for value in values if isinstance(value, str) and (key := _normalize(value)) in lookup]
    return list(dict.fromkeys(found))


def _provider_marks_pass(segment: Mapping[str, Any], travel_pass: TravelPass) -> bool:
    coverage = segment.get("fare_coverage")
    if not isinstance(coverage, str):
        return False
    value = coverage.strip().casefold()
    return value in {f"pass:{travel_pass.pass_id}", "pass_only"} or (
        value in {"pass", "covered"} and travel_pass.pass_id in (segment.get("covered_by_passes") or []))


def segment_covered_by(segment: Mapping[str, Any], travel_pass: TravelPass) -> bool:
    if _provider_marks_pass(segment, travel_pass):
        return True
    product_class = segment.get("product_class")
    countries = (segment.get("departure_country_code"), segment.get("arrival_country_code"))
    return (isinstance(product_class, str) and product_class in travel_pass.classes
            and all(isinstance(code, str) and code.upper() in travel_pass.countries for code in countries))


def covering_pass(segments: Sequence[Mapping[str, Any]], passes: Sequence[TravelPass]) -> Optional[TravelPass]:
    """The first owned pass covering every segment, else None."""
    if not segments:
        return None
    return next((p for p in passes if all(segment_covered_by(segment, p) for segment in segments)), None)
