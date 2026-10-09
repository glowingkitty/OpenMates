"""Requested embed IDs must not bypass current chat access boundaries."""

import hashlib
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


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_team_member_reads_finished_upload_from_canonical_head_before_unbound_cache() -> None:
    chat_id, team_id, embed_id = "team-chat", "team-1", "uploaded-image"
    hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
    from backend.core.api.app.services.directus.team_methods import hash_id

    cache = SimpleNamespace(get=AsyncMock(return_value={
        "user_id": "uploader", "files": [{"name": "secret.png"}],
        "vault_wrapped_aes_key": "private-vault-wrapper", "plaintext": "private-upload-metadata",
    }))
    key_page = {"embed_keys": [{"key_type": "chat", "encrypted_key": "chat-wrapper"}],
                "has_more_after": False, "end_cursor": None, "oversized_key_id": None}
    directus = SimpleNamespace(
        team=SimpleNamespace(require_team_role=AsyncMock()),
        chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value={"hashed_team_id": hash_id(team_id)})),
        embed=SimpleNamespace(
            get_embed_by_id=AsyncMock(return_value={
                "hashed_chat_id": hashed_chat_id, "hashed_embed_id": hashlib.sha256(embed_id.encode()).hexdigest(),
                "status": "finished", "encryption_mode": "client",
                "encrypted_type": "encrypted-image-type", "encrypted_content": "client-ciphertext",
            }),
            get_sync_embed_key_window_for_page=AsyncMock(return_value=key_page),
        ),
    )
    manager = SimpleNamespace(send_personal_message=AsyncMock())

    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=None, user_id="viewer", device_fingerprint_hash="device-1",
        payload={"embed_id": embed_id, "chat_id": chat_id, "team_id": team_id},
    )

    cache.get.assert_not_awaited()
    directus.team.require_team_role.assert_awaited_once_with(
        team_id, "viewer", {"owner", "admin", "member", "viewer"},
    )
    assert directus.embed.get_sync_embed_key_window_for_page.await_args.kwargs == {
        "include_master_keys": False,
    }
    event = manager.send_personal_message.await_args.args[0]
    assert event["type"] == "send_embed_data"
    assert event["payload"]["content"] == "client-ciphertext"
    assert event["payload"]["already_encrypted"] is True
    assert event["payload"]["embed_keys"] == key_page["embed_keys"]
    assert "private-vault-wrapper" not in str(event)
    assert "private-upload-metadata" not in str(event)


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.anyio
@pytest.mark.parametrize("denial", ["wrong_team", "wrong_chat", "removed_member"])
async def test_team_finished_upload_denies_mismatched_or_removed_viewer(denial: str) -> None:
    from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id

    chat_id, team_id = "team-chat", "team-1"
    directus = SimpleNamespace(
        team=SimpleNamespace(require_team_role=AsyncMock(
            side_effect=TeamPermissionError("removed") if denial == "removed_member" else None,
        )),
        chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value={
            "hashed_team_id": hash_id("different-team" if denial == "wrong_team" else team_id),
        })),
        embed=SimpleNamespace(
            get_embed_by_id=AsyncMock(return_value={
                "hashed_chat_id": hashlib.sha256(
                    ("different-chat" if denial == "wrong_chat" else chat_id).encode()
                ).hexdigest(),
                "status": "finished", "encryption_mode": "client",
                "encrypted_type": "encrypted-image-type", "encrypted_content": "client-ciphertext",
            }),
            get_sync_embed_key_window_for_page=AsyncMock(),
        ),
    )
    cache = SimpleNamespace(get=AsyncMock(return_value={"plaintext": "private-upload-metadata"}))
    manager = SimpleNamespace(send_personal_message=AsyncMock())

    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=None, user_id="viewer", device_fingerprint_hash="device-1",
        payload={"embed_id": "uploaded-image", "chat_id": chat_id, "team_id": team_id},
    )

    cache.get.assert_not_awaited()
    directus.embed.get_sync_embed_key_window_for_page.assert_not_awaited()
    assert manager.send_personal_message.await_args.args[0] == {
        "type": "error", "payload": {"message": "Embed not found", "status": 404},
    }


# contract-test: direct surface=rest_api assertions=storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_team_unbound_upload_cache_without_canonical_head_is_denied() -> None:
    from backend.core.api.app.services.directus.team_methods import hash_id

    team_id = "team-1"
    cache = SimpleNamespace(get=AsyncMock(return_value={
        "user_id": "uploader", "vault_wrapped_aes_key": "private-vault-wrapper",
        "files": [{"name": "private.png"}],
    }))
    directus = SimpleNamespace(
        team=SimpleNamespace(require_team_role=AsyncMock()),
        chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value={"hashed_team_id": hash_id(team_id)})),
        embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value=None)),
    )
    manager = SimpleNamespace(send_personal_message=AsyncMock())

    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=None, user_id="viewer", device_fingerprint_hash="device-1",
        payload={"embed_id": "uploaded-image", "chat_id": "team-chat", "team_id": team_id},
    )

    cache.get.assert_awaited_once()
    assert manager.send_personal_message.await_args.args[0] == {
        "type": "error", "payload": {"message": "Embed not found", "status": 404},
    }
