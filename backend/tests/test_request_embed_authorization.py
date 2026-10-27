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
@pytest.mark.parametrize("status", ["finished", "error"])
async def test_foreign_embed_id_is_denied_before_cache_read(status) -> None:
    cache = SimpleNamespace(get=AsyncMock(return_value={"chat_id": "owned-chat"}))
    directus = SimpleNamespace(
        chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value={
            "hashed_user_id": hashlib.sha256(b"user-1").hexdigest(), "hashed_team_id": None,
        })),
        embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value={
            "embed_id": "foreign-embed", "hashed_chat_id": "foreign-chat-hash",
            "status": status, "encryption_mode": "client",
            "encrypted_type": "type-cipher", "encrypted_content": "content-cipher",
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


# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
@pytest.mark.parametrize('catalog', [False, True])
async def test_owner_reloads_terminal_error_ciphertext_without_cache_or_decryption(catalog):
    owner_hash = hashlib.sha256(b'owner').hexdigest()
    row = {'embed_id': 'failed-skill', 'hashed_user_id': owner_hash,
           'hashed_chat_id': hashlib.sha256(b'chat').hexdigest(),
           'status': 'error', 'encryption_mode': 'client',
           'encrypted_type': 'type-ciphertext', 'encrypted_content': 'content-ciphertext'}
    if catalog:
        row.update(app_id='fitness', skill_id='search_classes')
    directus = SimpleNamespace(embed=SimpleNamespace(
        get_embed_by_id=AsyncMock(return_value=row),
        get_sync_embed_key_window_for_page=AsyncMock(return_value={
            'embed_keys': [{'key_type': 'master', 'encrypted_embed_key': 'wrapper'}],
            'has_more_after': False, 'end_cursor': None, 'oversized_key_id': None,
        }),
    ))
    _source_lookup(directus, {'hashed_user_id': owner_hash, 'hashed_team_id': None})
    cache = SimpleNamespace(get=AsyncMock())
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock())
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=encryption, user_id='owner', device_fingerprint_hash='device',
        payload={'embed_id': 'failed-skill', 'chat_id': 'chat'},
    )
    cache.get.assert_not_awaited()
    encryption.decrypt_with_user_key.assert_not_awaited()
    payload = manager.send_personal_message.await_args.args[0]['payload']
    assert payload['status'] == 'error'
    assert payload['type'] == 'type-ciphertext'
    assert payload['content'] == 'content-ciphertext'
    assert payload['already_encrypted'] is True


# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
@pytest.mark.parametrize('kind', ['valid', 'cancelled', 'raw', 'vault', 'missing-mode', 'non-app', 'incomplete', 'invalid-content', 'decrypt-error'])
async def test_cache_only_terminal_execution_error_is_decrypted_and_retained(kind):
    from toon_format import encode

    owner_hash = hashlib.sha256(b'owner').hexdigest()
    cache_row = {'chat_id': 'chat', 'hashed_user_id': owner_hash, 'type': 'app_skill_use',
                 'status': 'error', 'encryption_mode': 'client', 'encrypted_content': 'vault-cipher'}
    if kind == 'cancelled':
        cache_row['status'] = 'cancelled'
    if kind == 'raw':
        cache_row.pop('encrypted_content')
        cache_row['error'] = 'raw provider details'
    if kind == 'vault':
        cache_row['encryption_mode'] = 'vault'
        cache_row['encrypted_content'] = 'vault:v1:9Obx8WYnN6o=:Fv0Ds6QmEQk=:r41Zfb1S7HjHIMHn'
    elif kind == 'missing-mode':
        cache_row.pop('encryption_mode')
    elif kind == 'non-app':
        cache_row['type'] = 'document'
    elif kind == 'incomplete':
        cache_row['encrypted_content'] = {'malformed': 'ciphertext'}
    content = {'app_id': 'fitness', 'skill_id': 'search_classes', 'status': 'error',
               'error': 'Search failed. Please try again.', 'result_count': 0, 'embed_ids': []}
    if kind == 'invalid-content':
        content = {'status': 'error', 'reason': 'budget placeholder'}
    directus = SimpleNamespace(embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value=None)))
    _source_lookup(directus, {'hashed_user_id': owner_hash, 'hashed_team_id': None})
    redis = SimpleNamespace(delete=AsyncMock())

    async def redis_client():
        return redis

    cache = SimpleNamespace(get=AsyncMock(return_value=cache_row), client=redis_client(),
                            get_user_vault_key_id=AsyncMock(return_value='vault-key'))
    # Suppression paths alone access the Redis client property.
    if kind not in ('cancelled', 'raw', 'vault', 'missing-mode', 'non-app', 'incomplete'):
        cache.client.close()
        cache.client = None
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock(
        return_value=encode(content), side_effect=RuntimeError('decrypt failed') if kind == 'decrypt-error' else None))
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=encryption, user_id='owner', device_fingerprint_hash='device',
        payload={'embed_id': 'failed-skill', 'chat_id': 'chat'},
    )
    if kind == 'valid':
        payload = manager.send_personal_message.await_args.args[0]['payload']
        assert payload['status'] == 'error'
        assert payload['type'] == 'app_skill_use'
        assert payload['content'] == encode(content)
        redis.delete.assert_not_awaited()
    elif kind in ('cancelled', 'raw', 'vault', 'missing-mode', 'non-app', 'incomplete'):
        encryption.decrypt_with_user_key.assert_not_awaited()
        payload = manager.send_personal_message.await_args.args[0]['payload']
        if kind == 'cancelled':
            assert payload['status'] == 'cancelled'
        else:
            assert manager.send_personal_message.await_args.args[0]['type'] == 'error'
            assert 'content' not in payload
            assert all(call.args[0]['type'] != 'send_embed_data' for call in manager.send_personal_message.await_args_list)
        assert 'raw provider details' not in str(payload)
        redis.delete.assert_awaited_once()
    else:
        manager.send_personal_message.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=app-skills.assistant.bounded-private-failure,storage.privacy.ciphertext-boundary
