"""
backend/tests/test_anonymous_free_usage_budget.py

Regression tests for anonymous free-usage budget accounting. These tests use
fake Directus/cache collaborators so admin configuration, public-safe metadata,
identity caps, and reservations stay deterministic without a running CMS.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from backend.core.api.app.services.anonymous_free_usage_service import (
    ANONYMOUS_BUDGET_COLLECTION,
    ANONYMOUS_IDENTITY_DAILY_COLLECTION,
    ANONYMOUS_RESERVATIONS_COLLECTION,
    AnonymousFreeUsageService,
)


class FakeDirectus:
    def __init__(self) -> None:
        self.budget: dict[str, Any] | None = None
        self.identity_rows: dict[str, dict[str, Any]] = {}
        self.reservations: dict[str, dict[str, Any]] = {}
        self.created_payloads: list[tuple[str, dict[str, Any]]] = []
        self.fail_budget_updates = False

    async def get_items(
        self,
        collection: str,
        params: dict[str, Any] | None = None,
        no_cache: bool = False,
        admin_required: bool = False,
    ) -> list[dict[str, Any]]:
        params = params or {}
        if collection == ANONYMOUS_BUDGET_COLLECTION:
            budget_id = params.get("filter[id][_eq]")
            if budget_id and self.budget and self.budget.get("id") != budget_id:
                return []
            return [self.budget] if self.budget else []
        if collection == ANONYMOUS_IDENTITY_DAILY_COLLECTION:
            identity_hash = params.get("filter[identity_hash][_eq]")
            if identity_hash:
                return [row for row in self.identity_rows.values() if row["identity_hash"] == identity_hash]
            return list(self.identity_rows.values())
        if collection == ANONYMOUS_RESERVATIONS_COLLECTION:
            request_id = params.get("filter[request_id][_eq]")
            if request_id:
                return [row for row in self.reservations.values() if row["request_id"] == request_id]
            return list(self.reservations.values())
        raise AssertionError(f"Unexpected collection: {collection}")

    async def create_item(
        self,
        collection: str,
        payload: dict[str, Any],
        admin_required: bool = False,
    ) -> tuple[bool, dict[str, Any]]:
        self.created_payloads.append((collection, payload))
        if collection == ANONYMOUS_BUDGET_COLLECTION:
            self.budget = {"id": "default", **payload}
            return True, self.budget
        if collection == ANONYMOUS_IDENTITY_DAILY_COLLECTION:
            item_id = payload.get("id") or f"identity-{len(self.identity_rows) + 1}"
            row = {"id": item_id, **payload}
            self.identity_rows[item_id] = row
            return True, row
        if collection == ANONYMOUS_RESERVATIONS_COLLECTION:
            item_id = payload.get("id") or f"reservation-{len(self.reservations) + 1}"
            row = {"id": item_id, **payload}
            self.reservations[item_id] = row
            return True, row
        raise AssertionError(f"Unexpected collection: {collection}")

    async def update_item(
        self,
        collection: str,
        item_id: str,
        data: dict[str, Any],
        admin_required: bool = False,
    ) -> dict[str, Any] | None:
        if collection == ANONYMOUS_BUDGET_COLLECTION:
            if self.fail_budget_updates:
                return None
            assert self.budget is not None
            self.budget.update(data)
            return self.budget
        if collection == ANONYMOUS_IDENTITY_DAILY_COLLECTION:
            self.identity_rows[item_id].update(data)
            return self.identity_rows[item_id]
        if collection == ANONYMOUS_RESERVATIONS_COLLECTION:
            self.reservations[item_id].update(data)
            return self.reservations[item_id]
        raise AssertionError(f"Unexpected collection: {collection}")


def make_service() -> tuple[AnonymousFreeUsageService, FakeDirectus]:
    directus = FakeDirectus()
    service = AnonymousFreeUsageService(
        directus_service=directus,
        hmac_secret="test-secret",
    )
    return service, directus


@pytest.mark.asyncio
async def test_admin_budget_save_derives_caps_and_public_status_is_safe() -> None:
    service, directus = make_service()

    status = await service.save_budget(
        enabled=True,
        monthly_budget_credits=60_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )
    public = await service.get_public_status()

    assert status.enabled is True
    assert status.monthly_budget_credits == 60_000
    assert status.daily_hard_cap_credits == 3_000
    assert status.weekly_cap_credits == 15_000
    assert status.per_identity_daily_cap_credits == 400
    assert status.monthly_remaining_credits == 60_000
    assert status.daily_remaining_credits == 3_000
    assert status.weekly_remaining_credits == 15_000
    assert status.active is True
    assert public["active"] is True
    assert public["can_send_text"] is True
    assert set(public) == {"active", "can_send_text", "reason", "reset_at", "cta"}
    assert directus.created_payloads[0][0] == ANONYMOUS_BUDGET_COLLECTION
    created_id = directus.created_payloads[0][1]["id"]
    assert created_id != "default"
    assert str(UUID(created_id)) == created_id


@pytest.mark.asyncio
async def test_enabled_budget_requires_positive_per_identity_cap() -> None:
    service, _directus = make_service()

    with pytest.raises(ValueError, match="per_identity_daily_cap_credits must be >= 1 when enabled"):
        await service.save_budget(
            enabled=True,
            monthly_budget_credits=60_000,
            daily_hard_cap_percent=5,
            weekly_cap_percent=25,
            per_identity_daily_cap_credits=0,
            admin_user_id="admin-1",
        )


@pytest.mark.asyncio
async def test_existing_zero_per_identity_cap_is_not_publicly_active() -> None:
    service, directus = make_service()
    directus.budget = {
        "id": "legacy-zero-cap",
        "enabled": True,
        "monthly_budget_credits": 60_000,
        "daily_hard_cap_percent": 5,
        "weekly_cap_percent": 25,
        "per_identity_daily_cap_credits": 0,
        "daily_used_credits": 0,
        "weekly_used_credits": 0,
        "updated_at": "2026-06-18T15:31:28Z",
    }

    status = await service.get_budget_status()
    public = await service.get_public_status()

    assert status.active is False
    assert status.reason == "per_identity_exhausted"
    assert public["active"] is False
    assert public["can_send_text"] is False
    assert public["reason"] == "per_identity_exhausted"


@pytest.mark.asyncio
async def test_public_status_checks_per_identity_remaining_budget() -> None:
    service, _directus = make_service()
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=60_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=10,
        admin_user_id="admin-1",
    )
    first = await service.reserve_budget(
        request_id="request-1",
        anonymous_id="anon-1",
        ip_address="203.0.113.7",
        estimated_credits=10,
    )

    public = await service.get_public_status(
        anonymous_id="anon-1",
        ip_address="203.0.113.9",
        estimated_credits=10,
    )

    assert first.accepted is True
    assert public["active"] is False
    assert public["can_send_text"] is False
    assert public["reason"] == "per_identity_exhausted"


@pytest.mark.asyncio
async def test_admin_budget_update_failure_does_not_return_synthetic_success() -> None:
    service, directus = make_service()
    await service.save_budget(
        enabled=False,
        monthly_budget_credits=0,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )
    directus.fail_budget_updates = True

    with pytest.raises(RuntimeError, match="Failed to update anonymous free usage budget"):
        await service.save_budget(
            enabled=True,
            monthly_budget_credits=60_000,
            daily_hard_cap_percent=5,
            weekly_cap_percent=25,
            per_identity_daily_cap_credits=400,
            admin_user_id="admin-1",
        )

    assert directus.budget is not None
    assert directus.budget["enabled"] is False
    assert directus.budget["monthly_budget_credits"] == 0


@pytest.mark.asyncio
async def test_finalize_charges_decrement_daily_weekly_monthly_without_credit_balance() -> None:
    service, directus = make_service()
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=60_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )

    reservation = await service.reserve_budget(
        request_id="request-1",
        anonymous_id="anon-1",
        ip_address="203.0.113.7",
        estimated_credits=200,
    )
    await service.finalize_reservation("request-1", actual_credits=125)
    status = await service.get_budget_status()

    assert reservation.accepted is True
    assert status.daily_used_credits == 125
    assert status.weekly_used_credits == 125
    assert status.monthly_used_credits == 125
    assert status.monthly_remaining_credits == 59_875
    assert directus.budget is not None
    assert "credits_sold" not in directus.budget


@pytest.mark.asyncio
async def test_reservation_rejects_when_monthly_bucket_is_exhausted() -> None:
    service, directus = make_service()
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=100,
        daily_hard_cap_percent=100,
        weekly_cap_percent=100,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )
    assert directus.budget is not None
    directus.budget["monthly_used_credits"] = 95

    rejected = await service.reserve_budget(
        request_id="request-monthly",
        anonymous_id="anon-1",
        ip_address="203.0.113.7",
        estimated_credits=10,
    )

    assert rejected.accepted is False
    assert rejected.reason == "budget_exhausted"
    assert directus.budget["daily_used_credits"] == 0
    assert directus.budget["weekly_used_credits"] == 0
    assert directus.budget["monthly_used_credits"] == 95


@pytest.mark.asyncio
async def test_per_identity_daily_cap_uses_local_id_or_ip_hmac() -> None:
    service, _directus = make_service()
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=60_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )

    first = await service.reserve_budget(
        request_id="request-1",
        anonymous_id="anon-1",
        ip_address="203.0.113.7",
        estimated_credits=400,
    )
    await service.finalize_reservation("request-1", actual_credits=400)
    second_same_local_id = await service.reserve_budget(
        request_id="request-2",
        anonymous_id="anon-1",
        ip_address="203.0.113.9",
        estimated_credits=1,
    )
    second_same_ip = await service.reserve_budget(
        request_id="request-3",
        anonymous_id="anon-2",
        ip_address="203.0.113.7",
        estimated_credits=1,
    )

    assert first.accepted is True
    assert second_same_local_id.accepted is False
    assert second_same_local_id.reason == "per_identity_exhausted"
    assert second_same_ip.accepted is False
    assert second_same_ip.reason == "per_identity_exhausted"


@pytest.mark.asyncio
async def test_concurrent_reservations_cannot_overspend_and_failure_releases_unused() -> None:
    service, _directus = make_service()
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=2_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=1_000,
        admin_user_id="admin-1",
    )

    accepted = await service.reserve_budget(
        request_id="request-1",
        anonymous_id="anon-1",
        ip_address="203.0.113.7",
        estimated_credits=100,
    )
    rejected = await service.reserve_budget(
        request_id="request-2",
        anonymous_id="anon-2",
        ip_address="203.0.113.8",
        estimated_credits=100,
    )

    assert accepted.accepted is True
    assert rejected.accepted is False
    assert rejected.reason == "budget_exhausted"

    await service.release_reservation("request-1", reason="provider_failed")
    status = await service.get_budget_status()

    assert status.daily_used_credits == 0
    assert status.weekly_used_credits == 0
    assert status.active is True
