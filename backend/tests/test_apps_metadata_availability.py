"""Regression tests for app metadata provider availability checks.

These tests protect Settings > Apps visibility from provider-specific secret
shapes. App skills can use credentials that are not named `api_key`; the app
store metadata endpoint must still treat those skills as configured so the
frontend does not hide them after user-specific skill filtering.
"""

from __future__ import annotations

import pytest

from backend.core.api.app.routes.apps import SkillMetadataItem, _skill_models, build_app_metadata_item, check_provider_api_key_available
from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition, AppYAML, ProviderRef


class FakeSecretsManager:
    vault_token = "test-token"
    vault_url = "http://vault.test"

    async def get_secret(self, *, secret_path: str, secret_key: str) -> str | None:
        if secret_path == "kv/data/providers/edamam" and secret_key in {"app_id", "app_key"}:
            return "configured"
        return None


# contract-test: infrastructure reason=provider_credential_shape_unit
@pytest.mark.anyio
async def test_edamam_availability_accepts_app_id_and_app_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET__EDAMAM__API_KEY", raising=False)
    monkeypatch.delenv("SECRET__EDAMAM__APP_ID", raising=False)
    monkeypatch.delenv("SECRET__EDAMAM__APP_KEY", raising=False)

    assert await check_provider_api_key_available("edamam", FakeSecretsManager()) is True


# contract-test: infrastructure reason=provider_metadata_schema_unit
def test_skill_metadata_response_preserves_providers() -> None:
    item = SkillMetadataItem(
        id="get_events",
        name="Get events",
        description="Read calendar events",
        providers=[ProviderRef(name="Google", no_api_key=True)],
    )

    payload = item.model_dump()

    assert payload["providers"] == [{"name": "Google", "display_name": None, "no_api_key": True}]


# contract-test: supporting surface=rest_api assertions=ai-model-routing.catalog.capability-recommendation-variants
def test_skill_models_filter_missing_provider_keys() -> None:
    provider_configs = {
        "openai": {
            "name": "OpenAI",
            "models": [{"id": "gpt-4o-mini", "name": "GPT-4o Mini", "for_app_skill": "ai.ask"}],
        },
        "anthropic": {
            "name": "Anthropic",
            "models": [{"id": "claude-haiku", "name": "Claude Haiku", "for_app_skill": "ai.ask"}],
        },
    }

    models = _skill_models(
        app_id="ai",
        skill_id="ask",
        provider_configs=provider_configs,
        available_provider_ids={"openai"},
    )

    assert [model.provider_id for model in models] == ["openai"]


# contract-test: infrastructure reason=app_metadata_provider_projection_unit
def test_app_metadata_filters_unavailable_provider_details_and_models() -> None:
    app = AppYAML(
        id="web",
        name_translation_key="apps.web.name",
        description_translation_key="apps.web.description",
        category="work",
        skills=[
            AppSkillDefinition(
                id="search",
                name_translation_key="skills.web.search.name",
                description_translation_key="skills.web.search.description",
                providers=[ProviderRef(name="Brave")],
            ),
            AppSkillDefinition(
                id="ask",
                name_translation_key="skills.web.ask.name",
                description_translation_key="skills.web.ask.description",
            ),
        ],
    )
    provider_configs = {
        "brave": {"name": "Brave", "description": "Search"},
        "openai": {"name": "OpenAI", "models": [{"id": "gpt-4o-mini", "for_app_skill": "web.ask"}]},
    }

    item = build_app_metadata_item(
        app_id="web",
        app_metadata=app,
        translation_service=None,
        provider_configs=provider_configs,
        available_provider_ids={"openai"},
    )

    assert [provider.id for provider in item.skills[0].provider_details] == []
    assert [model.provider_id for model in item.skills[1].models] == ["openai"]


# contract-test: supporting surface=rest_api assertions=billing.models.active-price-consistency
def test_public_skill_models_preserve_current_promotion_without_supplier_costs() -> None:
    metadata = {"id": "intro", "effective_from": "2026-10-13", "expires_on": "2026-11-30",
                "source_url": "https://example.test/pricing", "reviewed_on": "2026-10-14",
                "eligible_hosts": ["google_ai_studio"], "processing_tier": "standard"}
    models = _skill_models(app_id="ai", skill_id="ask", provider_configs={"google": {
        "name": "Google", "models": [{"id": "gemini-4-argon", "for_app_skill": "ai.ask",
        "pricing": {"tokens": {"input": {"per_credit_unit": 160}},
                    "context_bands": {"over_200k": {"min_input_tokens": 200001, "tokens": {"input": {"per_credit_unit": 85}}}}},
        "active_temporary_price": metadata, "costs": {"supplier_secret": 2}}]}})
    published = models[0].model_dump()
    assert published["active_temporary_price"] == metadata
    assert published["pricing"]["tokens"]["input"]["per_credit_unit"] == 160
    assert published["pricing"]["context_bands"]["over_200k"]["min_input_tokens"] == 200001
    assert "costs" not in published


# contract-test: supporting surface=rest_api assertions=settings-ui.localization.visible-content-resolves,apps.discovery.public-catalog
@pytest.mark.parametrize("resolved", [True, False])
def test_focus_display_prefers_resolved_translation_over_authored_fallback(monkeypatch, resolved):
    from backend.core.api.app.routes import apps

    app = AppYAML(
        id="social_media", name_translation_key="apps.social_media",
        description_translation_key="apps.social_media.description", category="work",
        focuses=[{
            "id": "post", "name_translation_key": "social_media.post",
            "description_translation_key": "social_media.post.description",
            "process": ["Review the draft."],
            "system_prompt": "Help write a considered post.",
            "process_translation_key": "social_media_post.process",
            "systemprompt_translation_key": "social_media_post.systemprompt",
        }],
    )
    localized = {
        "social_media_post.process": "- Prüfe den Entwurf.\n  - Prüfe die Quellen.",
        "social_media_post.systemprompt": "Hilf beim Verfassen eines durchdachten Beitrags.",
    }
    monkeypatch.setattr(apps, "resolve_translation", lambda service, key, namespace, fallback="": localized.get(key, fallback) if resolved else fallback or key)
    item = apps.build_app_metadata_item(
        app_id="social_media", app_metadata=app, translation_service=None, provider_configs={},
    )
    focus = item.focus_modes[0]
    assert focus.process == (["Prüfe den Entwurf.", "Prüfe die Quellen."] if resolved else ["Review the draft."])
    assert focus.system_prompt == (localized["social_media_post.systemprompt"] if resolved else "Help write a considered post.")
    assert app.focuses[0].system_prompt == "Help write a considered post."
    assert app.focuses[0].process == ["Review the draft."]
