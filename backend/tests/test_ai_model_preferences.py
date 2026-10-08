# backend/tests/test_ai_model_preferences.py
#
# Contract tests for authenticated owner-scoped AI tier model defaults.
# They require a partial update to preserve the three independent selections,
# including the most-demanding tier, without cross-owner or multi-value state.
# Product implementation belongs to backend/core/api/app/routes/settings.py.

from backend.core.api.app.schemas.settings import AiModelDefaultsRequest


# contract-test: direct surface=rest_api assertions=ai-model-routing.preferences.exclusive-tier-defaults
def test_owner_can_set_exactly_one_value_for_each_of_three_tiers() -> None:
    """The owner default transport must retain one independent scalar per tier."""

    request = AiModelDefaultsRequest(
        default_ai_model_simple="google/gemini-3.5-flash-lite",
        default_ai_model_complex="google/gemini-3.7-flash",
        default_ai_model_most_demanding="google/gemini-3.7-flash-high",
    )

    assert request.model_fields_set == {
        "default_ai_model_simple",
        "default_ai_model_complex",
        "default_ai_model_most_demanding",
    }
    assert request.default_ai_model_simple == "google/gemini-3.5-flash-lite"
    assert request.default_ai_model_complex == "google/gemini-3.7-flash"
    assert request.default_ai_model_most_demanding == "google/gemini-3.7-flash-high"


# contract-test: direct surface=rest_api assertions=ai-model-routing.preferences.exclusive-tier-defaults
def test_most_demanding_update_is_owner_scoped_and_does_not_replace_other_tiers() -> None:
    """A partial owner update replaces only that owner's one tier selection."""

    request_data = AiModelDefaultsRequest(
        default_ai_model_most_demanding="google/gemini-3.7-flash-high",
    )

    assert request_data.model_fields_set == {"default_ai_model_most_demanding"}
    assert request_data.default_ai_model_most_demanding == "google/gemini-3.7-flash-high"


# contract-test: direct surface=rest_api assertions=ai-model-routing.preferences.exclusive-tier-defaults
def test_owner_can_reset_most_demanding_preference_to_auto() -> None:
    """Null is the exclusive Auto selection, rather than an unavailable exact model."""

    request_data = AiModelDefaultsRequest(default_ai_model_most_demanding=None)

    assert request_data.model_fields_set == {"default_ai_model_most_demanding"}
    assert request_data.default_ai_model_most_demanding is None


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preferences.exclusive-tier-defaults
async def test_tier_default_writes_reject_retired_and_non_chat_models_before_storage(monkeypatch) -> None:
    import inspect
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import pytest
    import yaml
    from fastapi import HTTPException
    from backend.core.api.app.routes import settings

    providers = Path(__file__).resolve().parents[1] / "providers"
    models = {
        f"{provider}/{model['id']}": model
        for provider in ("anthropic", "openai")
        for model in yaml.safe_load((providers / f"{provider}.yml").read_text())["models"]
    }
    monkeypatch.setattr(settings.config_manager, "get_model_pricing", lambda provider, model: models.get(f"{provider}/{model}"))
    directus = SimpleNamespace(update_user=AsyncMock(return_value=True))
    cache = SimpleNamespace(update_user=AsyncMock(return_value=True))
    handler = inspect.unwrap(settings.update_ai_model_defaults)
    for model in ("anthropic/claude-haiku-4-5-20251001", "openai/gpt-6-sol", "openai/gpt-image-2"):
        with pytest.raises(HTTPException) as error:
            await handler(
                request=SimpleNamespace(), request_data=AiModelDefaultsRequest(default_ai_model_simple=model),
                current_user=SimpleNamespace(id="owner"), directus_service=directus, cache_service=cache,
            )
        assert error.value.status_code == 400
    directus.update_user.assert_not_awaited()
    cache.update_user.assert_not_awaited()

    for model in ("anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5", "openai/gpt-6.1-sol", None):
        response = await handler(
            request=SimpleNamespace(), request_data=AiModelDefaultsRequest(default_ai_model_simple=model),
            current_user=SimpleNamespace(id="owner"), directus_service=directus, cache_service=cache,
        )
        assert response.success
        directus.update_user.assert_awaited_with("owner", {"default_ai_model_simple": model})
        cache.update_user.assert_awaited_with("owner", {"default_ai_model_simple": model})
