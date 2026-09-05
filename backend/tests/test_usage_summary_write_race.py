# backend/tests/test_usage_summary_write_race.py
#
# Regression tests for billing usage summary write races. The raw usage entry is
# authoritative, but summary helper rows feed the billing usage UI and must not
# split one user/identifier/period identity into multiple rows under concurrency.
# The tests simulate Directus duplicate-key create failures without live services.

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest


def _load_usage_methods_class():
    module_path = Path(__file__).resolve().parents[1] / "core/api/app/services/directus/usage.py"
    spec = importlib.util.spec_from_file_location("usage_methods_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.UsageMethods


UsageMethods = _load_usage_methods_class()


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.values.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self.values[key] = value

    async def delete(self, _key: str) -> None:
        return None


class DuplicateCreateSDK:
    def __init__(self, existing_row: dict[str, Any]) -> None:
        self.existing_row = existing_row
        self.cache = FakeCache()
        self.read_count = 0
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[str, str, dict[str, Any]]] = []

    async def get_items(self, collection: str, params: dict[str, Any] | None = None, **kwargs: Any):
        self.read_count += 1
        if self.read_count == 1:
            return []
        return [self.existing_row]

    async def create_item(self, collection: str, payload: dict[str, Any]):
        self.created.append(payload)
        return False, {"errors": [{"message": "duplicate key value violates unique constraint"}]}

    async def update_item(self, collection: str, item_id: str, payload: dict[str, Any]):
        self.updated.append((collection, item_id, payload))
        return True, {"id": item_id, **payload}


class FakeEncryption:
    async def decrypt_with_user_key(self, ciphertext: str, _key_id: str):
        return ciphertext.removeprefix("enc:")


class ReconciliationSDK:
    def __init__(self) -> None:
        self.cache = FakeCache()
        self.timestamp = int(datetime.now().timestamp())
        self.date = datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d")

    async def get_items(self, collection: str, params: dict[str, Any] | None = None, **kwargs: Any):
        if collection == "usage_daily_chat_summaries":
            return [
                {"id": "stale", "user_id_hash": "user-a", "chat_id": "root-chat", "date": self.date, "total_credits": 10, "entry_count": 1, "updated_at": 100}
            ]
        if collection == "usage_daily_api_key_summaries":
            return []
        if collection == "usage":
            return [
                {"id": "ai", "user_id_hash": "user-a", "source": "chat", "chat_id": "root-chat", "root_chat_id": "root-chat", "created_at": self.timestamp, "updated_at": 103, "encrypted_credits_costs_total": "enc:55"},
                {"id": "images", "user_id_hash": "user-a", "source": "chat", "chat_id": "child-images", "root_chat_id": "root-chat", "created_at": self.timestamp, "updated_at": 102, "encrypted_credits_costs_total": "enc:10"},
                {"id": "news", "user_id_hash": "user-a", "source": "chat", "chat_id": "child-news", "root_chat_id": "root-chat", "created_at": self.timestamp, "updated_at": 101, "encrypted_credits_costs_total": "enc:10"},
                {"id": "other-user", "user_id_hash": "user-b", "source": "chat", "chat_id": "root-chat", "root_chat_id": "root-chat", "created_at": self.timestamp, "updated_at": 104, "encrypted_credits_costs_total": "enc:999"},
            ]
        return []


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=billing.surface.semantic-parity
async def test_daily_summary_duplicate_create_retries_as_update() -> None:
    sdk = DuplicateCreateSDK({"id": "existing-daily", "total_credits": 10, "entry_count": 2})
    usage = UsageMethods(sdk=sdk, encryption_service=FakeEncryption())

    await usage._update_daily_summary(
        collection="usage_daily_chat_summaries",
        user_id_hash="user-a",
        identifier_key="chat_id",
        identifier_value="chat-1",
        date_str="2026-07-29",
        credits_charged=5,
        log_prefix="test",
    )

    assert len(sdk.created) == 1
    assert len(sdk.updated) == 1
    collection, item_id, payload = sdk.updated[0]
    assert collection == "usage_daily_chat_summaries"
    assert item_id == "existing-daily"
    assert payload["total_credits"] == 15
    assert payload["entry_count"] == 3


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=billing.surface.semantic-parity
async def test_monthly_summary_duplicate_create_retries_as_update() -> None:
    sdk = DuplicateCreateSDK({"id": "existing-monthly", "total_credits": 20, "entry_count": 4})
    usage = UsageMethods(sdk=sdk, encryption_service=FakeEncryption())

    await usage._update_summary(
        collection="usage_monthly_chat_summaries",
        user_id_hash="user-a",
        identifier_key="chat_id",
        identifier_value="chat-1",
        year_month="2026-07",
        credits_charged=6,
        log_prefix="test",
        summary_type="chat",
    )

    assert len(sdk.created) == 1
    assert len(sdk.updated) == 1
    collection, item_id, payload = sdk.updated[0]
    assert collection == "usage_monthly_chat_summaries"
    assert item_id == "existing-monthly"
    assert payload["total_credits"] == 26
    assert payload["entry_count"] == 5


@pytest.mark.anyio
# contract-test: direct surface=rest_api assertions=billing.surface.semantic-parity
async def test_daily_overview_reconciles_stale_chat_total_from_raw_usage() -> None:
    sdk = ReconciliationSDK()
    usage = UsageMethods(sdk=sdk, encryption_service=FakeEncryption())

    overview = await usage.get_reconciled_daily_overview(
        user_id_hash="user-a",
        user_vault_key_id="vault-a",
        days=7,
    )

    assert overview[0]["total_credits"] == 75
    assert overview[0]["items"][0]["total_credits"] == 75
    assert overview[0]["items"][0]["entry_count"] == 3
