"""Login and session responses carry the saved AI model preferences (TASK-1349).

The server applies saved defaults (e.g. ``default_ai_model_complex``) to every
request. When the login/session response dropped them, Settings showed "Auto"
while production kept routing complex requests to the old saved model.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.core.api.app.routes.auth_routes.auth_common import read_ai_preferences_for_auth
from backend.core.api.app.schemas.user import AI_PREFERENCE_FIELDS, UserResponse, ai_preference_fields


def _response(**user_data: object) -> dict[str, object]:
    return UserResponse(
        username="test-user", is_admin=False, credits=0, tfa_enabled=False,
        **ai_preference_fields(user_data),
    ).model_dump()


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preferences.exclusive-tier-defaults
def test_saved_model_defaults_are_returned() -> None:
    user = _response(
        default_ai_model_simple="google/gemini-3.8-flash",
        default_ai_model_complex="google/gemini-3.1-pro-preview",
        default_app_skill_models={"images.generate": "google/x"},
        follow_up_suggestions_enabled=False,
        recommendations_enabled=False,
    )
    assert user["default_ai_model_simple"] == "google/gemini-3.8-flash"
    assert user["default_ai_model_complex"] == "google/gemini-3.1-pro-preview"
    assert user["default_ai_model_most_demanding"] is None
    assert user["default_app_skill_models"] == {"images.generate": "google/x"}
    assert user["follow_up_suggestions_enabled"] is False
    assert user["recommendations_enabled"] is False


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preferences.exclusive-tier-defaults
def test_unset_preferences_mean_auto_and_enabled() -> None:
    user = _response(follow_up_suggestions_enabled=None, default_app_skill_models=None)
    assert user["default_ai_model_complex"] is None
    assert user["default_app_skill_models"] == {}
    assert user["follow_up_suggestions_enabled"] is True
    assert user["recommendations_enabled"] is True


# contract-test: supporting surface=rest_api assertions=ai-model-routing.preferences.exclusive-tier-defaults
async def test_auth_uses_saved_selections_and_auto_over_a_stale_profile() -> None:
    read_saved = AsyncMock(return_value={
        "default_ai_model_simple": "google/gemini-3.8-flash",
        "default_ai_model_complex": None,
    })
    directus = SimpleNamespace(get_user_fields_direct=read_saved)

    preferences = await read_ai_preferences_for_auth(
        directus, "test-user", {
            "default_ai_model_simple": None,
            "default_ai_model_complex": "google/gemini-3.1-pro-preview",
        },
    )

    read_saved.assert_awaited_once_with("test-user", list(AI_PREFERENCE_FIELDS), no_cache=True)
    assert preferences["default_ai_model_simple"] == "google/gemini-3.8-flash"
    assert preferences["default_ai_model_complex"] is None
