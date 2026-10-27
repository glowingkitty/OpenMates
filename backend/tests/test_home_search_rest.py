"""Offline housing schemas and unavailable execution contract."""
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
import yaml
from backend.apps.home.skills.search_skill import SearchSkill, SearchRequest

# contract-test: direct surface=rest_api assertions=app-skills.providers.unavailable-no-network
@pytest.mark.anyio
@pytest.mark.parametrize("providers", [None, ["unknown-source"]])
async def test_housing_search_unavailable_without_credentials_or_provider_work(monkeypatch, providers):
    skill = object.__new__(SearchSkill)
    secrets = AsyncMock(side_effect=AssertionError("must not load credentials"))
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", secrets)
    request = SearchRequest(requests=[{"query": "Berlin", "providers": providers}])
    result = await skill.execute(requests=[item.model_dump() for item in request.requests])
    assert result.error and "unavailable" in result.error.lower()
    assert result.results[0]["results"] == []
    assert result.providers == []
    assert result.provider == "Unavailable"
    secrets.assert_not_awaited()
    meta = yaml.safe_load(Path("backend/apps/home/app.yml").read_text())["skills"][0]
    assert meta["provider_required"] is True
    assert meta["providers"] == []
    assert SearchSkill.resolve_preview_metadata({"providers": providers})["providers"] == []
