"""Requested embed IDs must not bypass current chat access boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.request_embed_handler import handle_request_embed


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_foreign_embed_id_is_denied_before_cache_read() -> None:
    cache = SimpleNamespace(get=AsyncMock(return_value={"chat_id": "owned-chat"}))
    directus = SimpleNamespace(
        chat=SimpleNamespace(check_chat_ownership=AsyncMock(return_value=True)),
        embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value={
            "embed_id": "foreign-embed", "hashed_chat_id": "foreign-chat-hash",
        })),
    )
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=None, user_id="user-1", device_fingerprint_hash="device-1",
        payload={"embed_id": "foreign-embed", "chat_id": "owned-chat"},
    )
    cache.get.assert_not_awaited()
    assert manager.send_personal_message.await_args.args[0] == {
        "type": "error", "payload": {"message": "Embed not found", "status": 404},
    }


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_team_embed_request_checks_current_membership_before_cache_read() -> None:
    from backend.core.api.app.services.directus.team_methods import TeamPermissionError

    cache = SimpleNamespace(get=AsyncMock())
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    directus = SimpleNamespace(
        team=SimpleNamespace(require_team_role=AsyncMock(side_effect=TeamPermissionError("denied"))),
        embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value=None)),
    )
    await handle_request_embed(
        websocket=None, manager=manager,
        cache_service=cache, directus_service=directus, encryption_service=None,
        user_id="user-1", device_fingerprint_hash="device-1",
        payload={"embed_id": "embed-1", "chat_id": "chat-1", "team_id": "team-1"},
    )
    cache.get.assert_not_awaited()
    directus.embed.get_embed_by_id.assert_not_awaited()
    assert manager.send_personal_message.await_args.args[0] == {
        "type": "error", "payload": {"message": "Embed not found", "status": 404},
    }


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_foreign_chat_id_is_denied_before_embed_or_cache_read() -> None:
    cache = SimpleNamespace(get=AsyncMock())
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    directus = SimpleNamespace(
        chat=SimpleNamespace(check_chat_ownership=AsyncMock(return_value=False)),
        embed=SimpleNamespace(get_embed_by_id=AsyncMock()),
    )
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=None, user_id="user-1", device_fingerprint_hash="device-1",
        payload={"embed_id": "foreign-embed", "chat_id": "foreign-chat"},
    )
    cache.get.assert_not_awaited()
    directus.embed.get_embed_by_id.assert_not_awaited()
    assert manager.send_personal_message.await_args.args[0] == {
        "type": "error", "payload": {"message": "Embed not found", "status": 404},
    }
