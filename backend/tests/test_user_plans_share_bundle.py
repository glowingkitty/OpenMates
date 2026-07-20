"""Tests for encrypted plan entries in shared chat bundles.

Shared chat links carry decrypt authority in the URL fragment. The backend may
serve encrypted plan rows and chat-scoped wrapped keys, but must not receive raw
plan keys, decrypted fields, passwords, or durable share wrappers.
"""

import hashlib

import pytest

from backend.core.api.app.services.user_plan_share_bundle import get_shared_chat_plans


class FakeDirectus:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def get_items(self, collection: str, params: dict, **_kwargs):
        self.calls.append((collection, params))
        if collection == "user_plans":
            return [
                {
                    "plan_id": "plan-active",
                    "status": "active",
                    "primary_chat_id": "chat-1",
                    "encrypted_title": "cipher-title",
                    "encrypted_goal": "cipher-goal",
                }
            ]
        if collection == "user_plan_key_wrappers":
            return [
                {
                    "hashed_plan_id": hashlib.sha256(b"plan-active").hexdigest(),
                    "key_type": "chat",
                    "hashed_chat_id": hashlib.sha256(b"chat-1").hexdigest(),
                    "encrypted_plan_key": "cipher-plan-key-for-share-fragment",
                }
            ]
        return []


@pytest.mark.asyncio
async def test_shared_chat_payload_includes_chat_primary_active_plans_and_wrappers() -> None:
    directus = FakeDirectus()
    hashed_chat_id = hashlib.sha256(b"chat-1").hexdigest()

    payload = await get_shared_chat_plans("chat-1", hashed_chat_id, directus)

    assert payload["plans"][0]["plan_id"] == "plan-active"
    assert payload["plan_key_wrappers"][0]["key_type"] == "chat"
    plan_call = directus.calls[0]
    wrapper_call = directus.calls[1]
    assert plan_call[0] == "user_plans"
    assert plan_call[1]["filter[hashed_primary_chat_id][_eq]"] == hashed_chat_id
    assert wrapper_call[0] == "user_plan_key_wrappers"
    assert wrapper_call[1]["filter[key_type][_eq]"] == "chat"
    assert "fragment" not in str(directus.calls).lower()
    assert "password" not in str(directus.calls).lower()
    assert "raw_plan_key" not in str(directus.calls).lower()


@pytest.mark.asyncio
async def test_shared_chat_payload_excludes_project_only_plans_by_chat_filter() -> None:
    directus = FakeDirectus()
    await get_shared_chat_plans("chat-1", hashlib.sha256(b"chat-1").hexdigest(), directus)

    plan_params = directus.calls[0][1]
    assert "filter[hashed_primary_chat_id][_eq]" in plan_params
    assert "filter[linked_project_hashes][_contains]" not in plan_params
