# backend/tests/test_chat_model_preference_handler.py
#
# Authorization regressions for encrypted per-user chat model preferences.
# Shared recipients must not learn another participant's preference, while
# owner-scoped writes remain strictly forbidden outside the caller's chat scope.

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.chat_model_preference_handler import (
    handle_chat_model_preference,
)
from backend.core.api.app.services.directus.team_methods import TeamPermissionError


def _services() -> tuple[SimpleNamespace, SimpleNamespace]:
    manager = SimpleNamespace(send_personal_message=AsyncMock(), broadcast_to_user=AsyncMock())
    directus = SimpleNamespace(
        chat=SimpleNamespace(
            check_chat_ownership=AsyncMock(return_value=False),
            get_chat_metadata=AsyncMock(return_value={"hashed_user_id": "another-user"}),
        ),
        chat_model_preference=SimpleNamespace(
            get_preference=AsyncMock(),
            upsert_preference=AsyncMock(),
        ),
        team=SimpleNamespace(require_team_role=AsyncMock()),
    )
    return manager, directus


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
async def test_shared_recipient_read_returns_empty_preference() -> None:
    manager, directus = _services()

    await handle_chat_model_preference(
        websocket=AsyncMock(),
        manager=manager,
        cache_service=AsyncMock(),
        directus_service=directus,
        encryption_service=AsyncMock(),
        user_id="recipient-user",
        device_fingerprint_hash="recipient-device",
        payload={"chat_id": "shared-chat"},
        operation="get",
    )

    manager.send_personal_message.assert_awaited_once_with(
        {
            "type": "chat_model_preference",
            "payload": {"chat_id": "shared-chat", "preference": None},
        },
        "recipient-user",
        "recipient-device",
    )
    directus.chat_model_preference.get_preference.assert_not_awaited()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
async def test_shared_recipient_update_remains_forbidden() -> None:
    manager, directus = _services()

    await handle_chat_model_preference(
        websocket=AsyncMock(),
        manager=manager,
        cache_service=AsyncMock(),
        directus_service=directus,
        encryption_service=AsyncMock(),
        user_id="recipient-user",
        device_fingerprint_hash="recipient-device",
        payload={
            "chat_id": "shared-chat",
            "encrypted_selected_ai_model": "ciphertext",
            "expected_preference_v": 0,
        },
        operation="update",
    )

    message = manager.send_personal_message.await_args.args[0]
    assert message["type"] == "error"
    assert message["payload"]["code"] == "chat_model_preference_forbidden"
    directus.chat_model_preference.upsert_preference.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "update"])
# contract-test: supporting surface=rest_api assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
async def test_team_non_member_uses_privacy_safe_denial(operation: str) -> None:
    manager, directus = _services()
    directus.team.require_team_role.side_effect = TeamPermissionError("Team permission denied")

    await handle_chat_model_preference(
        websocket=AsyncMock(),
        manager=manager,
        cache_service=AsyncMock(),
        directus_service=directus,
        encryption_service=AsyncMock(),
        user_id="recipient-user",
        device_fingerprint_hash="recipient-device",
        payload={"chat_id": "team-chat", "team_id": "private-team"},
        operation=operation,
    )

    message = manager.send_personal_message.await_args.args[0]
    if operation == "get":
        assert message == {
            "type": "chat_model_preference",
            "payload": {"chat_id": "team-chat", "preference": None},
        }
    else:
        assert message["type"] == "error"
        assert message["payload"]["code"] == "chat_model_preference_forbidden"
    directus.chat_model_preference.get_preference.assert_not_awaited()
    directus.chat_model_preference.upsert_preference.assert_not_awaited()
