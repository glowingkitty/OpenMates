# backend/tests/test_notebook_run_outputs.py
#
# Regression tests for encrypted notebook-run output sidecars. The server stores
# only routeable metadata and ciphertext; canonical notebook embeds are not
# mutated by runtime output sync.

from __future__ import annotations

import hashlib

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers.notebook_run_output_handlers import _impl_upsert


CHAT_ID = "chat-1"
NOTEBOOK_EMBED_ID = "notebook-1"
USER_ID = "user-1"
USER_HASH = hashlib.sha256(USER_ID.encode()).hexdigest()
CHAT_HASH = hashlib.sha256(CHAT_ID.encode()).hexdigest()


class FakeCache:
    async def get_chat_embed_ids(self, chat_id: str) -> list[str]:
        return [NOTEBOOK_EMBED_ID] if chat_id == CHAT_ID else []


class FakeDirectusChat:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return chat_id == CHAT_ID and user_id == USER_ID


class FakeDirectusEmbed:
    async def get_embed_by_id(self, embed_id: str):
        if embed_id != NOTEBOOK_EMBED_ID:
            return None
        return {
            "embed_id": NOTEBOOK_EMBED_ID,
            "hashed_user_id": USER_HASH,
            "hashed_chat_id": CHAT_HASH,
            "type": "notebook",
            "status": "finished",
        }


class FakeDirectus:
    def __init__(self) -> None:
        self.chat = FakeDirectusChat()
        self.embed = FakeDirectusEmbed()
        self.items: dict[str, dict] = {}

    async def get_items(self, collection: str, params: dict, admin_required: bool = False):
        assert collection == "notebook_run_outputs"
        return list(self.items.values())

    async def create_item(self, collection: str, row: dict, admin_required: bool = False):
        assert collection == "notebook_run_outputs"
        self.items[row["id"]] = row
        return row

    async def update_item(self, collection: str, item_id: str, row: dict):
        assert collection == "notebook_run_outputs"
        self.items[item_id] = {**self.items.get(item_id, {}), **row}
        return self.items[item_id]


class FakeManager:
    def __init__(self) -> None:
        self.personal_messages: list[dict] = []
        self.broadcasts: list[dict] = []

    async def send_personal_message(self, message: dict, user_id: str, device_fingerprint_hash: str):
        self.personal_messages.append(message)

    async def broadcast_to_user(self, message: dict, user_id: str, exclude_device_hash: str | None = None):
        self.broadcasts.append(message)


@pytest.mark.anyio
async def test_notebook_run_output_upsert_stores_ciphertext_sidecar() -> None:
    manager = FakeManager()
    directus = FakeDirectus()

    await _impl_upsert(
        manager,
        FakeCache(),
        directus,
        USER_ID,
        "device-1",
        {
            "chat_id": CHAT_ID,
            "notebook_embed_id": NOTEBOOK_EMBED_ID,
            "id": "output-1",
            "source_version": "v1",
            "key_version": 1,
            "encrypted_payload": "ciphertext",
            "created_at": 100,
            "updated_at": 101,
        },
    )

    assert directus.items["output-1"]["encrypted_payload"] == "ciphertext"
    assert directus.items["output-1"]["notebook_embed_id"] == NOTEBOOK_EMBED_ID
    assert manager.broadcasts[0]["type"] == "notebook_run_output_synced"


@pytest.mark.anyio
async def test_notebook_run_output_rejects_wrong_chat() -> None:
    manager = FakeManager()

    await _impl_upsert(
        manager,
        FakeCache(),
        FakeDirectus(),
        USER_ID,
        "device-1",
        {
            "chat_id": "other-chat",
            "notebook_embed_id": NOTEBOOK_EMBED_ID,
            "encrypted_payload": "ciphertext",
            "created_at": 100,
            "updated_at": 101,
        },
    )

    assert manager.personal_messages
    assert "permission" in manager.personal_messages[0]["payload"]["message"].lower()
