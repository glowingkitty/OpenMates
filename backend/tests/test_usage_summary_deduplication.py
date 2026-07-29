# backend/tests/test_usage_summary_deduplication.py
#
# Regression coverage for legacy billing usage summary deduplication.
# The Settings usage UI, REST API, CLI, and SDKs consume these helper tables, so
# duplicate helper rows must not make raw usage charges look duplicated.
# These tests use fake Directus responses and never touch live billing data.

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

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


class FakeDirectusSDK:
    def __init__(self, rows_by_collection: dict[str, list[dict[str, Any]]]) -> None:
        self.rows_by_collection = rows_by_collection
        self.cache = FakeCache()
        self.calls: list[dict[str, Any]] = []

    async def get_items(self, collection: str, params: dict[str, Any] | None = None, **kwargs: Any):
        self.calls.append({"collection": collection, "params": params, **kwargs})
        return list(self.rows_by_collection.get(collection, []))


class FakeEncryption:
    async def encrypt_with_user_key(self, key_id: str, plaintext: str):
        return f"enc:{key_id}:{plaintext}", None

    async def decrypt_with_user_key(self, ciphertext: str, _key_id: str):
        return ciphertext


@pytest.mark.anyio
async def test_daily_overview_coalesces_duplicate_summary_rows() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    sdk = FakeDirectusSDK(
        {
            "usage_daily_chat_summaries": [
                {"id": "chat-a", "user_id_hash": "user-a", "chat_id": "chat-1", "date": today, "total_credits": 7, "entry_count": 1, "updated_at": 100},
                {"id": "chat-b", "user_id_hash": "user-a", "chat_id": "chat-1", "date": today, "total_credits": 5, "entry_count": 2, "updated_at": 200},
                {"id": "chat-empty", "user_id_hash": "user-a", "chat_id": "", "date": today, "total_credits": 99, "entry_count": 1, "updated_at": 300},
                {"id": "chat-other-user", "user_id_hash": "user-b", "chat_id": "chat-1", "date": today, "total_credits": 50, "entry_count": 1, "updated_at": 400},
            ],
            "usage_daily_api_key_summaries": [
                {"id": "api-a", "user_id_hash": "user-a", "api_key_hash": "cli:device-1", "date": today, "total_credits": 4, "entry_count": 1, "updated_at": 110},
                {"id": "api-b", "user_id_hash": "user-a", "api_key_hash": "cli:device-1", "date": today, "total_credits": 6, "entry_count": 1, "updated_at": 210},
            ],
        }
    )
    usage = UsageMethods(sdk=sdk, encryption_service=FakeEncryption())

    overview = await usage.get_daily_overview(user_id_hash="user-a", days=1)

    assert len(overview) == 1
    assert overview[0]["total_credits"] == 22
    chat_items = [item for item in overview[0]["items"] if item["type"] == "chat"]
    api_items = [item for item in overview[0]["items"] if item["type"] == "api_key"]
    assert chat_items == [
        {
            "type": "chat",
            "chat_id": "chat-1",
            "api_key_hash": None,
            "total_credits": 12,
            "entry_count": 3,
            "updated_at": 200,
        }
    ]
    assert api_items == [
        {
            "type": "api_key",
            "chat_id": None,
            "api_key_hash": "cli:device-1",
            "total_credits": 10,
            "entry_count": 2,
            "updated_at": 210,
        }
    ]


@pytest.mark.anyio
async def test_monthly_summaries_coalesce_duplicates_and_preserve_archive_metadata() -> None:
    sdk = FakeDirectusSDK(
        {
            "usage_monthly_chat_summaries": [
                {"id": "summary-a", "user_id_hash": "user-a", "chat_id": "chat-1", "year_month": "2026-07", "total_credits": 7, "entry_count": 1, "is_archived": False, "archive_s3_key": None, "updated_at": 100},
                {"id": "summary-b", "user_id_hash": "user-a", "chat_id": "chat-1", "year_month": "2026-07", "total_credits": 5, "entry_count": 2, "is_archived": True, "archive_s3_key": "usage-archives/user-a/2026-07/usage.json.gz", "updated_at": 200},
                {"id": "summary-empty", "user_id_hash": "user-a", "chat_id": "", "year_month": "2026-07", "total_credits": 99, "entry_count": 1, "is_archived": False, "archive_s3_key": None, "updated_at": 300},
                {"id": "summary-other-user", "user_id_hash": "user-b", "chat_id": "chat-1", "year_month": "2026-07", "total_credits": 50, "entry_count": 1, "is_archived": False, "archive_s3_key": None, "updated_at": 400},
            ]
        }
    )
    usage = UsageMethods(sdk=sdk, encryption_service=FakeEncryption())

    summaries = await usage.get_monthly_summaries(user_id_hash="user-a", summary_type="chat", months=1)

    assert summaries == [
        {
            "id": "summary-b",
            "user_id_hash": "user-a",
            "chat_id": "chat-1",
            "year_month": "2026-07",
            "total_credits": 12,
            "entry_count": 3,
            "is_archived": True,
            "archive_s3_key": "usage-archives/user-a/2026-07/usage.json.gz",
            "updated_at": 200,
        }
    ]


@pytest.mark.anyio
async def test_daily_overview_coalesces_cached_duplicate_items() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    sdk = FakeDirectusSDK({})
    sdk.cache.values["usage_daily_overview:user-a:1"] = [
        {
            "date": today,
            "total_credits": 111,
            "items": [
                {"type": "chat", "chat_id": "chat-1", "api_key_hash": None, "total_credits": 7, "entry_count": 1, "updated_at": 100},
                {"type": "chat", "chat_id": "chat-1", "api_key_hash": None, "total_credits": 5, "entry_count": 2, "updated_at": 200},
                {"type": "chat", "chat_id": "", "api_key_hash": None, "total_credits": 99, "entry_count": 1, "updated_at": 300},
            ],
        }
    ]
    usage = UsageMethods(sdk=sdk, encryption_service=FakeEncryption())

    overview = await usage.get_daily_overview(user_id_hash="user-a", days=1)

    assert overview == [
        {
            "date": today,
            "total_credits": 12,
            "items": [
                {"type": "chat", "chat_id": "chat-1", "api_key_hash": None, "total_credits": 12, "entry_count": 3, "updated_at": 200}
            ],
        }
    ]


@pytest.mark.anyio
async def test_monthly_summaries_coalesce_cached_duplicate_rows() -> None:
    sdk = FakeDirectusSDK({})
    sdk.cache.values["usage_summaries:user-a:chat:1"] = [
        {"id": "summary-a", "user_id_hash": "user-a", "chat_id": "chat-1", "year_month": "2026-07", "total_credits": 7, "entry_count": 1, "updated_at": 100},
        {"id": "summary-b", "user_id_hash": "user-a", "chat_id": "chat-1", "year_month": "2026-07", "total_credits": 5, "entry_count": 2, "updated_at": 200},
    ]
    usage = UsageMethods(sdk=sdk, encryption_service=FakeEncryption())

    summaries = await usage.get_monthly_summaries(user_id_hash="user-a", summary_type="chat", months=1)

    assert summaries == [
        {
            "id": "summary-b",
            "user_id_hash": "user-a",
            "chat_id": "chat-1",
            "year_month": "2026-07",
            "total_credits": 12,
            "entry_count": 3,
            "updated_at": 200,
        }
    ]
