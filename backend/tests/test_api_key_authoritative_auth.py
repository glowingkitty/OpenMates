"""API key revocation and expiry cannot be bypassed by stale cached records."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import hashlib

import pytest

from backend.core.api.app.utils.api_key_auth import ApiKeyAuthService, ApiKeyNotFoundError, DeviceNotApprovedError


class Directus:
    def __init__(self):
        self.row = {"id": "key-1", "user_id": "user-1", "credential_version": 2,
                    "full_access": True, "scopes": {}, "expires_at": None}
        self.lookups = 0

    async def get_api_key_by_hash(self, _digest):
        self.lookups += 1
        return self.row

    async def update_api_key_last_used(self, *_args, **_kwargs):
        return True


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement
def test_api_key_each_request_reads_authority_and_rejects_legacy_or_bad_expiry():
    async def run():
        directus = Directus()
        service = ApiKeyAuthService(directus, SimpleNamespace())
        await service.authenticate_api_key("sk-api-secret")
        directus.row = None
        with pytest.raises(ApiKeyNotFoundError):
            await service.authenticate_api_key("sk-api-secret")
        assert directus.lookups == 2

        directus.row = {"id": "legacy", "user_id": "user-1", "expires_at": None}
        with pytest.raises(ApiKeyNotFoundError):
            await service.authenticate_api_key("sk-api-secret")
        directus.row["credential_version"] = 2
        directus.row["expires_at"] = "unparseable"
        with pytest.raises(ApiKeyNotFoundError):
            await service.authenticate_api_key("sk-api-secret")
        directus.row["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with pytest.raises(ApiKeyNotFoundError):
            await service.authenticate_api_key("sk-api-secret")

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
@pytest.mark.parametrize("sdk", ["rust", "npm", "pip"])
def test_sdk_device_identity_is_stable_and_never_bypasses_approval(sdk):
    async def run():
        cache = SimpleNamespace(get=AsyncMock(return_value={"approved_at": None, "device_id": "device-1"}))
        service = ApiKeyAuthService(SimpleNamespace(update_api_key_device_last_access=AsyncMock()), cache)
        request = SimpleNamespace(
            headers={"X-OpenMates-SDK": sdk, "X-OpenMates-Device-Identity": "explicit-device"},
            client=SimpleNamespace(host="192.0.2.1"),
        )
        with pytest.raises(DeviceNotApprovedError):
            await service._check_and_register_device("key-1", "user-1", request)
        cache.get.assert_awaited_once_with(
            "api_key_device_approval:key-1:" + hashlib.sha256(f"{sdk}:explicit-device:user-1".encode()).hexdigest()
        )
        cache.get.return_value = {"approved_at": "2026-10-21T00:00:00Z", "device_id": "device-1"}
        expected = await service._check_and_register_device("key-1", "user-1", request)
        request.client.host = "192.0.2.2"
        assert await service._check_and_register_device("key-1", "user-1", request) == expected
        assert service._access_type_for_request(request) == sdk
    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device
def test_unknown_sdk_header_stays_ip_scoped_rest_access():
    service = ApiKeyAuthService(SimpleNamespace(), SimpleNamespace())
    request = SimpleNamespace(headers={"X-OpenMates-SDK": "unknown"})
    assert service._access_type_for_request(request) == "rest_api"


# contract-test: direct surface=rest_api assertions=auth.session.isolation,owner-consistency.http.refuse-before-effect
@pytest.mark.asyncio
@pytest.mark.parametrize("expected,allowed", [(None, True), ("22222222-2222-4222-8222-222222222222", True), ("11111111-1111-4111-8111-111111111111", False)])
async def test_request_aware_api_key_restriction_precedes_device_and_usage_effects(expected, allowed):
    from fastapi import HTTPException
    from starlette.requests import Request
    directus = Directus()
    directus.row["user_id"] = "22222222-2222-4222-8222-222222222222"
    directus.update_api_key_last_used = AsyncMock(return_value=True)
    service = ApiKeyAuthService(directus, SimpleNamespace())
    service._check_and_register_device = AsyncMock(return_value="synthetic-device")
    headers = [] if expected is None else [(b"x-openmates-expected-principal", expected.encode())]
    request = Request({"type": "http", "headers": headers})
    if allowed:
        result = await service.authenticate_api_key("sk-api-synthetic", request=request)
        assert result["user_id"] == directus.row["user_id"]
        service._check_and_register_device.assert_awaited_once()
        directus.update_api_key_last_used.assert_awaited_once()
    else:
        with pytest.raises(HTTPException) as error:
            await service.authenticate_api_key("sk-api-synthetic", request=request)
        assert error.value.status_code == 403
        assert error.value.detail == {"error": "session_principal_mismatch"}
        service._check_and_register_device.assert_not_awaited()
        directus.update_api_key_last_used.assert_not_awaited()
