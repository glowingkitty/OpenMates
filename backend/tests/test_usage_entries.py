# backend/tests/test_usage_entries.py
#
# Regression tests for billing usage history retrieval.
# The user-facing billing page and CLI depend on this query returning the newest
# usage rows first; otherwise successful charges can be hidden behind older rows.
# These tests keep the Directus query contract deterministic without needing a
# live Directus instance or real encryption keys.

from __future__ import annotations

import importlib.util
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


class FakeDirectusSDK:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    async def get_items(self, collection: str, params: dict[str, Any], no_cache: bool = False):
        self.calls.append({"collection": collection, "params": params, "no_cache": no_cache})
        return self.rows


class FakeEncryption:
    async def decrypt_with_user_key(self, ciphertext: str, _key_id: str):
        return ciphertext


@pytest.mark.anyio
async def test_user_usage_entries_query_requests_newest_first_page() -> None:
    sdk = FakeDirectusSDK([
        {
            "id": "usage-1",
            "type": "skill_execution",
            "source": "chat",
            "created_at": 200,
            "updated_at": 200,
            "app_id": "code",
            "skill_id": "run",
            "encrypted_credits_costs_total": "5",
        }
    ])
    usage = UsageMethods(sdk=sdk, encryption_service=FakeEncryption())

    entries = await usage.get_user_usage_entries(
        user_id_hash="user-hash",
        user_vault_key_id="vault-key",
        limit=10,
        offset=0,
        sort="-created_at",
    )

    assert entries[0]["app_id"] == "code"
    params = sdk.calls[0]["params"]
    assert params["sort"] == ["-created_at"]
    assert params["limit"] == 10
    assert params["offset"] == 0
