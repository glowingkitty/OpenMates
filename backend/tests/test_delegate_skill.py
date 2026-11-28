"""Verify inputs and results at the installed appointment package boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.shared.app_packages import delegate_skill
from backend.shared.app_packages.provider_dispatch import InstalledProviderOutcome


# contract-test: supporting surface=rest_api assertions=health-search-appointments.input.validated
@pytest.mark.anyio
async def test_long_appointment_window_reaches_selected_provider_without_relevance_text(monkeypatch):
    provider = SimpleNamespace(provider_id="example", name="Example")
    row = {
        "provider_id": "example",
        "practitioner_role": "physician",
        "visit_motive": "General consultation",
    }
    run = AsyncMock(return_value=[InstalledProviderOutcome("example", [row])])
    monkeypatch.setattr(delegate_skill, "run_installed_providers", run)
    models = delegate_skill.resolve_original_skill_models(
        "backend.apps.health.skills.search_appointments_skill.SearchAppointmentsSkill",
    )
    skill = object.__new__(delegate_skill.InstalledProviderSkill)
    skill.app_id, skill.skill_id = "health", "search_appointments"

    result = await skill._serve_item(0, {
        "city": "Example City",
        "speciality": "psychiatrist",
        "days_ahead": 30,
        "provider_platform": "example",
        "medication_visit": "initiation",
        "relevance_criteria": "Medication intake",
    }, models, [provider], None)

    assert run.call_args.args[2] == ["example"]
    assert run.call_args.args[3]["days_ahead"] == 30
    assert "relevance_criteria" not in run.call_args.args[3]
    assert result["results"] == [{**row, "prescribing_match": "unverified"}]
