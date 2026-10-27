"""Provider-backed execution fails before dispatch when no supported source exists."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.apps.base_app import BaseApp
from backend.core.api.app.routes import apps, apps_api
from backend.core.api.app.services.skill_registry import SkillRegistry, filter_app_components_by_availability
from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition, skill_has_provider_support


def definition(**kwargs):
    return AppSkillDefinition(
        id="search", name_translation_key="skills.search.name",
        description_translation_key="skills.search.description", **kwargs,
    )


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.parametrize("raw", [False, True])
def test_provider_requirement_keeps_local_operations_available(raw):
    local = definition(providers=[])
    remote = definition(provider_required=True, providers=[])
    supported = definition(provider_required=True, providers=[{"name": "Public Catalog", "no_api_key": True}])
    for skill, expected in [(local, True), (remote, False), (supported, True)]:
        assert skill_has_provider_support(skill.model_dump() if raw else skill) is expected


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
@pytest.mark.parametrize("module", [apps, apps_api])
async def test_catalog_rejects_source_free_skill_before_secret_access(module):
    secrets = SimpleNamespace(get_secret=AsyncMock(side_effect=AssertionError("Unexpected credential access")))
    assert await module.is_skill_available(definition(provider_required=True, providers=[]), "sample", secrets) is False
    assert await module.is_skill_available(definition(providers=[]), "sample", secrets) is True
    secrets.get_secret.assert_not_called()


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
def test_registry_filters_source_free_skills_but_preserves_historical_readers():
    payload = {
        "skills": [
            {"id": "search", "class_path": "sample.Search", "provider_required": True, "providers": []},
            {"id": "local", "class_path": "sample.Local"},
        ],
        "embed_types": [{"id": "result"}],
    }
    available = SimpleNamespace(is_enabled=lambda _: True)
    filtered = filter_app_components_by_availability("sample", payload, available)
    assert [skill["id"] for skill in filtered["skills"]] == ["local"]
    assert filtered["embed_types"] == [{"id": "result"}]
    assert len(payload["skills"]) == 2


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_direct_dispatch_rejects_before_constructing_skill_or_mutating_input():
    class UnexpectedSkill:
        def __init__(self, **kwargs):
            raise AssertionError("Unavailable skill must not be constructed")

    app = object.__new__(BaseApp)
    request = {"query": "sample", "_user_id": "owner"}
    with pytest.raises(HTTPException) as exc:
        await app._dispatch_skill_with_class(definition(provider_required=True, providers=[]), UnexpectedSkill, request)
    assert exc.value.status_code == 503
    assert request == {"query": "sample", "_user_id": "owner"}


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
def test_registry_does_not_advertise_resolved_source_free_implementation():
    registry = SkillRegistry()
    skill = definition(provider_required=True, providers=[])
    registry.apps["sample"] = SimpleNamespace(skill_classes={"search": object}, get_skill_by_id=lambda _: skill)
    assert registry.is_skill_available("sample", "search") is False
