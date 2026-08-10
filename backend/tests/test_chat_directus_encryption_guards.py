# backend/tests/test_chat_directus_encryption_guards.py
#
# Directus chat/message collections are zero-knowledge persistence surfaces.
# These tests prove runtime write methods reject server-side Vault ciphertext
# before it can be stored in chat metadata or message content fields.

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _load_chat_methods_class():
    module_path = Path(__file__).resolve().parents[1] / "core" / "api" / "app" / "services" / "directus" / "chat_methods.py"
    spec = importlib.util.spec_from_file_location("chat_methods_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ChatMethods


def _load_api_methods_module():
    module_path = Path(__file__).resolve().parents[1] / "core" / "api" / "app" / "services" / "directus" / "api_methods.py"
    spec = importlib.util.spec_from_file_location("directus_api_methods_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _client_ciphertext() -> str:
    raw = b"OM" + bytes.fromhex("1a5b3b7c") + (b"0" * 12) + b"ciphertext-ok"
    return base64.b64encode(raw).decode("ascii")


def test_legacy_import_chat_source_fails_closed_without_direct_plaintext_writes() -> None:
    settings_path = Path(__file__).resolve().parents[1] / "core" / "api" / "app" / "routes" / "settings.py"
    source = settings_path.read_text()
    start = source.index("async def import_chat(")
    end = source.index("# ---------------------------------------------------------------------------\n# Issue-Report", start)
    import_chat_source = source[start:end]

    assert "status_code=503" in import_chat_source
    assert "client-encrypted import flow" in import_chat_source
    assert 'create_item("chats"' not in import_chat_source
    assert "create_item('chats'" not in import_chat_source
    assert 'create_item("messages"' not in import_chat_source
    assert "create_item('messages'" not in import_chat_source


@pytest.mark.anyio
async def test_low_level_create_item_rejects_plaintext_chat_fields_before_directus_write() -> None:
    api_methods = _load_api_methods_module()
    directus = SimpleNamespace(base_url="http://cms:8055", _make_api_request=AsyncMock())

    success, result = await api_methods.create_item(directus, "chats", {
        "id": "chat-1",
        "hashed_user_id": "hashed-user",
        "title": "Plaintext title",
        "summary": "Plaintext summary",
    })

    assert success is False
    assert result["error"] == "plaintext_private_fields_forbidden"
    assert result["fields"] == ["summary", "title"]
    directus._make_api_request.assert_not_awaited()


@pytest.mark.anyio
async def test_low_level_create_item_rejects_plaintext_message_fields_before_directus_write() -> None:
    api_methods = _load_api_methods_module()
    directus = SimpleNamespace(base_url="http://cms:8055", _make_api_request=AsyncMock())

    success, result = await api_methods.create_item(directus, "messages", {
        "id": "message-1",
        "chat_id": "chat-1",
        "role": "user",
        "content": "Plaintext message",
        "thinking": "Plaintext thinking",
    })

    assert success is False
    assert result["error"] == "plaintext_private_fields_forbidden"
    assert result["fields"] == ["content", "thinking"]
    directus._make_api_request.assert_not_awaited()


@pytest.mark.anyio
async def test_low_level_create_item_accepts_client_encrypted_message_fields() -> None:
    api_methods = _load_api_methods_module()
    response = SimpleNamespace(
        status_code=200,
        json=lambda: {"data": {"id": "message-1", "encrypted_content": _client_ciphertext()}},
    )
    directus = SimpleNamespace(
        base_url="http://cms:8055",
        _make_api_request=AsyncMock(return_value=response),
    )

    success, result = await api_methods.create_item(directus, "messages", {
        "id": "message-1",
        "chat_id": "chat-1",
        "role": "user",
        "encrypted_content": _client_ciphertext(),
    })

    assert success is True
    assert result["id"] == "message-1"
    directus._make_api_request.assert_awaited_once()


@pytest.mark.anyio
async def test_create_chat_rejects_vault_encrypted_metadata_before_directus_write() -> None:
    ChatMethods = _load_chat_methods_class()
    directus = SimpleNamespace(create_item=AsyncMock())
    methods = ChatMethods(directus)

    with pytest.raises(ValueError, match="Vault ciphertext is not allowed"):
        await methods.create_chat_in_directus({"id": "chat-1", "encrypted_title": "vault:v1:ciphertext"})

    directus.create_item.assert_not_awaited()


@pytest.mark.anyio
async def test_create_chat_treats_directus_unique_field_error_as_duplicate_race() -> None:
    ChatMethods = _load_chat_methods_class()
    cache = SimpleNamespace(delete=AsyncMock(), increment_stat=AsyncMock())
    directus = SimpleNamespace(
        cache=cache,
        create_item=AsyncMock(return_value=(
            False,
            {
                "status_code": 400,
                "text": '{"errors":[{"message":"Value for field \\"id\\" in collection \\"chats\\" has to be unique."}]}',
            },
        )),
        update_item=AsyncMock(return_value={"id": "chat-1", "encrypted_title": "client-encrypted-title"}),
    )
    methods = ChatMethods(directus)

    result, is_duplicate = await methods.create_chat_in_directus({
        "id": "chat-1",
        "encrypted_title": "client-encrypted-title",
        "messages_v": 1,
    })

    assert is_duplicate is True
    assert result == {"id": "chat-1", "encrypted_title": "client-encrypted-title"}
    directus.update_item.assert_awaited_once_with(
        "chats",
        "chat-1",
        {"encrypted_title": "client-encrypted-title", "messages_v": 1},
    )


@pytest.mark.anyio
async def test_update_chat_fields_rejects_vault_encrypted_metadata_before_directus_write() -> None:
    ChatMethods = _load_chat_methods_class()
    directus = SimpleNamespace(update_item=AsyncMock())
    methods = ChatMethods(directus)

    with pytest.raises(ValueError, match="Vault ciphertext is not allowed"):
        await methods.update_chat_fields_in_directus("chat-1", {"encrypted_chat_summary": "vault:v1:ciphertext"})

    directus.update_item.assert_not_awaited()


@pytest.mark.anyio
async def test_create_message_rejects_vault_encrypted_content_before_directus_write() -> None:
    ChatMethods = _load_chat_methods_class()
    directus = SimpleNamespace(create_item=AsyncMock())
    methods = ChatMethods(directus)

    with pytest.raises(ValueError, match="Vault ciphertext"):
        await methods.create_message_in_directus({
            "message_id": "msg-1",
            "chat_id": "chat-1",
            "role": "user",
            "encrypted_content": "vault:v1:ciphertext",
        })

    directus.create_item.assert_not_awaited()


@pytest.mark.anyio
async def test_create_message_accepts_client_encrypted_content() -> None:
    ChatMethods = _load_chat_methods_class()
    cache = SimpleNamespace(delete=AsyncMock(), increment_stat=AsyncMock())
    directus = SimpleNamespace(
        cache=cache,
        create_item=AsyncMock(return_value=(True, {"id": "directus-msg", "client_message_id": "msg-1"})),
    )
    methods = ChatMethods(directus)

    result = await methods.create_message_in_directus({
        "message_id": "msg-1",
        "chat_id": "chat-1",
        "role": "user",
        "encrypted_content": _client_ciphertext(),
    })

    assert result == {"id": "directus-msg", "client_message_id": "msg-1"}
    directus.create_item.assert_awaited_once()
