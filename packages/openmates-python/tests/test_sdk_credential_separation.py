"""Separated SDK setup credential and typed first-party key-management exclusion."""

import hashlib
import os

import pytest

from openmates import OpenMates, OpenMatesUnavailableError
from openmates.sdk import _create_api_key_material, _unwrap_api_key_master_key


# contract-test: direct surface=sdks.pip assertions=sdk.auth.credential-separation
def test_python_sdk_sends_bearer_only_and_bearer_cannot_unwrap(monkeypatch):
    master_key = os.urandom(32)
    credential, material = _create_api_key_material("test", master_key)
    bearer, secret = credential.split(".")
    assert material["api_key_hash"] == hashlib.sha256(bearer.encode()).hexdigest()
    assert _unwrap_api_key_master_key(
        f"{bearer}.{'x' * len(secret)}",
        material["encrypted_master_key"], material["salt"], material["key_iv"],
    ) is None

    class Response:
        status_code = 200

        def json(self):
            return {"ok": True}

    def fake_get(url, *, headers, timeout):
        assert headers["Authorization"] == f"Bearer {bearer}"
        assert secret not in str(headers)
        return Response()

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    assert OpenMates(api_key=credential, device_id="test-device")._get("/v1/sdk/test") == {"ok": True}


# contract-test: direct surface=sdks.pip assertions=sdk.surface.semantic-parity,sdk.auth.legacy-key-migration
def test_python_sdk_key_management_requires_first_party_verification():
    client = OpenMates(api_key="sk-api-test", device_id="test-device")
    with pytest.raises(OpenMatesUnavailableError) as create_error:
        client.api_keys.create("new")
    assert create_error.value.code == "unavailable_requires_first_party_verification"
    with pytest.raises(OpenMatesUnavailableError) as revoke_error:
        client.api_keys.revoke("old")
    assert revoke_error.value.code == "unavailable_requires_first_party_verification"
