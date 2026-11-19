"""Push chat-title preference route: merges one boolean and never touches other keys."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.core.api.app.routes.push import PushPreferencesRequest, update_push_preferences


def _run(stored, value):
    directus = SimpleNamespace(
        get_user_fields_direct=AsyncMock(return_value={"push_notification_preferences": stored}),
        update_user=AsyncMock(return_value=True),
    )
    cache = SimpleNamespace(update_user=AsyncMock(return_value=True))
    user = SimpleNamespace(id="synthetic-user")
    result = asyncio.run(update_push_preferences(PushPreferencesRequest(includeChatTitle=value), user, directus, cache))
    return result, directus, cache


@pytest.mark.parametrize("stored,value,expected", [
    (None, False, {"includeChatTitle": False}),
    ({"aiResponses": True}, False, {"aiResponses": True, "includeChatTitle": False}),
    ('{"aiResponses": false}', True, {"aiResponses": False, "includeChatTitle": True}),
])
# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_preference_is_merged_and_cached(stored, value, expected):
    result, directus, cache = _run(stored, value)
    assert result.success is True
    directus.update_user.assert_awaited_once_with("synthetic-user", {"push_notification_preferences": expected})
    cache.update_user.assert_awaited_once_with("synthetic-user", {"push_notification_preferences": expected})


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_preference_rejects_non_boolean_values():
    with pytest.raises(ValidationError):
        PushPreferencesRequest(includeChatTitle="false")
