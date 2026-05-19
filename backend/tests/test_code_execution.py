# backend/tests/test_code_execution.py
#
# Regression tests for the web-app Code Run collector.
# Code Run must use server-readable Redis/Vault cache for recent chats, while
# Directus remains client-encrypted storage and is never decrypted with Vault.
# Older chats can retry with code decrypted on the authenticated client.

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from toon_format import encode

from backend.core.api.app.routes.code_execution import (
    CLIENT_CONTENT_REQUIRED_CODE,
    CodeRunClientFile,
    _collect_code_files,
)


CHAT_ID = "chat-1"
TARGET_EMBED_ID = "embed-target"
USER_ID = "user-1"
USER_HASH = hashlib.sha256(USER_ID.encode()).hexdigest()
CHAT_HASH = hashlib.sha256(CHAT_ID.encode()).hexdigest()


class FakeRedis:
    def __init__(self, embeds: dict[str, dict]):
        self.embeds = embeds

    async def get(self, key: str):
        embed_id = key.removeprefix("embed:")
        embed = self.embeds.get(embed_id)
        return json.dumps(embed).encode() if embed else None


class FakeCache:
    def __init__(self, embed_ids: list[str], embeds: dict[str, dict]):
        self.embed_ids = embed_ids
        self.embeds = embeds
        self.redis = FakeRedis(embeds)

    @property
    def client(self):
        async def _client():
            return self.redis

        return _client()

    async def get_chat_embed_ids(self, chat_id: str) -> list[str]:
        return self.embed_ids if chat_id == CHAT_ID else []

    async def get_embed_from_cache(self, embed_id: str):
        return self.embeds.get(embed_id)


class FakeDirectusEmbed:
    def __init__(self, embeds: dict[str, dict]):
        self.embeds = embeds

    async def get_embed_by_id(self, embed_id: str):
        return self.embeds.get(embed_id)


class FakeDirectus:
    def __init__(self, embeds: dict[str, dict]):
        self.embed = FakeDirectusEmbed(embeds)


class FakeEncryption:
    async def decrypt_with_user_key(self, ciphertext: str, key_id: str):
        if ciphertext.startswith("vault:"):
            return ciphertext.removeprefix("vault:")
        raise AssertionError("Code Run must not try to Vault-decrypt Directus client ciphertext")


def _user():
    return SimpleNamespace(id=USER_ID, vault_key_id="vault-key")


def _metadata(encrypted_content: str = "client-ciphertext") -> dict:
    return {
        "embed_id": TARGET_EMBED_ID,
        "hashed_user_id": USER_HASH,
        "hashed_chat_id": CHAT_HASH,
        "encrypted_content": encrypted_content,
        "encryption_mode": "client",
        "status": "finished",
    }


@pytest.mark.anyio
async def test_collect_code_files_uses_vault_encrypted_recent_cache() -> None:
    toon = encode({"type": "code", "code": "print('ok')", "language": "python", "filename": "main.py"})
    cached = _metadata(encrypted_content=f"vault:{toon}")

    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [],
        _user(),
        FakeCache([TARGET_EMBED_ID], {TARGET_EMBED_ID: cached}),
        FakeDirectus({}),
        FakeEncryption(),
    )

    assert target_path == "main.py"
    assert files == [{"path": "main.py", "content": "print('ok')", "language": "python", "is_target": True}]


@pytest.mark.anyio
async def test_collect_code_files_requests_client_content_for_directus_only_embed() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await _collect_code_files(
            CHAT_ID,
            TARGET_EMBED_ID,
            [],
            _user(),
            FakeCache([], {}),
            FakeDirectus({TARGET_EMBED_ID: _metadata()}),
            FakeEncryption(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == CLIENT_CONTENT_REQUIRED_CODE


@pytest.mark.anyio
async def test_collect_code_files_accepts_validated_client_fallback() -> None:
    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [CodeRunClientFile(embed_id=TARGET_EMBED_ID, code="print('client')", language="python", filename="client.py", is_target=True)],
        _user(),
        FakeCache([], {}),
        FakeDirectus({TARGET_EMBED_ID: _metadata()}),
        FakeEncryption(),
    )

    assert target_path == "client.py"
    assert files == [{"path": "client.py", "content": "print('client')", "language": "python", "is_target": True}]
