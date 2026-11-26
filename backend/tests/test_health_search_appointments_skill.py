"""Offline appointment contract while no permitted source is configured."""
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
import yaml
from pydantic import ValidationError
from backend.apps.health.skills.search_appointments_skill import (
    SearchAppointmentsSkill, SearchAppointmentsRequestItem,
)

# contract-test: direct surface=rest_api assertions=health-search-appointments.input.validated
@pytest.mark.parametrize("values", [{"speciality": "", "city": "Berlin"}, {"speciality": "dentist", "city": ""},
    {"speciality": "dentist", "city": "Berlin", "days_ahead": 14}])
def test_invalid_appointment_request_rejected(values):
    with pytest.raises(ValidationError):
        SearchAppointmentsRequestItem(**values)

# contract-test: direct surface=rest_api assertions=app-skills.providers.unavailable-no-network
@pytest.mark.anyio
async def test_unavailable_appointment_search_performs_no_external_work(monkeypatch):
    skill = object.__new__(SearchAppointmentsSkill)
    secrets = AsyncMock(side_effect=AssertionError("must not load credentials"))
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", secrets)
    result = await skill.execute(requests=[{"id": "medical", "speciality": "dentist", "city": "Berlin"}])
    assert result.error and "unavailable" in result.error.lower()
    assert result.provider == "Unavailable"
    assert result.results[0]["id"] == "medical"
    assert result.results[0]["results"] == []
    secrets.assert_not_awaited()
    meta = yaml.safe_load(Path("backend/apps/health/app.yml").read_text())["skills"][0]
    assert meta["provider_required"] is True
    assert meta["providers"] == []
    assert SearchAppointmentsSkill.resolve_preview_metadata({"provider_platform": "unknown-source"})["providers"] == []


# contract-test: direct surface=rest_api assertions=health-search-appointments.input.validated
@pytest.mark.parametrize("days", [30, 60, "30", "60"])
def test_appointment_window_accepts_explicit_extended_presets(days):
    request = SearchAppointmentsRequestItem(speciality="ophthalmologist", city="Berlin", days_ahead=days)
    assert request.days_ahead == int(days)


# contract-test: direct surface=rest_api assertions=health-search-appointments.results.prescribing-evidence
@pytest.mark.anyio
async def test_medication_search_keeps_unknown_and_removes_explicit_conflicts():
    group = {"results": [
        {"name": "Therapist", "practitioner_role": "non_prescribing"},
        {"name": "Restricted visit", "prescribing_availability": "unavailable"},
        {"name": "General intake", "practitioner_role": "physician"},
        {"name": "Medication consultation", "prescribing_availability": "available"},
    ]}
    await SearchAppointmentsSkill.postprocess_installed_group(
        group, {"requires_prescribing_clinician": True}, None, None,
    )
    assert group["excluded_appointment_count"] == 2
    assert [(row["name"], row["prescribing_match"]) for row in group["results"]] == [
        ("General intake", "unverified"),
        ("Medication consultation", "confirmed"),
    ]


# contract-test: direct surface=rest_api assertions=health-search-appointments.results.optional-relevance
@pytest.mark.anyio
async def test_optional_ranking_preserves_booking_fields_and_avoids_identity_in_projection(monkeypatch):
    from backend.apps.health.skills import search_appointments_skill as module
    from backend.shared.python_utils.search_relevance import SearchRelevanceRankingResult

    results = [
        {"name": "Practice A", "visit_motive": "General visit", "booking_url": "https://example.org/a"},
        {"name": "Practice B", "visit_motive": "New patient eye examination", "booking_url": "https://example.org/b"},
    ]
    rank = AsyncMock(return_value=SearchRelevanceRankingResult(candidates=results[::-1], applied=True))
    monkeypatch.setattr(module, "rank_search_candidates", rank)
    group = {"results": results[:]}
    await SearchAppointmentsSkill.postprocess_installed_group(group, {}, None, None)
    assert group["results"] == results
    rank.assert_not_awaited()

    await SearchAppointmentsSkill.postprocess_installed_group(
        group, {"relevance_criteria": "New-patient eye examination"}, None, None,
    )
    assert group["results"] == results[::-1]
    assert group["relevance_ranking"] == "applied"
    assert rank.call_args.kwargs["candidate_projections"] == [
        {"visit_motive": "General visit"},
        {"visit_motive": "New patient eye examination"},
    ]


# contract-test: direct surface=rest_api assertions=health-search-appointments.results.prescribing-evidence
@pytest.mark.anyio
async def test_initiation_and_external_diagnosis_require_separate_evidence():
    group = {"results": [
        {"name": "Repeat prescriptions", "prescribing_availability": "available", "prescribing_scope": "continuation"},
        {"name": "In-house diagnosis only", "prescribing_scope": "both", "accepts_external_diagnosis": False},
        {"name": "Generic intake", "prescribing_availability": "available"},
        {"name": "Eligible intake", "prescribing_availability": "available", "prescribing_scope": "initiation",
         "accepts_external_diagnosis": True},
    ]}
    await SearchAppointmentsSkill.postprocess_installed_group(group, {
        "medication_visit": "initiation", "requires_external_diagnosis_acceptance": True,
    }, None, None)
    assert group["excluded_appointment_count"] == 2
    assert [(row["name"], row["prescribing_match"], row["external_diagnosis_match"]) for row in group["results"]] == [
        ("Generic intake", "unverified", "unverified"),
        ("Eligible intake", "confirmed", "confirmed"),
    ]
