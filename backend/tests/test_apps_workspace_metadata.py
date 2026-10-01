"""Apps workspace public details and form-contract regression coverage."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import importlib
import sys

import pytest
import yaml
from fastapi import HTTPException

# Reuse the route tests' lightweight import infrastructure before route imports.
from backend.tests import test_apps_api as _apps_api_infra  # noqa: F401


def _route_dependency_stub(name: str, **members: object) -> ModuleType:
    module = ModuleType(name)
    for member, value in members.items():
        setattr(module, member, value)
    return module


# The public metadata route needs no database or cache connection. Keep the
# import-only doubles scoped to this import so other tests can load the actual
# services without inheriting this test's lightweight dependency graph.
_route_module_name = "backend.core.api.app.routes.apps"
_preexisting_route = sys.modules.get(_route_module_name)
with patch.dict(sys.modules, {
    "backend.core.api.app.services.limiter": _route_dependency_stub(
        "backend.core.api.app.services.limiter", limiter=_apps_api_infra._StubLimiter(),
    ),
    "backend.core.api.app.services.directus.directus": _route_dependency_stub(
        "backend.core.api.app.services.directus.directus", DirectusService=object,
    ),
    "backend.core.api.app.services.cache": _route_dependency_stub(
        "backend.core.api.app.services.cache", CacheService=object,
    ),
    "backend.core.api.app.routes.internal_api": _route_dependency_stub(
        "backend.core.api.app.routes.internal_api",
        get_directus_service=lambda: None,
        get_cache_service=lambda: None,
    ),
}):
    apps_routes = importlib.import_module(_route_module_name)

if _preexisting_route is None:
    # Retain this test's reference while allowing a later test to import the
    # production route with its real services from a dependency-complete env.
    sys.modules.pop(_route_module_name, None)
    _routes_package = importlib.import_module("backend.core.api.app.routes")
    if getattr(_routes_package, "apps", None) is apps_routes:
        delattr(_routes_package, "apps")
from backend.core.api.app.services.apps_workspace_metadata import (  # noqa: E402 # Import after scoped route dependency setup
    execution_status,
    primary_fields,
    request_schema,
    schema_defaults,
)
from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition, AppYAML  # noqa: E402


def _catalog_skill(app_id: str, skill_id: str) -> AppSkillDefinition:
    source = Path(__file__).resolve().parents[1] / "apps" / app_id / "app.yml"
    document = yaml.safe_load(source.read_text())
    return AppSkillDefinition.model_validate(next(
        skill for skill in document["skills"] if skill["id"] == skill_id
    ))


# contract-test: supporting surface=rest_api assertions=apps.forms.metadata-driven
def test_real_catalog_primary_fields_group_single_requests_routes_and_dates() -> None:
    news = _catalog_skill("news", "search")
    travel = _catalog_skill("travel", "search_connections")
    weather = _catalog_skill("weather", "forecast")

    assert primary_fields(request_schema(news))[0] == "requests[].query"
    assert len(primary_fields(request_schema(news))) <= 2
    assert primary_fields(request_schema(travel)) == [
        "requests[].legs[].origin", "requests[].legs[].destination",
    ]
    legs = request_schema(travel)["properties"]["requests"]["items"]["properties"]["legs"]["items"]
    assert "date" in legs["required"]
    assert primary_fields(request_schema(weather)) == ["location", "start_date"]
    assert schema_defaults(request_schema(news))["requests"][0]["count"] == 10
    assert schema_defaults(request_schema(weather))["days"] == 7
    assert "location" not in schema_defaults(request_schema(weather))


# contract-test: supporting surface=rest_api assertions=apps.forms.metadata-driven
def test_audio_generate_declares_one_prompt_with_advanced_duration_default() -> None:
    skill = _catalog_skill("audio", "generate")
    workflow_fields = skill.tool_schema["properties"]["requests"]["items"]["properties"]
    assert workflow_fields["prompt"]["x-ui"] == {"basic": True, "apps": {"control": "textarea"}}
    for name in ("duration_seconds", "loop", "output_format"):
        assert workflow_fields[name]["x-ui"]["basic"] is True
        assert workflow_fields[name]["x-ui"]["apps"] == {"basic": False}

    schema = request_schema(skill)
    request_fields = schema["properties"]["requests"]["items"]["properties"]

    assert primary_fields(schema) == ["requests[].prompt"]
    assert request_fields["prompt"]["x-ui"]["control"] == "textarea"
    assert "apps" not in request_fields["prompt"]["x-ui"]
    assert request_fields["duration_seconds"]["x-ui"]["basic"] is False
    assert request_fields["duration_seconds"]["default"] == 1.0
    assert schema_defaults(schema)["requests"][0]["duration_seconds"] == 1.0


# contract-test: supporting surface=rest_api assertions=apps.forms.metadata-driven
def test_direct_schema_is_authoritative_and_defaults_are_copied() -> None:
    skill = AppSkillDefinition(
        id="run", name_translation_key="run", description_translation_key="run.description",
        tool_schema={"type": "object", "properties": {"prompt": {"type": "string"}}},
        sdk_tool_schema={"type": "object", "properties": {"mode": {"type": "string", "default": "direct"}}},
    )
    schema = request_schema(skill)
    schema["properties"]["mode"]["default"] = "changed"

    assert request_schema(skill)["properties"]["mode"]["default"] == "direct"
    assert schema_defaults(request_schema(skill)) == {"mode": "direct"}
    assert "prompt" not in request_schema(skill)["properties"]


# contract-test: supporting surface=rest_api assertions=apps.discovery.public-catalog,apps.anonymous.cli-equivalent-gate
def test_execution_requires_registered_runtime_public_post_and_workflow_capability() -> None:
    registry = SimpleNamespace(is_skill_available=lambda app, skill: True)
    capability = SimpleNamespace(enabled=True, reason=None, metadata={"workflow": {"execution_mode": "sync"}})
    skill = _catalog_skill("news", "search")
    assert execution_status(app_id="news", skill=skill, registry=registry, capability=capability) == (True, None, "sync")

    blocked = _catalog_skill("code", "run")
    assert execution_status(app_id="code", skill=blocked, registry=registry, capability=capability)[1] == "REST_EXECUTION_UNAVAILABLE"
    capability.enabled = False
    capability.reason = "WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED"
    assert execution_status(app_id="news", skill=skill, registry=registry, capability=capability)[1] == capability.reason


class _FakeSecrets:
    def __init__(self, **kwargs: object) -> None:
        pass

    async def initialize(self) -> None:
        pass


# contract-test: supporting surface=rest_api assertions=apps.discovery.public-catalog,apps.forms.metadata-driven,apps.anonymous.cli-equivalent-gate
@pytest.mark.anyio
async def test_public_details_exposes_only_safe_catalog_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    skill = _catalog_skill("news", "search")
    skill.class_path = "secret.internal.Implementation"
    skill.default_config = {"api_key": "private-value"}
    app = AppYAML(
        id="news", name_translation_key="news", description_translation_key="news.description",
        skills=[skill],
    )
    state = SimpleNamespace(
        discovered_apps_metadata={"news": app},
        skill_registry=SimpleNamespace(is_skill_available=lambda app, skill: True),
        config_manager=None,
        translation_service=None,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    monkeypatch.setattr(apps_routes, "SecretsManager", _FakeSecrets)
    monkeypatch.setattr(apps_routes, "is_skill_available", lambda *args: _true())
    monkeypatch.setattr(apps_routes, "_available_provider_ids", lambda **kwargs: _empty_set())
    monkeypatch.setattr(
        apps_routes, "WorkflowCapabilityRegistry",
        lambda **kwargs: SimpleNamespace(get_capability=lambda id: SimpleNamespace(
            enabled=True, reason=None, metadata={"workflow": {"execution_mode": "sync"}},
        )),
    )

    result = await apps_routes.get_skill_details(
        request=request, app_id="news", skill_id="search",
        current_user=None, encryption_service=object(),
    )
    payload = result.model_dump(mode="json")
    assert payload["anonymous_allowed"] is True
    assert payload["execution_available"] is True
    assert payload["primary_fields"][0] == "requests[].query"
    assert len(payload["primary_fields"]) <= 2
    assert payload["defaults"]["requests"][0]["count"] == 10
    assert "secret.internal" not in str(payload)
    assert "private-value" not in str(payload)

    skill.internal = True
    with pytest.raises(HTTPException) as error:
        await apps_routes.get_skill_details(
            request=request, app_id="news", skill_id="search",
            current_user=None, encryption_service=object(),
        )
    assert error.value.status_code == 404


async def _true() -> bool:
    return True


async def _empty_set() -> set[str]:
    return set()
