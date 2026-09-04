"""API key scope, budget, and device authorization contracts.

Purpose: lock the SDK V1 permission model before backend implementation.
Architecture: docs/plans/sdk-packages-v1/plan.yml and developer settings.
Security: tests assert deny-by-scope and deny-by-budget behavior server-side.
Run: python3 -m pytest backend/tests/test_api_key_scopes.py
"""

import hashlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes import settings
from backend.core.api.app.routes.apps_api import _require_api_key_app_skill_scope
from backend.core.api.app.routes.openai_compat import _dispatch_ai_ask_chat_completion
from backend.core.api.app.services.api_key_authorization import (
    CANONICAL_API_KEY_SCOPES,
    ApiKeyBudgetError,
    ApiKeyScopeError,
    ApiKeyAuthorizationService,
)
from backend.core.api.app.services.directus.api_key_device_methods import _dedupe_api_key_devices
from backend.core.api.app.utils.api_key_device_ownership import api_key_device_belongs_to_user


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_full_access_default_allows_chat_and_any_skill():
    service = ApiKeyAuthorizationService()
    metadata = service.normalize_metadata({})

    service.require_chat_scope(metadata, "chat:read_existing")
    service.require_chat_scope(metadata, "chat:create_incognito")
    service.require_app_skill_scope(metadata, "web", "search")
    service.require_app_skill_scope(metadata, "images", "generate")


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_direct_app_skill_dispatch_rejects_unselected_ai_ask_scope() -> None:
    with pytest.raises(HTTPException) as exc:
        _require_api_key_app_skill_scope(
            {
                "api_key_hash": "api-key-hash",
                "api_key_metadata": {
                    "full_access": False,
                    "scopes": {"apps": {"mode": "selected", "allowed_apps": [], "allowed_skills": []}},
                },
            },
            "ai",
            "ask",
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "missing_scope", "missing_scope": "skill:ai:ask"}


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
async def test_openai_ai_dispatch_rejects_unselected_ai_ask_scope() -> None:
    with pytest.raises(HTTPException) as exc:
        await _dispatch_ai_ask_chat_completion(
            request_body={"model": "openai/gpt-test", "messages": []},
            user_info={
                "user_id": "user-1",
                "api_key_hash": "api-key-hash",
                "api_key_metadata": {
                    "full_access": False,
                    "scopes": {"apps": {"mode": "selected", "allowed_apps": [], "allowed_skills": []}},
                },
            },
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "missing_scope", "missing_scope": "skill:ai:ask"}


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
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


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
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


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_scope_payload_validation_accepts_canonical_scopes_and_rejects_unknown_values():
    service = ApiKeyAuthorizationService()
    scopes = {
        group: sorted(values)
        for group, values in CANONICAL_API_KEY_SCOPES.items()
    }
    scopes["apps"] = {
        "mode": "selected",
        "allowed_apps": ["web"],
        "allowed_skills": ["web:search"],
    }

    assert service.validate_scope_payload(scopes) == scopes

    with pytest.raises(ValueError, match="Unsupported API key scope: task:admin"):
        service.validate_scope_payload({"tasks": ["task:admin"]})

    with pytest.raises(ValueError, match="Unsupported API key scope group: admin"):
        service.validate_scope_payload({"admin": ["admin:all"]})


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_scope_payload_validation_deduplicates_selected_values():
    service = ApiKeyAuthorizationService()

    normalized = service.validate_scope_payload({
        "chat": ["chat:read_existing", "chat:read_existing"],
        "apps": {
            "mode": "selected",
            "allowed_apps": ["web", "web"],
            "allowed_skills": ["web:search", "web:search"],
        },
    })

    assert normalized["chat"] == ["chat:read_existing"]
    assert normalized["apps"] == {
        "mode": "selected",
        "allowed_apps": ["web"],
        "allowed_skills": ["web:search"],
    }


@pytest.mark.parametrize(
    "limit",
    [
        {"period": "daily", "credits": 100},
        {"period": "weekly", "credits": 100},
        {"period": "monthly", "credits": 100},
        {"period": "lifetime", "credits": 100},
    ],
)
# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_one_period_credit_budget_blocks_when_request_would_exceed_limit(limit):
    service = ApiKeyAuthorizationService()
    metadata = service.normalize_metadata({"credit_limit": limit})

    service.require_budget(metadata, already_spent=90, requested_credits=10)
    with pytest.raises(ApiKeyBudgetError) as exc:
        service.require_budget(metadata, already_spent=95, requested_credits=10)

    assert exc.value.period == limit["period"]
    assert exc.value.remaining_credits == 5


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
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


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_owned_api_key_device_verification_uses_device_owner_hash():
    user_id = "user-123"
    device = {
        "id": "device-123",
        "api_key_id": "api-key-123",
        "hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest(),
        "device_hash": "device-hash-123",
    }

    assert api_key_device_belongs_to_user(device, user_id)


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_owned_api_key_device_verification_rejects_other_users():
    device = {
        "id": "device-123",
        "api_key_id": "api-key-123",
        "hashed_user_id": hashlib.sha256(b"other-user").hexdigest(),
        "device_hash": "device-hash-123",
    }

    assert not api_key_device_belongs_to_user(device, "user-123")


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
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
# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
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
