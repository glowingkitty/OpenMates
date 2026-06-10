"""
backend/tests/test_free_testing_credits_budget.py

Regression tests for the server-admin Free testing credit budget.
The tests exercise the service contract with fake Directus/cache/encryption
collaborators so budget accounting, idempotency, public metadata, and
promotional stats remain deterministic without a running CMS.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import pytest

from backend.core.api.app.services.free_testing_credits_service import (
    FREE_TESTING_BUDGET_COLLECTION,
    FREE_TESTING_GRANTS_COLLECTION,
    FreeTestingCreditsService,
)


class FakeDirectus:
    def __init__(self) -> None:
        self.budget: dict[str, Any] | None = None
        self.grants: list[dict[str, Any]] = []
        self.users: dict[str, dict[str, Any]] = {
            "user-1": {"id": "user-1", "vault_key_id": "vault-1", "encrypted_credit_balance": "enc:0"},
            "user-2": {"id": "user-2", "vault_key_id": "vault-2", "encrypted_credit_balance": "enc:0"},
            "user-3": {"id": "user-3", "vault_key_id": "vault-3", "encrypted_credit_balance": "enc:0"},
        }
        self.updated_users: list[tuple[str, dict[str, Any]]] = []

    async def get_items(self, collection: str, params: dict[str, Any] | None = None, no_cache: bool = False, admin_required: bool = False) -> list[dict[str, Any]]:
        if collection == FREE_TESTING_BUDGET_COLLECTION:
            return [self.budget] if self.budget else []
        if collection == FREE_TESTING_GRANTS_COLLECTION:
            expected_hash = (params or {}).get("filter[user_id_hash][_eq]")
            if expected_hash:
                return [grant for grant in self.grants if grant.get("user_id_hash") == expected_hash]
            return list(self.grants)
        if collection == "directus_users":
            user_id = (params or {}).get("filter[id][_eq]")
            return [self.users[user_id]] if user_id in self.users else []
        raise AssertionError(f"Unexpected collection: {collection}")

    async def create_item(self, collection: str, payload: dict[str, Any], admin_required: bool = False) -> tuple[bool, dict[str, Any]]:
        if collection == FREE_TESTING_BUDGET_COLLECTION:
            self.budget = {"id": "default", **payload}
            return True, self.budget
        if collection == FREE_TESTING_GRANTS_COLLECTION:
            grant = {"id": f"grant-{len(self.grants) + 1}", **payload}
            self.grants.append(grant)
            return True, grant
        raise AssertionError(f"Unexpected collection: {collection}")

    async def update_item(self, collection: str, item_id: str, data: dict[str, Any], admin_required: bool = False) -> dict[str, Any] | None:
        if collection == FREE_TESTING_BUDGET_COLLECTION:
            assert self.budget is not None
            self.budget.update(data)
            return self.budget
        raise AssertionError(f"Unexpected collection: {collection}")

    async def update_user(self, user_id: str, data: dict[str, Any]) -> bool:
        self.users[user_id].update(data)
        self.updated_users.append((user_id, data))
        return True


class FakeCache:
    def __init__(self, directus: FakeDirectus) -> None:
        self.directus = directus
        self.users: dict[str, dict[str, Any]] = {
            user_id: {"user_id": user_id, "id": user_id, "vault_key_id": user["vault_key_id"], "credits": 0}
            for user_id, user in directus.users.items()
        }
        self.incremented: list[tuple[str, int]] = []
        self.liability_updates: list[int] = []
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        return self.users.get(user_id)

    async def set_user(self, user_data: dict[str, Any], user_id: str | None = None, refresh_token: str | None = None, ttl: int | None = None) -> bool:
        resolved_id = user_id or user_data.get("user_id") or user_data.get("id")
        assert resolved_id
        self.users[resolved_id] = dict(user_data)
        return True

    async def increment_stat(self, field: str, amount: int = 1) -> None:
        self.incremented.append((field, amount))

    async def update_liability(self, delta: int) -> None:
        self.liability_updates.append(delta)

    async def publish_event(self, channel: str, event_data: dict[str, Any]) -> None:
        self.published.append((channel, event_data))


class FakeEncryption:
    async def encrypt_with_user_key(self, plaintext: str, key_id: str) -> tuple[str, str]:
        return f"enc:{plaintext}:key:{key_id}", "1"


class FakeWebSocketManager:
    def __init__(self) -> None:
        self.broadcasts: list[tuple[str, str, dict[str, Any]]] = []

    async def broadcast_to_user_specific_event(self, user_id: str, event_name: str, payload: dict[str, Any]) -> None:
        self.broadcasts.append((user_id, event_name, payload))


class FakeCelery:
    def __init__(self) -> None:
        self.tasks: list[tuple[str, dict[str, Any], str | None]] = []

    def send_task(self, name: str, kwargs: dict[str, Any], queue: str | None = None) -> None:
        self.tasks.append((name, kwargs, queue))


def make_service() -> tuple[FreeTestingCreditsService, FakeDirectus, FakeCache, FakeWebSocketManager, FakeCelery]:
    directus = FakeDirectus()
    cache = FakeCache(directus)
    manager = FakeWebSocketManager()
    celery = FakeCelery()
    service = FreeTestingCreditsService(
        directus_service=directus,
        cache_service=cache,
        encryption_service=FakeEncryption(),
        websocket_manager=manager,
        celery_app=celery,
        admin_email_getter=lambda: "admin@example.com",
    )
    return service, directus, cache, manager, celery


@pytest.mark.asyncio
async def test_admin_budget_save_and_public_metadata_are_safe() -> None:
    service, _, _, _, _ = make_service()

    status = await service.save_budget(
        enabled=True,
        total_budget_credits=50_000,
        per_user_grant_credits=1_000,
        admin_user_id="admin-1",
    )
    public = await service.get_public_promotion()

    assert status.enabled is True
    assert status.total_budget_credits == 50_000
    assert status.used_budget_credits == 0
    assert status.remaining_budget_credits == 50_000
    assert status.active is True
    assert public == {"active": True, "grant_credits": 1_000}
    assert "remaining_budget_credits" not in public
    assert "total_budget_credits" not in public


@pytest.mark.asyncio
async def test_grant_is_idempotent_and_does_not_count_as_credits_sold() -> None:
    service, directus, cache, manager, celery = make_service()
    await service.save_budget(enabled=True, total_budget_credits=2_000, per_user_grant_credits=1_000, admin_user_id="admin-1")

    assert await service.has_grant_for_user("user-1") is False

    first = await service.grant_to_new_signup("user-1")
    second = await service.grant_to_new_signup("user-1")

    assert first.granted is True
    assert first.credits_granted == 1_000
    assert first.current_credits == 1_000
    assert await service.has_grant_for_user("user-1") is True
    assert await service.has_grant_for_user("user-2") is False
    assert second.granted is False
    assert second.reason == "already_granted"
    assert directus.budget is not None
    assert directus.budget["used_budget_credits"] == 1_000
    assert len(directus.grants) == 1
    assert directus.grants[0]["user_id_hash"] == hashlib.sha256(b"user-1").hexdigest()
    assert cache.users["user-1"]["credits"] == 1_000
    assert ("credits_sold", 1_000) not in cache.incremented
    assert ("free_testing_credits_granted", 1_000) in cache.incremented
    assert ("free_testing_grants_created", 1) in cache.incremented
    assert cache.liability_updates == [1_000]
    assert ("user-1", "user_credits_updated", {"credits": 1_000}) in manager.broadcasts
    assert any(event_name == "user_notification" for _, event_name, _ in manager.broadcasts)
    assert celery.tasks == []


@pytest.mark.asyncio
async def test_no_partial_grant_when_remaining_is_below_per_user_amount() -> None:
    service, directus, cache, _, _ = make_service()
    await service.save_budget(enabled=True, total_budget_credits=1_500, per_user_grant_credits=1_000, admin_user_id="admin-1")
    first = await service.grant_to_new_signup("user-1")

    second = await service.grant_to_new_signup("user-2")
    public = await service.get_public_promotion()

    assert first.granted is True
    assert second.granted is False
    assert second.reason == "insufficient_budget"
    assert directus.budget is not None
    assert directus.budget["used_budget_credits"] == 1_000
    assert len(directus.grants) == 1
    assert cache.users["user-2"]["credits"] == 0
    assert public == {"active": False, "grant_credits": 1_000}


@pytest.mark.asyncio
async def test_concurrent_grants_do_not_overspend_budget_and_email_once() -> None:
    service, directus, _, _, celery = make_service()
    await service.save_budget(enabled=True, total_budget_credits=2_000, per_user_grant_credits=1_000, admin_user_id="admin-1")

    results = await asyncio.gather(
        service.grant_to_new_signup("user-1"),
        service.grant_to_new_signup("user-2"),
        service.grant_to_new_signup("user-3"),
    )

    assert sum(1 for result in results if result.granted) == 2
    assert directus.budget is not None
    assert directus.budget["used_budget_credits"] == 2_000
    assert directus.budget["exhausted_email_sent_at"]
    assert len(directus.grants) == 2
    assert len(celery.tasks) == 1
    name, kwargs, queue = celery.tasks[0]
    assert name == "app.tasks.email_tasks.free_testing_budget_email_task.send_free_testing_budget_exhausted_email"
    assert kwargs["admin_email"] == "admin@example.com"
    assert kwargs["total_budget_credits"] == 2_000
    assert queue == "email"


@pytest.mark.asyncio
async def test_disabled_budget_is_inactive_and_does_not_grant() -> None:
    service, _, cache, _, _ = make_service()
    await service.save_budget(enabled=False, total_budget_credits=50_000, per_user_grant_credits=1_000, admin_user_id="admin-1")

    result = await service.grant_to_new_signup("user-1")

    assert result.granted is False
    assert result.reason == "inactive"
    assert await service.get_public_promotion() == {"active": False, "grant_credits": 1_000}
    assert cache.users["user-1"]["credits"] == 0
