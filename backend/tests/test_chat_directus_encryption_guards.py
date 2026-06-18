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


def _load_chat_methods_class():
    module_path = Path(__file__).resolve().parents[1] / "core" / "api" / "app" / "services" / "directus" / "chat_methods.py"
    spec = importlib.util.spec_from_file_location("chat_methods_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ChatMethods


def _client_ciphertext() -> str:
    raw = b"OM" + bytes.fromhex("1a5b3b7c") + (b"0" * 12) + b"ciphertext-ok"
    return base64.b64encode(raw).decode("ascii")


@pytest.mark.asyncio
async def test_create_chat_rejects_vault_encrypted_metadata_before_directus_write() -> None:
    ChatMethods = _load_chat_methods_class()
    directus = SimpleNamespace(create_item=AsyncMock())
    methods = ChatMethods(directus)

    with pytest.raises(ValueError, match="Vault ciphertext is not allowed"):
        await methods.create_chat_in_directus({"id": "chat-1", "encrypted_title": "vault:v1:ciphertext"})

    directus.create_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_chat_fields_rejects_vault_encrypted_metadata_before_directus_write() -> None:
    ChatMethods = _load_chat_methods_class()
    directus = SimpleNamespace(update_item=AsyncMock())
    methods = ChatMethods(directus)

    with pytest.raises(ValueError, match="Vault ciphertext is not allowed"):
        await methods.update_chat_fields_in_directus("chat-1", {"encrypted_chat_summary": "vault:v1:ciphertext"})

    directus.update_item.assert_not_awaited()


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
