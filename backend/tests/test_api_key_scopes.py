"""API key scope, budget, and device authorization contracts.

Purpose: lock the SDK V1 permission model before backend implementation.
Architecture: docs/specs/sdk-packages-v1/spec.yml and developer settings.
Security: tests assert deny-by-scope and deny-by-budget behavior server-side.
Run: python3 -m pytest backend/tests/test_api_key_scopes.py
"""

import hashlib
from types import SimpleNamespace

import pytest

from backend.core.api.app.routes import settings
from backend.core.api.app.services.api_key_authorization import (
    ApiKeyBudgetError,
    ApiKeyScopeError,
    ApiKeyAuthorizationService,
)
from backend.core.api.app.services.directus.api_key_device_methods import _dedupe_api_key_devices
from backend.core.api.app.utils.api_key_device_ownership import api_key_device_belongs_to_user


def test_full_access_default_allows_chat_and_any_skill():
    service = ApiKeyAuthorizationService()
    metadata = service.normalize_metadata({})

    service.require_chat_scope(metadata, "chat:read_existing")
    service.require_chat_scope(metadata, "chat:create_incognito")
    service.require_app_skill_scope(metadata, "web", "search")
    service.require_app_skill_scope(metadata, "images", "generate")


def test_app_skill_scope_can_allow_one_skill_only():
    service = ApiKeyAuthorizationService()
    metadata = service.normalize_metadata(
        {
            "full_access": False,
            "scopes": {
                "apps": {
                    "mode": "selected",
                    "allowed_skills": ["web:search"],
                }
            },
        }
    )

    service.require_app_skill_scope(metadata, "web", "search")
    with pytest.raises(ApiKeyScopeError) as exc:
        service.require_app_skill_scope(metadata, "web", "browse")
    assert exc.value.missing_scope == "skill:web:browse"


def test_chat_scopes_are_enforced_independently():
    service = ApiKeyAuthorizationService()
    metadata = service.normalize_metadata(
        {
            "full_access": False,
            "scopes": {
                "chat": ["chat:create_incognito", "chat:create_saved"],
            },
        }
    )

    service.require_chat_scope(metadata, "chat:create_incognito")
    service.require_chat_scope(metadata, "chat:create_saved")
    with pytest.raises(ApiKeyScopeError) as exc:
        service.require_chat_scope(metadata, "chat:read_existing")
    assert exc.value.missing_scope == "chat:read_existing"


@pytest.mark.parametrize(
    "limit",
    [
        {"period": "daily", "credits": 100},
        {"period": "weekly", "credits": 100},
        {"period": "monthly", "credits": 100},
        {"period": "lifetime", "credits": 100},
    ],
)
def test_one_period_credit_budget_blocks_when_request_would_exceed_limit(limit):
    service = ApiKeyAuthorizationService()
    metadata = service.normalize_metadata({"credit_limit": limit})

    service.require_budget(metadata, already_spent=90, requested_credits=10)
    with pytest.raises(ApiKeyBudgetError) as exc:
        service.require_budget(metadata, already_spent=95, requested_credits=10)

    assert exc.value.period == limit["period"]
    assert exc.value.remaining_credits == 5


def test_multiple_credit_periods_are_rejected():
    service = ApiKeyAuthorizationService()

    with pytest.raises(ValueError, match="exactly one credit limit period"):
        service.normalize_metadata(
            {
                "credit_limit": {
                    "daily": 100,
                    "monthly": 500,
                }
            }
        )


def test_owned_api_key_device_verification_uses_device_owner_hash():
    user_id = "user-123"
    device = {
        "id": "device-123",
        "api_key_id": "api-key-123",
        "hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest(),
        "device_hash": "device-hash-123",
    }

    assert api_key_device_belongs_to_user(device, user_id)


def test_owned_api_key_device_verification_rejects_other_users():
    device = {
        "id": "device-123",
        "api_key_id": "api-key-123",
        "hashed_user_id": hashlib.sha256(b"other-user").hexdigest(),
        "device_hash": "device-hash-123",
    }

    assert not api_key_device_belongs_to_user(device, "user-123")


def test_api_key_device_dedupe_prefers_approved_duplicate():
    devices = _dedupe_api_key_devices([
        {
            "id": "pending-device",
            "api_key_id": "api-key-123",
            "device_hash": "device-hash-123",
            "approved_at": None,
            "first_access_at": "2026-07-16T10:00:00+00:00",
            "last_access_at": "2026-07-16T10:00:00+00:00",
        },
        {
            "id": "approved-device",
            "api_key_id": "api-key-123",
            "device_hash": "device-hash-123",
            "approved_at": "2026-07-16T10:05:00+00:00",
            "first_access_at": "2026-07-16T10:01:00+00:00",
            "last_access_at": "2026-07-16T10:06:00+00:00",
        },
    ])

    assert devices == [{
        "id": "approved-device",
        "api_key_id": "api-key-123",
        "device_hash": "device-hash-123",
        "approved_at": "2026-07-16T10:05:00+00:00",
        "first_access_at": "2026-07-16T10:00:00+00:00",
        "last_access_at": "2026-07-16T10:06:00+00:00",
    }]


class _FakeApiKeyDeviceDirectus:
    def __init__(self, user_id: str):
        self.device = {
            "id": "device-123",
            "api_key_id": "api-key-123",
            "hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest(),
            "device_hash": "device-hash-123",
        }

    async def get_api_key_device_by_id(self, device_id):
        assert device_id == "device-123"
        return self.device

    async def approve_api_key_device(self, device_id):
        assert device_id == "device-123"
        return True, "Device approved successfully"


class _FakeApiKeyDeviceCache:
    def __init__(self):
        self.deleted_keys = []

    async def delete(self, key):
        self.deleted_keys.append(key)


@pytest.mark.anyio
async def test_approve_api_key_device_invalidates_injected_cache():
    user_id = "user-123"
    cache = _FakeApiKeyDeviceCache()

    approve_device_route = getattr(settings.approve_api_key_device, "__wrapped__", settings.approve_api_key_device)
    response = await approve_device_route(
        request=SimpleNamespace(),
        device_id="device-123",
        current_user=SimpleNamespace(id=user_id),
        directus_service=_FakeApiKeyDeviceDirectus(user_id),
        cache_service=cache,
    )

    assert response.success is True
    assert cache.deleted_keys == ["api_key_device_approval:api-key-123:device-hash-123"]
