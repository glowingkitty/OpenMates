"""Unit tests for the health appointment search skill.

These tests cover deterministic quality filters and provider-normalization
contracts without live Doctolib or Jameda calls. The live provider APIs are
covered separately by CLI/API smoke tests; this file guards local filtering
logic that should never regress because of German city spelling variants.
"""

from __future__ import annotations

from backend.apps.health.skills.search_appointments_skill import (
    _cities_match,
    _matches_motive_category,
    _matches_procedure_intent,
    _matches_speciality_intent,
    _select_jameda_services_for_request,
)


def test_jameda_city_matching_accepts_umlaut_city_names() -> None:
    """Jameda returns display cities while requests use URL slug city names."""

    assert _cities_match("Köln", "koeln") is True
    assert _cities_match("München", "muenchen") is True
    assert _cities_match("Düsseldorf", "duesseldorf") is True
    assert _cities_match("Nürnberg", "nuernberg") is True


def test_jameda_city_matching_rejects_different_cities() -> None:
    assert _cities_match("Berlin", "hamburg") is False
    assert _cities_match("Köln", "bonn") is False
    assert _cities_match("", "koeln") is False


def test_procedure_filter_rejects_wrong_radiology_modality() -> None:
    assert _matches_procedure_intent("ct", "CT Oberbauch") is True
    assert _matches_procedure_intent("ct", "MRT Kniegelenk") is False
    assert _matches_procedure_intent("mrt", "MRT Kopf / Schädel") is True
    assert _matches_procedure_intent("mrt", "CT NNH nativ") is False


def test_motive_category_filter_handles_negation_and_overbroad_speech_hours() -> None:
    assert _matches_motive_category("Hautkrebsvorsorge", "checkup") is True
    assert _matches_motive_category("Privatsprechstunde (nicht Hautkrebsvorsorge)", "checkup") is False
    assert _matches_motive_category("Allgemeine Sprechstunde", "general") is True
    assert _matches_motive_category("Schnarchsprechstunde", "general") is False


def test_speciality_guard_rejects_obvious_cross_speciality_results() -> None:
    assert _matches_speciality_intent("kinderarzt", "Kinder- und Jugendarzt", "Praxis") is True
    assert _matches_speciality_intent("kinderarzt", "Zahnärztin", "Dr. Danja Dosch") is False
    assert _matches_speciality_intent("hno", "Hals-Nasen-Ohren-Arzt", "Praxis") is True


def test_jameda_service_selection_uses_calendar_service_ids() -> None:
    services = [
        {"addressServiceId": 1, "itemServiceName": "MRT Kniegelenk", "insuranceProviderId": 1},
        {"addressServiceId": 2, "itemServiceName": "CT Abdomen", "insuranceProviderId": 1},
    ]

    selected = _select_jameda_services_for_request(
        services,
        speciality_raw="ct",
        visit_motive_category=None,
        insurance_sector="public",
    )

    assert [svc["addressServiceId"] for svc in selected] == [2]
