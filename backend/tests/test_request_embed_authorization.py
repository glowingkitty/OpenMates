"""Requested embed IDs must not bypass current chat access boundaries."""

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.request_embed_handler import handle_request_embed


def _source_lookup(directus: SimpleNamespace, metadata: dict | None) -> None:
    async def get_items(collection: str, params: dict, **kwargs):
        assert collection == "chats"
        assert kwargs == {"no_cache": True, "admin_required": True, "raise_on_error": True}
        assert params["fields"] == "id,hashed_user_id,hashed_team_id,storage_state"
        return ([{"id": params["filter"]["id"]["_eq"], **metadata}]
                if metadata is not None else [])

    directus.get_items = AsyncMock(side_effect=get_items)


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_foreign_embed_id_is_denied_before_cache_read() -> None:
    cache = SimpleNamespace(get=AsyncMock(return_value={"chat_id": "owned-chat"}))
    directus = SimpleNamespace(
        chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value={
            "hashed_user_id": hashlib.sha256(b"user-1").hexdigest(), "hashed_team_id": None,
        })),
        embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value={
            "embed_id": "foreign-embed", "hashed_chat_id": "foreign-chat-hash",
        })),
    )
    _source_lookup(directus, {"hashed_user_id": hashlib.sha256(b"user-1").hexdigest(),
                             "hashed_team_id": None})
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
        chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value={
            "hashed_team_id": hashlib.sha256(b"team-1").hexdigest(),
        })),
        embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value=None)),
    )
    _source_lookup(directus, {"hashed_team_id": hashlib.sha256(b"team-1").hexdigest()})
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
        chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value=None)),
        embed=SimpleNamespace(get_embed_by_id=AsyncMock()),
    )
    _source_lookup(directus, None)
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
    _source_lookup(directus, {"hashed_team_id": hash_id(team_id)})
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
    _source_lookup(directus, {
        "hashed_team_id": hash_id("different-team" if denial == "wrong_team" else team_id),
    })
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
    _source_lookup(directus, {"hashed_team_id": hash_id(team_id)})
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


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
@pytest.mark.parametrize("include_team_id", [False, True])
async def test_removed_team_author_cannot_omit_chat_id(include_team_id: bool) -> None:
    from backend.core.api.app.services.directus.team_methods import hash_id

    owner_hash = hashlib.sha256(b"former-author").hexdigest()
    team_id = "team-1"
    directus = SimpleNamespace(
        team=SimpleNamespace(require_team_role=AsyncMock()),
        chat=SimpleNamespace(
            get_chat_activity_candidates=AsyncMock(return_value=[{"id": "team-chat"}]),
            get_chat_metadata=AsyncMock(return_value={
                "hashed_user_id": owner_hash, "hashed_team_id": hash_id(team_id),
            }),
        ),
        embed=SimpleNamespace(
            get_embed_by_id=AsyncMock(return_value={
                "hashed_user_id": owner_hash,
                "hashed_chat_id": hashlib.sha256(b"team-chat").hexdigest(),
                "status": "finished", "encrypted_content": "team-ciphertext",
                "encrypted_type": "team-type",
            }),
            get_sync_embed_key_window_for_page=AsyncMock(),
        ),
    )
    _source_lookup(directus, {"hashed_user_id": owner_hash, "hashed_team_id": hash_id(team_id)})
    cache = SimpleNamespace(get=AsyncMock())
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=None, user_id="former-author", device_fingerprint_hash="device-1",
        payload={"embed_id": "upload", **({"team_id": team_id} if include_team_id else {})},
    )
    cache.get.assert_not_awaited()
    directus.embed.get_sync_embed_key_window_for_page.assert_not_awaited()
    assert manager.send_personal_message.await_args.args[0]["payload"]["status"] == 404


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_team_creator_cannot_use_personal_chat_id_even_if_ownership_cache_says_yes() -> None:
    from backend.core.api.app.services.directus.team_methods import hash_id

    directus = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(return_value={
                "hashed_user_id": hashlib.sha256(b"former-author").hexdigest(),
                "hashed_team_id": hash_id("team-1"),
            }),
            check_chat_ownership=AsyncMock(return_value=True),
        ),
        embed=SimpleNamespace(get_embed_by_id=AsyncMock()),
    )
    _source_lookup(directus, {
        "hashed_user_id": hashlib.sha256(b"former-author").hexdigest(),
        "hashed_team_id": hash_id("team-1"),
    })
    cache = SimpleNamespace(get=AsyncMock())
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=None, user_id="former-author", device_fingerprint_hash="device-1",
        payload={"embed_id": "upload", "chat_id": "team-chat"},
    )
    directus.chat.check_chat_ownership.assert_not_awaited()
    directus.embed.get_embed_by_id.assert_not_awaited()
    cache.get.assert_not_awaited()
    assert manager.send_personal_message.await_args.args[0]["payload"]["status"] == 404


# contract-test: direct surface=rest_api assertions=storage.cold.shared-team-authorized
@pytest.mark.anyio
@pytest.mark.parametrize("state", ["missing", "deleting", "wrong_owner"])
async def test_personal_source_must_be_live_and_owned(state: str) -> None:
    metadata = None if state == "missing" else {
        "hashed_team_id": None,
        "hashed_user_id": hashlib.sha256(("other" if state == "wrong_owner" else "owner").encode()).hexdigest(),
        "storage_state": "deleting" if state == "deleting" else "hot",
    }
    directus = SimpleNamespace(
        chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value=metadata)),
        embed=SimpleNamespace(get_embed_by_id=AsyncMock()),
    )
    _source_lookup(directus, metadata)
    cache = SimpleNamespace(get=AsyncMock())
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=None, user_id="owner", device_fingerprint_hash="device-1",
        payload={"embed_id": "upload", "chat_id": "personal-chat"},
    )
    cache.get.assert_not_awaited()
    directus.embed.get_embed_by_id.assert_not_awaited()
    assert manager.send_personal_message.await_args.args[0]["payload"]["status"] == 404


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
async def test_legacy_personal_author_reads_only_verified_personal_source() -> None:
    chat_id, user_id = "personal-chat", "owner"
    owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
    key_page = {"embed_keys": [{"key_type": "master", "encrypted_embed_key": "owner-wrapper"}],
                "has_more_after": False, "end_cursor": None, "oversized_key_id": None}
    directus = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_activity_candidates=AsyncMock(return_value=[{"id": chat_id}]),
            get_chat_metadata=AsyncMock(return_value={
                "hashed_user_id": owner_hash, "hashed_team_id": None, "storage_state": "hot",
            }),
        ),
        embed=SimpleNamespace(
            get_embed_by_id=AsyncMock(return_value={
                "hashed_user_id": owner_hash, "hashed_chat_id": hashlib.sha256(chat_id.encode()).hexdigest(),
                "status": "finished", "encrypted_content": "personal-ciphertext",
                "encrypted_type": "personal-type",
            }),
            get_sync_embed_key_window_for_page=AsyncMock(return_value=key_page),
        ),
    )
    _source_lookup(directus, {"hashed_user_id": owner_hash, "hashed_team_id": None,
                             "storage_state": "hot"})
    cache = SimpleNamespace(get=AsyncMock())
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=None, user_id=user_id, device_fingerprint_hash="device-1",
        payload={"embed_id": "upload"},
    )
    directus.embed.get_sync_embed_key_window_for_page.assert_awaited_once()
    assert directus.embed.get_sync_embed_key_window_for_page.await_args.kwargs == {
        "include_master_keys": True,
    }
    assert manager.send_personal_message.await_args.args[0]["payload"]["content"] == "personal-ciphertext"
