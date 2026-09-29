"""SDK API-key session contracts.

Purpose: verify the API-key SDK session returns wrapped key material only.
Architecture: docs/specs/sdk-packages-v1/spec.yml.
Security: SDK session must preserve device approval and never expose plaintext keys.
Run: python3 -m pytest backend/tests/test_sdk_session.py
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import hashlib

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes.sdk import create_sdk_session_for_api_key
from backend.core.api.app.routes.settings import validate_project_key_grants


def _request():
    return SimpleNamespace(
        headers={"Authorization": "Bearer sk-api-test"},
        client=SimpleNamespace(host="127.0.0.1"),
    )


# contract-test: direct surface=rest_api assertions=sdk.auth.credential-separation,sdk.encryption.local-only
@pytest.mark.asyncio
async def test_sdk_session_returns_api_key_wrapper_without_plaintext_master_key():
    auth_service = AsyncMock()
    auth_service.authenticate_api_key = AsyncMock(
        return_value={
            "user_id": "user-1",
            "api_key_id": "api-key-1",
            "api_key_hash": "a" * 64,
            "device_hash": "d" * 64,
            "api_key_encrypted_name": "encrypted-name",
            "api_key_metadata": {"full_access": True},
        }
    )
    directus_service = AsyncMock()
    directus_service.get_user_profile = AsyncMock(
        return_value=(True, {"username": "alice"}, "ok")
    )
    directus_service.get_encryption_key = AsyncMock(
        return_value={
            "encrypted_key": "wrapped-master-key",
            "salt": "salt-b64",
            "key_iv": "iv-b64",
        }
    )

    result = await create_sdk_session_for_api_key(
        request=_request(),
        sdk_name="npm",
        device_identity="machine-1",
        auth_service=auth_service,
        directus_service=directus_service,
    )

    assert result["user"] == {"id": "user-1", "username": "alice"}
    assert result["key_wrapper"] == {
        "encrypted_key": "wrapped-master-key",
        "salt": "salt-b64",
        "key_iv": "iv-b64",
    }
    assert "master_key" not in str(result).lower()
    directus_service.get_encryption_key.assert_awaited_once_with(
        hashlib.sha256("user-1".encode()).hexdigest(),
        "api_key_" + "a" * 64,
    )


# contract-test: direct surface=rest_api assertions=sdk.auth.limited-resource-keys
@pytest.mark.asyncio
async def test_limited_sdk_session_never_exports_account_master_wrapper():
    auth_service = AsyncMock()
    auth_service.authenticate_api_key.return_value = {
        "user_id": "user-1",
        "api_key_id": "limited-key",
        "api_key_hash": "b" * 64,
        "api_key_metadata": {"full_access": False, "scopes": {"chat": ["chat:read_existing"]}},
    }
    directus_service = AsyncMock()
    directus_service.get_user_profile.return_value = (True, {"username": "alice"}, "ok")

    result = await create_sdk_session_for_api_key(
        request=_request(),
        sdk_name="pip",
        device_identity="machine-1",
        auth_service=auth_service,
        directus_service=directus_service,
    )

    assert result["key_wrapper"] is None
    assert result["grant_key_scope"] == "allowed_resource_keys"
    directus_service.get_encryption_key.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=sdk.auth.limited-resource-keys
@pytest.mark.asyncio
async def test_limited_sdk_session_returns_only_still_owned_project_grants():
    auth_service = AsyncMock()
    auth_service.authenticate_api_key.return_value = {
        "user_id": "user-1", "api_key_id": "limited-key", "api_key_hash": "b" * 64,
        "api_key_metadata": {"full_access": False, "scopes": {"projects": ["project:read"]}},
    }
    owned = {"resource_type": "project", "resource_id": "owned", "encrypted_key": "wrapped-project", "salt": "salt", "key_iv": "iv"}
    foreign = {"resource_type": "project", "resource_id": "foreign", "encrypted_key": "wrapped-foreign", "salt": "salt", "key_iv": "iv"}
    directus_service = AsyncMock()
    directus_service.get_user_profile.return_value = (True, {"username": "alice"}, "ok")
    directus_service.get_api_key_by_hash.return_value = {"id": "limited-key", "resource_key_grants": [owned, foreign]}
    async def owned_project(project_id, _user_id):
        return {"project_id": project_id} if project_id == "owned" else None
    directus_service.project.get_project.side_effect = owned_project

    result = await create_sdk_session_for_api_key(
        request=_request(), sdk_name="npm", device_identity="machine-1",
        auth_service=auth_service, directus_service=directus_service,
    )
    assert result["resource_key_grants"] == [owned]
    assert result["key_wrapper"] is None
    assert "wrapped-foreign" not in str(result)
    directus_service.get_encryption_key.assert_not_awaited()

    directus_service.get_api_key_by_hash.return_value = None
    with pytest.raises(HTTPException) as error:
        await create_sdk_session_for_api_key(
            request=_request(), sdk_name="npm", device_identity="machine-1",
            auth_service=auth_service, directus_service=directus_service,
        )
    assert error.value.status_code == 401


# contract-test: direct surface=rest_api assertions=sdk.auth.limited-resource-keys
@pytest.mark.asyncio
async def test_project_grant_creation_rejects_foreign_resource_and_root_scope():
    directus_service = AsyncMock()
    project_id = "22222222-2222-4222-8222-222222222222"
    grant = {"resource_type": "project", "resource_id": project_id, "encrypted_key": "ciphertext", "salt": "salt", "key_iv": "iv"}
    directus_service.project.get_project.return_value = None
    with pytest.raises(HTTPException) as foreign_error:
        await validate_project_key_grants(
            [grant], full_access=False, scopes={"projects": ["project:read"]},
            user_id="owner", directus_service=directus_service,
        )
    assert foreign_error.value.status_code == 403
    directus_service.project.get_project.assert_awaited_once_with(project_id, "owner")

    directus_service.project.get_project.reset_mock()
    with pytest.raises(HTTPException) as full_access_error:
        await validate_project_key_grants(
            [grant], full_access=True, scopes={"projects": ["project:read"]},
            user_id="owner", directus_service=directus_service,
        )
    assert full_access_error.value.status_code == 400
    directus_service.project.get_project.assert_not_awaited()
