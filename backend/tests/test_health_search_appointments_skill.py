"""Unit tests for the health appointment search skill.

These tests cover deterministic quality filters and provider-normalization
contracts without live Doctolib or Jameda calls. The live provider APIs are
covered separately by CLI/API smoke tests; this file guards local filtering
logic that should never regress because of German city spelling variants.
"""

from __future__ import annotations

from backend.apps.health.skills.search_appointments_skill import (
    _cities_match,
    _doctolib_motive_allows_new_patients,
    _doctolib_motive_matches_requested_insurance,
    _doctolib_provider_matches_requested_insurance,
    _is_private_practice_name,
    _jameda_service_matches_requested_insurance,
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
    assert _matches_motive_category("Behandlung von Kopfschmerzen/ Schwindel", "general") is False
    assert _matches_motive_category("CMD / Kiefergelenk (Beratung)", "general") is False
    assert _matches_motive_category("Dentcoat (Beratung)", "general") is False
    assert _matches_motive_category("Veneers (Beratung)", "general") is False
    assert _matches_motive_category("Beratung Zahnextraktion", "general") is False
    assert _matches_motive_category("Weisheitszahnentfernung (Beratung)", "general") is False
    assert _matches_motive_category("Beratung Knie-OP (mit existierendem MRT)", "general") is False
    assert _matches_motive_category("OP Beratung und Aufklärung bei Kniebeschwerden", "general") is False
    assert _matches_motive_category("Eingewachsener Zehennagel / Nagelbettentzündung - Erstuntersuchung", "general") is False
    assert _matches_motive_category("Krebsvorsorge, bekannter Patient", "checkup") is False
    assert _matches_motive_category("Kontrolluntersuchung", "general") is False
    assert _matches_motive_category("Nackentransparenz-Messung mit Erst-Trimester-Screening", "checkup") is False
    assert _matches_motive_category("Ersttrimesterscreening/ frühe Feindiagnostik", "checkup") is False
    assert _matches_motive_category("Videosprechstunde - Bestandspatient", "general") is False
    assert _matches_motive_category("Kontrolluntersuchung / Wiedervorstellung", "followup") is True


def test_speciality_guard_rejects_obvious_cross_speciality_results() -> None:
    assert _matches_speciality_intent("kinderarzt", "Kinder- und Jugendarzt", "Praxis") is True
    assert _matches_speciality_intent("kinderarzt", "Zahnärztin", "Dr. Danja Dosch") is False
    assert _matches_speciality_intent("hno", "Hals-Nasen-Ohren-Arzt", "Praxis") is True
    assert _matches_speciality_intent(
        "kardiologie",
        "Internist",
        "Thomas Hilzinger",
        "Herz-Kreislauf-Untersuchung",
    ) is False


def test_doctolib_new_patient_filter_rejects_existing_patient_only_motives() -> None:
    assert _doctolib_motive_allows_new_patients({}) is True
    assert _doctolib_motive_allows_new_patients({"allowNewPatients": True}) is True
    assert _doctolib_motive_allows_new_patients({"allowNewPatients": False}) is False


def test_doctolib_public_insurance_rejects_explicit_paid_motives() -> None:
    assert _doctolib_motive_matches_requested_insurance(
        {"name": "Erstuntersuchung Neupatient:in"},
        "public",
    ) is True
    assert _doctolib_motive_matches_requested_insurance(
        {"name": "Erstuntersuchung Neupatient:in (49 € zusätzlich)"},
        "public",
    ) is False
    assert _doctolib_motive_matches_requested_insurance(
        {"name": "Privatsprechstunde"},
        "public",
    ) is False
    assert _doctolib_motive_matches_requested_insurance(
        {"name": "Hautkrebsvorsorge mit Videodokumentation Fotofinder"},
        "public",
    ) is False
    assert _doctolib_motive_matches_requested_insurance(
        {"name": "MRT nach Arbeitsunfall zu Lasten der Berufsgenossenschaft mit Überweisung vom D-Arzt"},
        "public",
    ) is False


def test_doctolib_public_insurance_rejects_private_telemedicine_practices() -> None:
    assert _doctolib_provider_matches_requested_insurance(
        {
            "link": "/telemedizinische-praxis/muenchen/cardiotelemed-prof-dr-dr-med-juergen-haase",
            "onlineBooking": {"telehealth": True},
            "regulationSector": None,
            "matchedVisitMotive": {"name": "Videosprechstunde - Neupatient"},
        },
        "public",
    ) is False
    assert _doctolib_provider_matches_requested_insurance(
        {
            "link": "/facharzt-fur-hno/berlin/example",
            "onlineBooking": {"telehealth": False},
            "regulationSector": "akzeptiert_gesetzlich_versicherte_patient",
            "matchedVisitMotive": {"name": "Erstuntersuchung Neupatient:in"},
        },
        "public",
    ) is True


def test_public_request_rejects_private_practice_names() -> None:
    assert _is_private_practice_name("Naser Hatami - Privatpraxis") is True
    assert _is_private_practice_name("Praxis für Orthopädie") is False


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


def test_jameda_public_insurance_rejects_selfpayer_services() -> None:
    assert _jameda_service_matches_requested_insurance(
        {"insuranceProviderId": 1, "selfpayer": False},
        "public",
    ) is True
    assert _jameda_service_matches_requested_insurance(
        {"insuranceProviderId": 1, "selfpayer": True},
        "public",
    ) is False
    assert _jameda_service_matches_requested_insurance(
        {"insuranceProviderId": 2, "selfpayer": False},
        "public",
    ) is False
    assert _jameda_service_matches_requested_insurance(
        {"insuranceProviderId": 1, "selfpayer": False, "price": 188.37},
        "public",
    ) is False
    assert _jameda_service_matches_requested_insurance(
        {"insuranceProviderId": 1, "itemServiceName": "Vorsorge PLUS (kostenpflichtig:188,37€)"},
        "public",
    ) is False


def test_jameda_service_selection_drops_public_paid_and_existing_patient_noise() -> None:
    services = [
        {
            "addressServiceId": 1,
            "itemServiceName": "Vorsorge PLUS (kostenpflichtig:188,37€)",
            "insuranceProviderId": 1,
        },
        {
            "addressServiceId": 2,
            "itemServiceName": "Vorsorgeuntersuchung / Krebsvorsorge",
            "insuranceProviderId": 1,
        },
        {
            "addressServiceId": 3,
            "itemServiceName": "Krebsvorsorge, bekannter Patient",
            "insuranceProviderId": 1,
        },
    ]

    selected = _select_jameda_services_for_request(
        services,
        speciality_raw="urologie",
        visit_motive_category="checkup",
        insurance_sector="public",
    )

    assert [svc["addressServiceId"] for svc in selected] == [2]
