"""Unit tests for the health appointment search skill.

These tests cover deterministic quality filters and provider-normalization
contracts without live Doctolib or Jameda calls. The live provider APIs are
covered separately by CLI/API smoke tests; this file guards local filtering
logic that should never regress because of German city spelling variants.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from pydantic import ValidationError
from backend.apps.health.skills import search_appointments_skill as skill

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


# contract-test: supporting surface=rest_api assertions=health-search-appointments.eligibility.location-speciality
def test_jameda_city_matching_accepts_umlaut_city_names() -> None:
    """Jameda returns display cities while requests use URL slug city names."""

    assert _cities_match("Köln", "koeln") is True
    assert _cities_match("München", "muenchen") is True
    assert _cities_match("Düsseldorf", "duesseldorf") is True
    assert _cities_match("Nürnberg", "nuernberg") is True


# contract-test: supporting surface=rest_api assertions=health-search-appointments.eligibility.location-speciality
def test_jameda_city_matching_rejects_different_cities() -> None:
    assert _cities_match("Berlin", "hamburg") is False
    assert _cities_match("Köln", "bonn") is False
    assert _cities_match("", "koeln") is False


# contract-test: supporting surface=rest_api assertions=health-search-appointments.purpose.explicit
def test_procedure_filter_rejects_wrong_radiology_modality() -> None:
    assert _matches_procedure_intent("ct", "CT Oberbauch") is True
    assert _matches_procedure_intent("ct", "MRT Kniegelenk") is False
    assert _matches_procedure_intent("mrt", "MRT Kopf / Schädel") is True
    assert _matches_procedure_intent("mrt", "CT NNH nativ") is False


# contract-test: supporting surface=rest_api assertions=health-search-appointments.purpose.explicit
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
    assert _matches_motive_category("Beratung Behandlung Eigenfett", "general") is False
    assert _matches_motive_category("Beratung zu Behandlungen für ein Leben ohne Brille - Augenlasern", "general") is False
    assert _matches_motive_category("Voruntersuchung Augen-OP Katarakt (Grauer Star)", "general") is False
    assert _matches_motive_category("Buche jetzt dein kostenloses Beratungsgespräch zur Ketamintherapie", "general") is False
    assert _matches_motive_category("Beratung Knie-OP (mit existierendem MRT)", "general") is False
    assert _matches_motive_category("OP Beratung und Aufklärung bei Kniebeschwerden", "general") is False
    assert _matches_motive_category("Eingewachsener Zehennagel / Nagelbettentzündung - Erstuntersuchung", "general") is False
    assert _matches_motive_category("Krebsvorsorge, bekannter Patient", "checkup") is False
    assert _matches_motive_category("Kontrolluntersuchung", "general") is False
    assert _matches_motive_category("Kontrolluntersuchung", "checkup") is True
    assert _matches_motive_category("Nackentransparenz-Messung mit Erst-Trimester-Screening", "checkup") is False
    assert _matches_motive_category("Ersttrimesterscreening/ frühe Feindiagnostik", "checkup") is False
    assert _matches_motive_category("Videosprechstunde - Bestandspatient", "general") is False
    assert _matches_motive_category("Kontrolluntersuchung / Wiedervorstellung", "followup") is True


# contract-test: supporting surface=rest_api assertions=health-search-appointments.eligibility.location-speciality
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


# contract-test: supporting surface=rest_api assertions=health-search-appointments.purpose.explicit
def test_doctolib_new_patient_filter_rejects_existing_patient_only_motives() -> None:
    assert _doctolib_motive_allows_new_patients({}) is True
    assert _doctolib_motive_allows_new_patients({"allowNewPatients": True}) is True
    assert _doctolib_motive_allows_new_patients({"allowNewPatients": False}) is False


# contract-test: supporting surface=rest_api assertions=health-search-appointments.purpose.explicit
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


# contract-test: supporting surface=rest_api assertions=health-search-appointments.eligibility.insurance-patients
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


# contract-test: supporting surface=rest_api assertions=health-search-appointments.eligibility.insurance-patients
def test_public_request_rejects_private_practice_names() -> None:
    assert _is_private_practice_name("Naser Hatami - Privatpraxis") is True
    assert _is_private_practice_name("Praxis für Orthopädie") is False


# contract-test: supporting surface=rest_api assertions=health-search-appointments.purpose.explicit
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


# contract-test: supporting surface=rest_api assertions=health-search-appointments.eligibility.insurance-patients
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


# contract-test: supporting surface=rest_api assertions=health-search-appointments.eligibility.insurance-patients
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


# contract-test: supporting surface=rest_api assertions=health-search-appointments.purpose.initial-consultation
@pytest.mark.parametrize("category", [None, "general"])
def test_initial_consultation_never_falls_back_to_prp(category):
    services = [{"addressServiceId": 620472, "itemServiceName": "Eigenbluttherapie (PRP) Gelenkbehandlung"}]
    assert skill._select_jameda_services_for_request(services, "orthopädie", category, None) == []


# contract-test: supporting surface=rest_api assertions=health-search-appointments.purpose.initial-consultation
@pytest.mark.parametrize("category", [None, "general"])
def test_initial_consultation_preserves_general_service(category):
    services = [
        {"addressServiceId": 620472, "itemServiceName": "Eigenbluttherapie (PRP) Gelenkbehandlung"},
        {"addressServiceId": 5078, "itemServiceName": "Allgemeine Sprechstunde"},
    ]
    assert [s["addressServiceId"] for s in skill._select_jameda_services_for_request(services, "orthopädie", category, None)] == [5078]


# contract-test: supporting surface=rest_api assertions=health-search-appointments.input.validated
@pytest.mark.parametrize("override", [
    {"city": " "}, {"speciality": ""}, {"provider_platform": "unknown"},
    {"visit_motive_category": "anything"}, {"insurance_sector": "free"},
    {"days_ahead": 14}, {"max_doctors": 0}, {"max_doctors": 100000},
    {"telehealth": "false"},
])
def test_search_request_rejects_invalid_criteria(override):
    with pytest.raises(ValidationError):
        skill.SearchAppointmentsRequestItem.model_validate({"speciality": "orthopädie", "city": "Berlin", **override})


# contract-test: supporting surface=rest_api assertions=health-search-appointments.results.grouping,health-search-appointments.availability.window-order
def test_grouping_uses_instants_and_preserves_provider_identity():
    base = {"practice_id": 1, "visit_motive_id": 2, "name": "Synthetic practice", "address": "Berlin"}
    slots = [
        {**base, "provider_platform": "Jameda", "slot_datetime": "2026-09-09T11:00:00Z"},
        {**base, "provider_platform": "Jameda", "slot_datetime": "2026-09-09T12:30:00+02:00"},
        {**base, "provider_platform": "Doctolib", "slot_datetime": "2026-09-09T12:45:00+02:00"},
    ]
    result = skill._group_slots_by_doctor(slots)
    assert len(result) == 2
    assert result[0]["slot_datetime"] == "2026-09-09T12:30:00+02:00"
    assert result[0]["additional_slot_datetimes"] == ["2026-09-09T11:00:00Z"]
    assert result[1]["provider_platform"] == "Doctolib"


# contract-test: supporting surface=rest_api assertions=health-search-appointments.availability.window-order
def test_invalid_timestamps_cannot_be_available_slots():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    result = skill._filter_past_slots([{"slot_datetime": "not-a-time"}, {"slot_datetime": future}])
    assert result == [{"slot_datetime": future}]


# contract-test: supporting surface=rest_api assertions=health-search-appointments.eligibility.modality-language
@pytest.mark.parametrize("constraint", [{"telehealth": True}, {"language": "gb"}])
async def test_jameda_unverifiable_filters_do_not_query_provider(monkeypatch, constraint):
    async def forbidden(*args, **kwargs):
        raise AssertionError("provider must not be queried for unsupported filters")
    monkeypatch.setattr(skill, "_get_jameda_token", forbidden)
    _, results, error = await skill._process_single_jameda_request(None, {"speciality": "orthopädie", "city": "Berlin", **constraint})
    assert results == []
    assert error.startswith("Unsupported Jameda filters:")


# contract-test: supporting surface=rest_api assertions=health-search-appointments.outcomes.explicit
async def test_partial_failure_keeps_sanitized_results_and_provider_coverage(monkeypatch):
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def client(*args, **kwargs):
        yield None
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    async def doctolib(*args, **kwargs):
        return "1", [], "provider temporarily unavailable"
    async def jameda(*args, **kwargs):
        return "1", [{"slot_datetime": future, "name": "Synthetic Practice", "provider_platform": "Jameda", "visit_motive": "Allgemeine Sprechstunde"}], None
    sanitized = []
    async def sanitize(payload, **kwargs):
        sanitized.append(payload)
        return payload
    monkeypatch.setattr(skill, "create_http_client", client)
    monkeypatch.setattr(skill, "_process_single_doctolib_request", doctolib)
    monkeypatch.setattr(skill, "_process_single_jameda_request", jameda)
    monkeypatch.setattr(skill, "sanitize_long_text_fields_in_payload", sanitize)
    instance = skill.SearchAppointmentsSkill(None, "health", "search_appointments", "Search", "Search appointments")
    _, results, error = await instance._make_request_processor(None, None, None)({"id": "1", "provider_platform": "both", "days_ahead": 1})
    assert error is None
    assert len(results) == 1 and len(sanitized) == 1
    assert results[0]["search_coverage"] == {"Doctolib": "failed", "Jameda": "success"}


# contract-test: supporting surface=rest_api assertions=health-search-appointments.availability.window-order
async def test_jameda_query_uses_offset_aware_rolling_window():
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"_items": []}
    class Client:
        url = None
        async def get(self, url, **kwargs):
            self.url = url
            return Response()
    from urllib.parse import urlparse, parse_qs
    client = Client()
    before = datetime.now(timezone.utc)
    await skill._jameda_fetch_slots(client, "synthetic-token", "1", "2", 1)
    query = parse_qs(urlparse(client.url).query)
    start = datetime.fromisoformat(query["start"][0])
    end = datetime.fromisoformat(query["end"][0])
    assert abs((start - before).total_seconds()) < 2
    assert end - start == timedelta(days=1)


# contract-test: supporting surface=rest_api assertions=health-search-appointments.availability.window-order
def test_slots_outside_requested_window_are_not_returned():
    now = datetime.now(timezone.utc)
    slots = [{"slot_datetime": (now + timedelta(hours=h)).isoformat()} for h in (2, 48)]
    assert skill._filter_past_slots(slots, days_ahead=1) == slots[:1]


# contract-test: supporting surface=rest_api assertions=health-search-appointments.eligibility.modality-language,health-search-appointments.eligibility.location-speciality
@pytest.mark.parametrize("constraint", [{"telehealth": True}, {"language": "gb"}, {"city": "Hamburg"}])
async def test_doctolib_checks_constraints_before_fetching_slots(monkeypatch, constraint):
    async def resolve(*args, **kwargs): return {}
    async def search(*args, **kwargs):
        return [{"speciality": {"name": "Orthopäde"}, "location": {"city": "Berlin"},
                 "languages": ["de"], "matchedVisitMotive": {"name": "Allgemeine Sprechstunde", "visitMotiveId": 1},
                 "onlineBooking": {"telehealth": False, "agendaIds": [1]}, "references": {"practiceId": 1}}]
    availability_calls = []
    async def forbidden(*args, **kwargs):
        availability_calls.append(True)
        return {"availabilities": []}
    monkeypatch.setattr(skill, "_resolve_location", resolve)
    monkeypatch.setattr(skill, "_search_doctors", search)
    monkeypatch.setattr(skill, "_fetch_availability", forbidden)
    _, results, error = await skill._process_single_doctolib_request(None, {"speciality": "orthopädie", "city": "Berlin", **constraint})
    assert results == []
    assert error is None
    assert not availability_calls


# contract-test: supporting surface=rest_api assertions=health-search-appointments.outcomes.explicit
async def test_jameda_slot_failure_is_not_successful_empty():
    class BrokenClient:
        async def get(self, *args, **kwargs):
            raise skill.httpx.ReadError("Synthetic upstream failure")
    with pytest.raises(skill.httpx.ReadError):
        await skill._jameda_fetch_slots(BrokenClient(), "synthetic-token", "1", "2", 1)


# contract-test: supporting surface=rest_api assertions=health-search-appointments.purpose.explicit,health-search-appointments.eligibility.insurance-patients
async def test_followup_preserves_existing_patient_request(monkeypatch):
    async def resolve(*args, **kwargs): return {}
    async def search(*args, **kwargs):
        return [{"speciality": {"name": "Orthopäde"}, "location": {"city": "Berlin"},
                 "matchedVisitMotive": {"name": "Kontrolluntersuchung / Wiedervorstellung", "visitMotiveId": 1, "allowNewPatients": False},
                 "onlineBooking": {"agendaIds": [1]}, "references": {"practiceId": 1}}]
    calls = []
    async def availability(*args, **kwargs):
        calls.append(True)
        return {"availabilities": []}
    monkeypatch.setattr(skill, "_resolve_location", resolve)
    monkeypatch.setattr(skill, "_search_doctors", search)
    monkeypatch.setattr(skill, "_fetch_availability", availability)
    await skill._process_single_doctolib_request(None, {"speciality": "orthopädie", "city": "Berlin", "visit_motive_category": "followup"})
    assert calls == [True]


# contract-test: supporting surface=rest_api assertions=health-search-appointments.purpose.explicit
async def test_jameda_followup_does_not_request_new_patient_slots():
    from urllib.parse import urlparse, parse_qs
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"_items": []}
    class Client:
        url = ""
        async def get(self, url, **kwargs):
            self.url = url
            return Response()
    client = Client()
    await skill._jameda_fetch_slots(client, "synthetic-token", "1", "2", 1, service_id=3, new_patient=False)
    query = parse_qs(urlparse(client.url).query)
    assert query["filters[is_new_patient]"] == ["0"]


# contract-test: supporting surface=rest_api assertions=health-search-appointments.outcomes.explicit
async def test_doctolib_availability_failure_is_not_successful_empty():
    class BrokenClient:
        async def get(self, *args, **kwargs):
            raise skill.httpx.ReadError("Synthetic upstream failure")
    with pytest.raises(skill.httpx.ReadError):
        await skill._fetch_availability(BrokenClient(), 1, [1], 1, "public", False, 1)


# contract-test: supporting surface=rest_api assertions=health-search-appointments.purpose.initial-consultation
@pytest.mark.parametrize("motive", ["Burnout (Beratung)", "Schulterbeschwerden (Behandlung)"])
def test_general_consultation_rejects_unrequested_condition_treatment(motive):
    assert not skill._matches_motive_category(motive, "general")


# contract-test: supporting surface=rest_api assertions=health-search-appointments.input.validated
@pytest.mark.parametrize("days", ["1", "3", "7"])
def test_search_accepts_numeric_enum_strings_from_llm_schema(days):
    request = skill.SearchAppointmentsRequestItem(speciality="orthopädie", city="Berlin", days_ahead=days)
    assert request.days_ahead == int(days)


# contract-test: supporting surface=rest_api assertions=health-search-appointments.input.validated
def test_search_rejects_boolean_lookahead():
    with pytest.raises(ValidationError):
        skill.SearchAppointmentsRequestItem(speciality="orthopädie", city="Berlin", days_ahead=True)


# contract-test: supporting surface=rest_api assertions=health-search-appointments.purpose.initial-consultation
def test_general_consultation_excludes_preventive_exam():
    assert not skill._matches_motive_category("Vorsorgeuntersuchung", "general")
    assert skill._matches_motive_category("Vorsorgeuntersuchung", "checkup")


# contract-test: supporting surface=rest_api assertions=health-search-appointments.input.validated
@pytest.mark.parametrize("request_id", [None, 7, "caller-id"])
def test_request_validation_preserves_base_skill_generated_ids(request_id):
    instance = skill.SearchAppointmentsSkill(None, "health", "search_appointments", "Search", "Search appointments")
    requests, invalid, errors, error = instance._partition_requests_by_required_fields(
        requests=[{"id": request_id, "speciality": "orthopädie", "city": "Berlin"}],
        required_fields=["speciality", "city"],
        field_display_names={},
        empty_error_message="No requests",
        logger=skill.logger,
    )
    assert not invalid and not errors and not error
    result = skill.SearchAppointmentsRequestItem.model_validate(requests[0])
    assert result.id == (1 if request_id is None else request_id)
