# backend/tests/test_code_execution.py
#
# Regression tests for the web-app Code Run collector.
# Code Run must use server-readable Redis/Vault cache for recent chats, while
# Directus remains client-encrypted storage and is never decrypted with Vault.
# Older chats can retry with code decrypted on the authenticated client.

from __future__ import annotations

import hashlib
import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from toon_format import encode

from backend.apps.code.tasks.run_code_task import RUN_CREDITS_PER_MINUTE as TASK_RUN_CREDITS_PER_MINUTE
from backend.apps.code.tasks.run_code_task import _charge_run_credits
from backend.core.api.app.routes.code_execution import (
    CLIENT_CONTENT_REQUIRED_CODE,
    CodeRunClientAttachment,
    CodeRunClientFile,
    RUN_CREDITS_PER_MINUTE as ROUTE_RUN_CREDITS_PER_MINUTE,
    _collect_code_files,
)


CHAT_ID = "chat-1"
TARGET_EMBED_ID = "embed-target"
USER_ID = "user-1"
USER_HASH = hashlib.sha256(USER_ID.encode()).hexdigest()
CHAT_HASH = hashlib.sha256(CHAT_ID.encode()).hexdigest()
MESSAGE_ID = "message-1"


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
        "message_id": MESSAGE_ID,
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
        [],
        None,
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
            [],
            None,
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
        [],
        None,
        _user(),
        FakeCache([], {}),
        FakeDirectus({TARGET_EMBED_ID: _metadata()}),
        FakeEncryption(),
    )

    assert target_path == "client.py"
    assert files == [{"path": "client.py", "content": "print('client')", "language": "python", "is_target": True}]


@pytest.mark.anyio
async def test_collect_code_files_filters_cached_files_to_selected_embeds() -> None:
    target_toon = encode({"type": "code", "code": "print('target')", "language": "python", "filename": "main.py"})
    helper_toon = encode({"type": "code", "code": "print('helper')", "language": "python", "filename": "helper.py"})
    skipped_toon = encode({"type": "code", "code": "print('skip')", "language": "python", "filename": "skip.py"})
    embeds = {
        TARGET_EMBED_ID: _metadata(encrypted_content=f"vault:{target_toon}"),
        "embed-helper": {**_metadata(encrypted_content=f"vault:{helper_toon}"), "embed_id": "embed-helper"},
        "embed-skip": {**_metadata(encrypted_content=f"vault:{skipped_toon}"), "embed_id": "embed-skip"},
    }

    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [],
        [],
        [TARGET_EMBED_ID, "embed-helper"],
        _user(),
        FakeCache([TARGET_EMBED_ID, "embed-helper", "embed-skip"], embeds),
        FakeDirectus({}),
        FakeEncryption(),
    )

    assert target_path == "main.py"
    assert [file["path"] for file in files] == ["main.py", "helper.py"]


@pytest.mark.anyio
async def test_collect_code_files_accepts_selected_client_attachment_fallback() -> None:
    target_toon = encode({"type": "code", "code": "print('target')", "language": "python", "filename": "main.py"})
    attachment_id = "embed-attachment"
    attachment_metadata = {**_metadata(), "embed_id": attachment_id}

    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [],
        [
            CodeRunClientAttachment(
                embed_id=attachment_id,
                path="data/input.txt",
                content_base64=base64.b64encode(b"hello").decode("ascii"),
                mime_type="text/plain",
            )
        ],
        [TARGET_EMBED_ID, attachment_id],
        _user(),
        FakeCache([TARGET_EMBED_ID], {TARGET_EMBED_ID: _metadata(encrypted_content=f"vault:{target_toon}")}),
        FakeDirectus({attachment_id: attachment_metadata}),
        FakeEncryption(),
    )

    assert target_path == "main.py"
    assert files[0]["path"] == "main.py"
    assert files[1]["path"] == "inputs/data/input.txt"
    assert base64.b64decode(files[1]["content_base64"]) == b"hello"


def test_code_run_cost_is_five_credits_per_minute() -> None:
    assert ROUTE_RUN_CREDITS_PER_MINUTE == 5
    assert TASK_RUN_CREDITS_PER_MINUTE == 5


@pytest.mark.anyio
async def test_charge_run_credits_links_usage_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, json: dict, headers: dict):
            requests.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr("backend.apps.code.tasks.run_code_task.httpx.AsyncClient", FakeAsyncClient)

    charged = await _charge_run_credits(
        {
            "user_id": USER_ID,
            "user_id_hash": USER_HASH,
            "chat_id": CHAT_ID,
            "message_id": MESSAGE_ID,
            "target_embed_id": TARGET_EMBED_ID,
            "target_path": "main.py",
            "files": [{"path": "main.py"}],
        },
        5,
        "execution-1",
        {"billing_phase": "initial_minute", "charged_minutes": 1},
    )

    assert charged == 5
    assert requests[0]["json"]["credits"] == 5
    assert requests[0]["json"]["app_id"] == "code"
    assert requests[0]["json"]["skill_id"] == "run"
    assert requests[0]["json"]["usage_details"]["chat_id"] == CHAT_ID
    assert requests[0]["json"]["usage_details"]["message_id"] == MESSAGE_ID
    assert requests[0]["json"]["usage_details"]["credits_per_minute"] == 5
