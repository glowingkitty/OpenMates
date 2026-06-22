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

from backend.core.api.app.routes.sdk import create_sdk_session_for_api_key


def _request():
    return SimpleNamespace(
        headers={"Authorization": "Bearer sk-api-test"},
        client=SimpleNamespace(host="127.0.0.1"),
    )


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
