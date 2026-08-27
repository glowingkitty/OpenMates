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