@pytest.mark.anyio
@pytest.mark.parametrize('change', [
    {'encryption_mode': 'vault'}, {'encryption_mode': None}, {'encrypted_content': ''},
    {'encrypted_type': ''}, {'status': 'cancelled'}, {'status': 'processing'},
])
async def test_non_client_terminal_envelopes_are_not_served_as_readable_execution_errors(change):
    owner_hash = hashlib.sha256(b'owner').hexdigest()
    row = {'embed_id': 'failed-skill', 'hashed_user_id': owner_hash,
           'hashed_chat_id': hashlib.sha256(b'chat').hexdigest(),
           'status': 'error', 'encryption_mode': 'client',
           'encrypted_type': 'type-cipher', 'encrypted_content': 'content-cipher', **change}
    directus = SimpleNamespace(embed=SimpleNamespace(
        get_embed_by_id=AsyncMock(return_value=row), get_sync_embed_key_window_for_page=AsyncMock()))
    _source_lookup(directus, {'hashed_user_id': owner_hash, 'hashed_team_id': None})
    cache = SimpleNamespace(get=AsyncMock(return_value=None))
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=None, user_id='owner', device_fingerprint_hash='device',
        payload={'embed_id': 'failed-skill', 'chat_id': 'chat'},
    )
    directus.embed.get_sync_embed_key_window_for_page.assert_not_awaited()
    assert manager.send_personal_message.await_args.args[0] == {
        'type': 'error', 'payload': {'message': 'Embed not found', 'status': 404},
    }


SOURCE_EMBED_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_REQUEST_ID = "22222222-2222-4222-8222-222222222222"
SOURCE_CHAT_ID = "33333333-3333-4333-8333-333333333333"


def _source_discovery_fixture(case="owner", *, child=False, scoped_team=False):
    """Only explicit ACL metadata may be read on a source-only request."""
    from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id

    owner_hash = hashlib.sha256(b"owner").hexdigest()
    row = {"embed_id": SOURCE_EMBED_ID, "hashed_user_id": owner_hash,
           "hashed_chat_id": hashlib.sha256(SOURCE_CHAT_ID.encode()).hexdigest(), "status": "finished"}
    if child:
        row["parent_embed_id"] = "44444444-4444-4444-8444-444444444444"
    chat = {"id": SOURCE_CHAT_ID, "hashed_user_id": owner_hash, "hashed_team_id": None}
    if case == "foreign_embed":
        row["hashed_user_id"] = hashlib.sha256(b"foreign").hexdigest()
    elif case == "wrong_chat":
        row["hashed_chat_id"] = hashlib.sha256(b"other-chat").hexdigest()
    elif case == "cancelled":
        row["status"] = "cancelled"
    elif case == "missing_hash":
        row.pop("hashed_chat_id")
    elif case == "foreign_chat":
        chat["hashed_user_id"] = hashlib.sha256(b"foreign").hexdigest()
    elif case == "deleting":
        chat["storage_state"] = "deleting"
    elif case in ("team_source", "team_scoped", "team_removed", "team_mismatch"):
        chat["hashed_team_id"] = hash_id("team-1")

    if scoped_team:
        chat["hashed_team_id"] = hash_id("team-1")

    async def metadata(collection, params, **kwargs):
        assert kwargs == {"no_cache": True, "admin_required": True, "raise_on_error": True}
        assert params["limit"] == 2
        if collection == "embeds":
            assert params["fields"] == "embed_id,hashed_user_id,hashed_chat_id,status"
            assert params["filter"] == {"embed_id": {"_eq": SOURCE_EMBED_ID}}
            if case == "embed_read_error":
                raise RuntimeError("unavailable store")
            return [] if case == "missing" else [row]
        assert collection == "chats"
        assert params["fields"] == "id,hashed_user_id,hashed_team_id,storage_state"
        assert params["filter"] == {"id": {"_eq": SOURCE_CHAT_ID}}
        return [] if case == "deleted" else [chat]

    directus = SimpleNamespace(
        get_items=AsyncMock(side_effect=metadata),
        embed=SimpleNamespace(get_embed_by_id=AsyncMock(), get_sync_embed_key_window_for_page=AsyncMock()),
        chat=SimpleNamespace(get_chat_activity_candidates=AsyncMock(return_value=[{"id": SOURCE_CHAT_ID}]),
                             get_chat_metadata=AsyncMock(return_value={})),
        team=SimpleNamespace(require_team_role=AsyncMock(
            side_effect=TeamPermissionError("removed") if case == "team_removed" else None)),
    )
    cache = SimpleNamespace(get=AsyncMock(), get_user_vault_key_id=AsyncMock())
    encryption = SimpleNamespace(decrypt_with_user_key=AsyncMock())
    manager = SimpleNamespace(send_personal_message=AsyncMock())
    return directus, cache, encryption, manager


