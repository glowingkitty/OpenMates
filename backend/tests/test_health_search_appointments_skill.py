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
