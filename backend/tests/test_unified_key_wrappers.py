"""
Regression tests for unified key-wrapper backend migration helpers.

Production chat rows currently store a chat key wrapped by the user's master
key. The first migration slice copies that ciphertext into a canonical wrapper
row without decrypting it and without using wrapper existence as authorization.
"""

import hashlib
import logging

import pytest

from backend.core.api.app.services.directus.chat_key_wrapper_methods import (
    ChatKeyWrapperMethods,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class FakeChatMethods:
    def __init__(self, owned_chat_ids: set[str]) -> None:
        self.owned_chat_ids = owned_chat_ids

    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return chat_id in self.owned_chat_ids and user_id == "user-1"


class FakeDirectusService:
    def __init__(self) -> None:
        self.chat = FakeChatMethods({"chat-1"})
        self.created_items: list[tuple[str, dict, bool]] = []
        self.requests: list[tuple[str, dict, bool]] = []
        self.wrapper_rows: list[dict] = []
        self.chat_rows: list[dict] = [
            {
                "id": "chat-1",
                "hashed_user_id": _hash("user-1"),
                "encrypted_chat_key": "ciphertext-master-wrapped-chat-key-1",
            },
            {
                "id": "chat-without-key",
                "hashed_user_id": _hash("user-1"),
                "encrypted_chat_key": "",
            },
        ]

    async def get_items(
        self,
        collection: str,
        params: dict,
        admin_required: bool = False,
        **_kwargs,
    ):
        self.requests.append((collection, params, admin_required))

        if collection == "chats":
            return self.chat_rows[: params.get("limit", len(self.chat_rows))]

        if collection != "chat_key_wrappers":
            raise AssertionError(f"Unexpected collection {collection}")

        rows = list(self.wrapper_rows)
        for param_key, param_value in params.items():
            if not param_key.startswith("filter[") or "][_eq]" not in param_key:
                continue
            field = param_key.removeprefix("filter[").split("]", 1)[0]
            rows = [row for row in rows if row.get(field) == param_value]
        limit = params.get("limit", len(rows))
        return rows if limit == -1 else rows[:limit]

    async def create_item(
        self,
        collection: str,
        record: dict,
        admin_required: bool = False,
    ):
        self.created_items.append((collection, record.copy(), admin_required))
        created = {"id": f"wrapper-{len(self.wrapper_rows) + 1}", **record}
        self.wrapper_rows.append(created)
        return True, created


@pytest.mark.anyio
async def test_backfill_copies_chat_key_ciphertext_without_duplication(caplog):
    directus = FakeDirectusService()
    methods = ChatKeyWrapperMethods(directus)

    caplog.set_level(logging.INFO)

    first = await methods.backfill_master_wrappers(limit=50)
    second = await methods.backfill_master_wrappers(limit=50)

    assert first == {"checked": 2, "created": 1, "skipped": 1, "failed": 0}
    assert second == {"checked": 2, "created": 0, "skipped": 2, "failed": 0}
    assert len(directus.created_items) == 1

    collection, record, admin_required = directus.created_items[0]
    assert collection == "chat_key_wrappers"
    assert admin_required is True
    assert record == {
        "hashed_chat_id": _hash("chat-1"),
        "hashed_user_id": _hash("user-1"),
        "key_type": "master",
        "encrypted_chat_key": "ciphertext-master-wrapped-chat-key-1",
        "wrapper_version": 1,
        "created_at": record["created_at"],
    }

    assert "ciphertext-master-wrapped-chat-key-1" not in caplog.text
    assert all("encrypted_chat_key" not in message for message in caplog.messages)


@pytest.mark.anyio
async def test_backfill_dry_run_does_not_create_wrappers():
    directus = FakeDirectusService()
    methods = ChatKeyWrapperMethods(directus)

    result = await methods.backfill_master_wrappers(limit=50, dry_run=True)

    assert result == {"checked": 2, "created": 1, "skipped": 1, "failed": 0}
    assert directus.created_items == []
    assert directus.wrapper_rows == []


@pytest.mark.anyio
async def test_list_authorized_wrappers_requires_chat_ownership():
    directus = FakeDirectusService()
    directus.wrapper_rows = [
        {
            "id": "wrapper-1",
            "hashed_chat_id": _hash("chat-1"),
            "hashed_user_id": _hash("user-1"),
            "key_type": "master",
            "encrypted_chat_key": "ciphertext-master-wrapped-chat-key-1",
        }
    ]
    methods = ChatKeyWrapperMethods(directus)

    authorized = await methods.list_authorized_wrappers("chat-1", "user-1")
    requests_after_authorized_read = len(directus.requests)
    unauthorized = await methods.list_authorized_wrappers("chat-1", "user-2")

    assert [row["id"] for row in authorized] == ["wrapper-1"]
    assert unauthorized == []
    assert len(directus.requests) == requests_after_authorized_read