def _assert_source_only_reply(directus, cache, encryption, manager, chat_id, request_id=SOURCE_REQUEST_ID):
    manager.send_personal_message.assert_awaited_once_with(
        {"type": "embed_source", "payload": {"embed_id": SOURCE_EMBED_ID, "request_id": request_id,
                                              "chat_id": chat_id, "user_id": "owner"}}, "owner", "device",
    )
    # Source discovery cannot read content, operational cache, key wrappers or Vault plaintext.
    directus.embed.get_embed_by_id.assert_not_awaited()
    directus.embed.get_sync_embed_key_window_for_page.assert_not_awaited()
    cache.get.assert_not_awaited()
    cache.get_user_vault_key_id.assert_not_awaited()
    encryption.decrypt_with_user_key.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=storage.privacy.ciphertext-boundary,storage.cold.shared-team-authorized
@pytest.mark.anyio
@pytest.mark.parametrize("child", [False, True])
async def test_source_only_discovers_owned_personal_original_without_content_or_keys(child):
    directus, cache, encryption, manager = _source_discovery_fixture(child=child)
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=encryption, user_id="owner", device_fingerprint_hash="device",
        payload={"embed_id": SOURCE_EMBED_ID, "source_only": True, "request_id": SOURCE_REQUEST_ID},
    )
    directus.chat.get_chat_activity_candidates.assert_awaited_once_with("owner")
    assert [call.args[0] for call in directus.get_items.await_args_list] == ["embeds", "chats"]
    _assert_source_only_reply(directus, cache, encryption, manager, SOURCE_CHAT_ID)


# contract-test: direct surface=rest_api assertions=storage.privacy.ciphertext-boundary,storage.cold.shared-team-authorized
@pytest.mark.anyio
@pytest.mark.parametrize("case", ["missing", "foreign_embed", "foreign_chat", "deleted", "deleting",
                                       "cancelled", "missing_hash", "team_source", "embed_read_error"])
async def test_source_only_unavailable_or_unauthorized_discovery_is_uniformly_correlated(case):
    directus, cache, encryption, manager = _source_discovery_fixture(case)
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=encryption, user_id="owner", device_fingerprint_hash="device",
        payload={"embed_id": SOURCE_EMBED_ID, "source_only": True, "request_id": SOURCE_REQUEST_ID},
    )
    _assert_source_only_reply(directus, cache, encryption, manager, None)


# contract-test: direct surface=rest_api assertions=storage.privacy.ciphertext-boundary,storage.cold.shared-team-authorized
@pytest.mark.anyio
@pytest.mark.parametrize("case", ["team_scoped", "team_removed", "team_mismatch", "wrong_chat", "missing"])
async def test_source_only_scoped_team_discovery_preserves_current_acl(case):
    directus, cache, encryption, manager = _source_discovery_fixture(case, scoped_team=True)
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=encryption, user_id="owner", device_fingerprint_hash="device",
        payload={"embed_id": SOURCE_EMBED_ID, "chat_id": SOURCE_CHAT_ID,
                 "team_id": "wrong-team" if case == "team_mismatch" else "team-1",
                 "source_only": True, "request_id": SOURCE_REQUEST_ID},
    )
    _assert_source_only_reply(directus, cache, encryption, manager,
                             SOURCE_CHAT_ID if case == "team_scoped" else None)
    if case == "team_scoped":
        directus.team.require_team_role.assert_awaited_once_with(
            "team-1", "owner", {"owner", "admin", "member", "viewer"})


# contract-test: direct surface=rest_api assertions=storage.privacy.ciphertext-boundary
@pytest.mark.anyio
@pytest.mark.parametrize("request_id", [None, "", "not-a-uuid", "22222222222242228222222222222222", 42])
async def test_source_only_invalid_correlation_id_is_rejected_before_database_reads(request_id):
    directus, cache, encryption, manager = _source_discovery_fixture()
    await handle_request_embed(
        websocket=None, manager=manager, cache_service=cache, directus_service=directus,
        encryption_service=encryption, user_id="owner", device_fingerprint_hash="device",
        payload={"embed_id": SOURCE_EMBED_ID, "source_only": True, "request_id": request_id},
    )
    directus.get_items.assert_not_awaited()
    directus.chat.get_chat_activity_candidates.assert_not_awaited()
    _assert_source_only_reply(directus, cache, encryption, manager, None, request_id)
