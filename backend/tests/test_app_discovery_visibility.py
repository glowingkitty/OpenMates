"""Discovery requires an executable skill or focus, never only durable data."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException

from backend.core.api.app.routes import apps, apps_api
from backend.core.api.app.services.app_discovery_visibility import EXCLUDED_DISCOVERY_APPS
from backend.shared.python_schemas.app_metadata_schemas import AppYAML


def source(app_id, *, skill=None, focus=None, memory=False, embeds=()):
    return AppYAML(
        id=app_id, name_translation_key=f"apps.{app_id}",
        description_translation_key=f"apps.{app_id}.description", category="work",
        skills=[dict(id="run", name_translation_key="run", description_translation_key="run.description", **skill)] if skill is not None else [],
        focuses=[dict(id="reflect", name_translation_key="reflect", description_translation_key="reflect.description", system_prompt="Reflect carefully.", **focus)] if focus is not None else [],
        embed_types=list(embeds),
        memory_fields=[dict(id="saved", type="list", name_translation_key="saved", description_translation_key="saved.description", schema={"type": "object"})] if memory else [],
    )


def direct_embed(*, catalog=True, paused=False):
    return {
        "id": "document", "category": "direct", "frontend_type": "document",
        "backend_type": "document", "default_enabled": False if paused else None,
        "content_catalog": {"enabled": catalog, "content_type_id": "document"},
    }


VISIBLE = {"focus_only", "local", "ccc", "docs", "mindmaps", "diagrams", "electronics"}


@pytest.fixture
def discovery(monkeypatch):
    definitions = {
        "memory_only": source("memory_only", memory=True),
        "source_free": source("source_free", skill={"provider_required": True, "providers": []}, memory=True),
        "paused": source("paused", skill={"default_enabled": False}, memory=True),
        "missing_credentials": source("missing_credentials", skill={"providers": ["UnavailableProvider"]}),
        "mail": source("mail", skill={"providers": [{"name": "PrivateMail", "no_api_key": True}]}),
        "paused_focus": source("paused_focus", focus={"default_enabled": False}, memory=True),
        "focus_only": source("focus_only", focus={}),
        **{app_id: source(app_id, embeds=[direct_embed()]) for app_id in ["docs", "mindmaps", "diagrams", "electronics"]},
        "models3d": source("models3d", embeds=[dict(id="saved_model", category="direct", frontend_type="model", backend_type="model")]),
        "disabled_catalog": source("disabled_catalog", embeds=[direct_embed(catalog=False)]),
        "paused_creation": source("paused_creation", embeds=[direct_embed(paused=True)]),
        "skill_result_catalog": source("skill_result_catalog", embeds=[{**direct_embed(), "category": "app-skill-use", "skill_id": "search"}]),
        "local": source("local", skill={}),
        "ccc": source("ccc", skill={"providers": [{"name": "media.ccc.de", "no_api_key": True}]}),
        **{app_id: source(app_id, skill={}, focus={}, embeds=[direct_embed()]) for app_id in EXCLUDED_DISCOVERY_APPS},
    }
    definitions["mail"].skills[0].id = "search"
    secrets = SimpleNamespace(initialize=AsyncMock(), get_secret=AsyncMock(side_effect=AssertionError("No live secrets")))
    state = SimpleNamespace(discovered_apps_metadata=definitions, secrets_manager=secrets, cache_service=None, config_manager=None, translation_service=None)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    monkeypatch.setattr(apps, "SecretsManager", lambda **kwargs: secrets)
    monkeypatch.setattr(apps, "_is_protonmail_user_allowed", AsyncMock(return_value=False))
    monkeypatch.setattr(apps, "_available_provider_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(apps, "check_provider_api_key_available", AsyncMock(return_value=False))
    monkeypatch.setattr(apps_api, "check_provider_api_key_available", AsyncMock(return_value=False))
    monkeypatch.setattr(apps_api, "get_discovered_apps", lambda request: definitions)
    monkeypatch.setattr(apps_api, "get_translation_service", lambda request: None)
    monkeypatch.setattr(apps_api, "get_config_manager", lambda request: None)
    monkeypatch.setattr(apps_api, "_is_protonmail_allowed_for_external_user", AsyncMock(return_value=False))
    monkeypatch.setattr(apps_api, "get_skill_providers_with_pricing", AsyncMock(return_value=[]))
    return request, definitions, secrets


# contract-test: supporting surface=rest_api assertions=apps.discovery.public-catalog
@pytest.mark.asyncio
@pytest.mark.parametrize("include_unavailable", [False, True])
@pytest.mark.parametrize("module", [apps, apps_api])
async def test_lists_require_actual_skill_or_enabled_focus_even_with_compatibility_flag(discovery, module, include_unavailable):
    request, definitions, secrets = discovery
    if module is apps:
        result = await apps.get_apps_metadata(request, current_user=None, encryption_service=None, include_unavailable=include_unavailable)
        visible = set(result.apps)
    else:
        result = await apps_api.list_apps(request, user_info={"user_id": "isolated"}, include_unavailable=include_unavailable)
        visible = {item.id for item in result.apps}
        for app_id in ["docs", "mindmaps", "diagrams", "electronics"]:
            item = next(item for item in result.apps if item.id == app_id)
            assert item.content_types[0]["id"] == f"{app_id}.document"
            assert item.content_types[0]["source"] == "self"
    assert visible == VISIBLE
    assert "mail" not in visible and "missing_credentials" not in visible
    assert definitions["memory_only"].memory_fields[0].id == "saved"
    assert len(definitions["source_free"].skills) == 1
    secrets.get_secret.assert_not_called()


# contract-test: supporting surface=rest_api assertions=apps.discovery.public-catalog
@pytest.mark.asyncio
@pytest.mark.parametrize("app_id", ["memory_only", "source_free", "paused", "paused_focus", "missing_credentials", "mail", "models3d", "disabled_catalog", "paused_creation", "skill_result_catalog", *sorted(EXCLUDED_DISCOVERY_APPS)])
async def test_public_direct_metadata_does_not_restore_hidden_apps(discovery, app_id):
    request, _, _ = discovery
    with pytest.raises(HTTPException) as exc:
        await apps.get_app_metadata(app_id, request, include_unavailable=True)
    assert exc.value.status_code == 404


# contract-test: supporting surface=rest_api assertions=apps.discovery.public-catalog
@pytest.mark.asyncio
@pytest.mark.parametrize("app_id", sorted(VISIBLE))
async def test_public_direct_metadata_keeps_valid_apps(discovery, app_id):
    request, _, _ = discovery
    result = await apps.get_app_metadata(app_id, request, include_unavailable=True)
    assert result.id == app_id


# contract-test: supporting surface=rest_api assertions=apps.discovery.public-catalog
@pytest.mark.asyncio
async def test_dynamic_authenticated_details_share_visibility_and_preserve_404(discovery):
    request, definitions, _ = discovery
    api = FastAPI()
    apps_api.register_app_and_skill_routes(api, definitions)
    for app_id in definitions:
        handler = next(route.endpoint for route in api.routes if route.path == f"/v1/apps/{app_id}")
        if app_id in VISIBLE:
            assert (await handler(request, user_info={"user_id": "isolated"})).id == app_id
        else:
            with pytest.raises(HTTPException) as exc:
                await handler(request, user_info={"user_id": "isolated"})
            assert exc.value.status_code == 404


# contract-test: supporting surface=rest_api assertions=apps.discovery.public-catalog
def test_real_creation_declarations_do_not_reactivate_retired_result_renderers():
    from pathlib import Path
    import yaml
    from backend.core.api.app.services.app_discovery_visibility import app_is_discoverable

    root = Path(__file__).resolve().parents[1] / "apps"
    for app_id in ["docs", "mindmaps", "diagrams", "electronics"]:
        metadata = yaml.safe_load((root / app_id / "app.yml").read_text())
        assert app_is_discoverable(app_id, [], [], metadata.get("embed_types", []))
    for app_id in ["events", "travel", "health", "home", "models3d"]:
        metadata = yaml.safe_load((root / app_id / "app.yml").read_text())
        assert not app_is_discoverable(app_id, [], [], metadata.get("embed_types", []))
