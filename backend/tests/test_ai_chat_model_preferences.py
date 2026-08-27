# backend/tests/test_ai_chat_model_preferences.py
#
# Focused unit coverage for the encrypted user/chat AI model preference store.
# These tests prove the backend service accepts only opaque Format D ciphertext,
# scopes rows by hashed owner plus chat ID, and uses preference_v compare-and-set
# updates without adding durable plaintext model fields.

from __future__ import annotations

import base64
from typing import Any

import pytest

from backend.core.api.app.services.directus.chat_model_preference_methods import (
    ChatModelPreferenceConflictError,
    ChatModelPreferenceMethods,
    ChatModelPreferenceValidationError,
    hash_user_id,
    validate_encrypted_selected_ai_model,
)


def _format_d_ciphertext() -> str:
    return base64.b64encode(b"\x01" * 28).decode("ascii")


class FakeDirectus:
    def __init__(self, rows: list[dict[str, Any]] | None = None):
        self.rows = rows or []
        self.conditional_update_kwargs: dict[str, Any] | None = None

    async def get_items(self, collection: str, params: dict[str, Any], **_kwargs: Any) -> list[dict[str, Any]]:
        assert collection == "user_chat_preferences"
        filter_data = params["filter"]
        hashed_user_id = filter_data["hashed_user_id"]["_eq"]
        chat_id = filter_data["chat_id"]["_eq"]
        return [
            row.copy()
            for row in self.rows
            if row.get("hashed_user_id") == hashed_user_id and row.get("chat_id") == chat_id
        ][:1]

    async def create_item(self, collection: str, payload: dict[str, Any], **_kwargs: Any) -> tuple[bool, dict[str, Any]]:
        assert collection == "user_chat_preferences"
        row = {"id": "pref-created", **payload}
        self.rows.append(row)
        return True, row.copy()

    async def update_item_if_version(
        self,
        collection: str,
        item_id: str,
        data: dict[str, Any],
        expected_version: int,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        assert collection == "user_chat_preferences"
        self.conditional_update_kwargs = kwargs
        for row in self.rows:
            if row.get("id") == item_id and row.get("preference_v") == expected_version:
                row.update(data)
                return row.copy()
        return None


class EmptyResponseAfterCasDirectus(FakeDirectus):
    async def update_item_if_version(
        self,
        collection: str,
        item_id: str,
        data: dict[str, Any],
        expected_version: int,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        await super().update_item_if_version(collection, item_id, data, expected_version, **kwargs)
        return None

    async def update_item(self, collection: str, item_id: str, data: dict[str, Any], **_kwargs: Any) -> dict[str, Any] | None:
        assert collection == "user_chat_preferences"
        for row in self.rows:
            if row.get("id") == item_id:
                row.update(data)
                return row.copy()
        return None


# contract-test: direct surface=rest_api assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
@pytest.mark.asyncio
async def test_chat_model_preference_create_stores_only_ciphertext_and_owner_hash() -> None:
    directus = FakeDirectus()
    methods = ChatModelPreferenceMethods(directus)  # type: ignore[arg-type]
    ciphertext = _format_d_ciphertext()

    record = await methods.upsert_preference(
        user_id="user-1",
        chat_id="chat-1",
        encrypted_selected_ai_model=ciphertext,
        expected_preference_v=0,
    )

    assert record["preference_v"] == 1
    assert directus.rows == [
        {
            "id": "pref-created",
            "hashed_user_id": hash_user_id("user-1"),
            "chat_id": "chat-1",
            "encrypted_selected_ai_model": ciphertext,
            "preference_v": 1,
            "updated_at": record["updated_at"],
        }
    ]
    assert "selected_ai_model" not in directus.rows[0]
    assert "model_id" not in directus.rows[0]


# contract-test: direct surface=rest_api assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
@pytest.mark.asyncio
async def test_chat_model_preference_update_uses_owner_scoped_cas() -> None:
    directus = FakeDirectus([
        {
            "id": "pref-1",
            "hashed_user_id": hash_user_id("user-1"),
            "chat_id": "chat-1",
            "encrypted_selected_ai_model": _format_d_ciphertext(),
            "preference_v": 4,
            "updated_at": 10,
        }
    ])
    methods = ChatModelPreferenceMethods(directus)  # type: ignore[arg-type]
    next_ciphertext = base64.b64encode(b"\x02" * 28).decode("ascii")

    record = await methods.upsert_preference(
        user_id="user-1",
        chat_id="chat-1",
        encrypted_selected_ai_model=next_ciphertext,
        expected_preference_v=4,
    )

    assert record["preference_v"] == 5
    assert record["encrypted_selected_ai_model"] == next_ciphertext
    assert directus.conditional_update_kwargs == {
        "version_field": "preference_v",
        "extra_filters": {"chat_id": "chat-1"},
        "owner_hash_field": "hashed_user_id",
        "owner_hash": hash_user_id("user-1"),
        "admin_required": True,
    }


# contract-test: direct surface=rest_api assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
@pytest.mark.asyncio
async def test_chat_model_preference_cas_accepts_directus_empty_success_response() -> None:
    directus = EmptyResponseAfterCasDirectus([
        {
            "id": "pref-1",
            "hashed_user_id": hash_user_id("user-1"),
            "chat_id": "chat-1",
            "encrypted_selected_ai_model": _format_d_ciphertext(),
            "preference_v": 1,
            "updated_at": 10,
        }
    ])
    methods = ChatModelPreferenceMethods(directus)  # type: ignore[arg-type]
    next_ciphertext = base64.b64encode(b"\x02" * 28).decode("ascii")

    record = await methods.upsert_preference(
        user_id="user-1",
        chat_id="chat-1",
        encrypted_selected_ai_model=next_ciphertext,
        expected_preference_v=1,
    )

    assert record["preference_v"] == 2
    assert record["encrypted_selected_ai_model"] == next_ciphertext


# contract-test: direct surface=rest_api assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
def test_chat_model_preference_rejects_plaintext_selection() -> None:
    with pytest.raises(ChatModelPreferenceValidationError):
        validate_encrypted_selected_ai_model("google/gemini-3.7-flash")

    with pytest.raises(ChatModelPreferenceValidationError):
        validate_encrypted_selected_ai_model("auto")


# contract-test: direct surface=rest_api assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
@pytest.mark.asyncio
async def test_chat_model_preference_conflict_returns_server_record() -> None:
    server_record = {
        "id": "pref-1",
        "hashed_user_id": hash_user_id("user-1"),
        "chat_id": "chat-1",
        "encrypted_selected_ai_model": _format_d_ciphertext(),
        "preference_v": 2,
        "updated_at": 10,
    }
    methods = ChatModelPreferenceMethods(FakeDirectus([server_record]))  # type: ignore[arg-type]

    with pytest.raises(ChatModelPreferenceConflictError) as exc_info:
        await methods.upsert_preference(
            user_id="user-1",
            chat_id="chat-1",
            encrypted_selected_ai_model=base64.b64encode(b"\x03" * 28).decode("ascii"),
            expected_preference_v=1,
        )

    assert exc_info.value.server_record == server_record
