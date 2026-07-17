"""Python SDK key-wrapper parity tests.

Purpose: ensure chat decrypt paths prefer canonical wrapper rows and keep
row-level encrypted_chat_key fallback during migration.
Security: synthetic keys only; no network calls or real chat data.
Run: python3 -m pytest packages/openmates-python/tests/test_key_wrappers.py
"""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from openmates import OpenMates
from openmates.sdk import _create_api_key_material, _encrypt_aes_gcm_bytes


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("utf-8")


def _encrypt_combined(value: bytes, key: bytes) -> str:
    iv = os.urandom(12)
    return _b64(iv + AESGCM(key).encrypt(iv, value, None))


def test_pip_sdk_decrypts_chat_with_master_wrapper_before_row_key(monkeypatch):
    master_key = bytes([11]) * 32
    wrapper_chat_key = bytes([12]) * 32
    stale_row_chat_key = bytes([13]) * 32
    api_key, material = _create_api_key_material("wrapper parity", master_key)
    chat_id = "11111111-1111-4111-8111-111111111111"
    hashed_chat_id = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "key_wrapper": {
                    "encrypted_key": material["encrypted_master_key"],
                    "salt": material["salt"],
                    "key_iv": material["key_iv"],
                }
            }

    def fake_post(url, *, json, headers, timeout):
        assert url.endswith("/v1/sdk/session")
        assert headers["Authorization"] == f"Bearer {api_key}"
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key)
    payload = client._decrypt_loaded_chat_payload({
        "chat": {
            "id": chat_id,
            "encrypted_chat_key": _encrypt_aes_gcm_bytes(stale_row_chat_key, master_key),
            "encrypted_title": _encrypt_combined(b"Wrapper Title", wrapper_chat_key),
        },
        "messages": [
            {
                "id": "message-1",
                "encrypted_content": _encrypt_combined(b"Wrapper message", wrapper_chat_key),
            }
        ],
        "chat_key_wrappers": [{
            "id": "wrapper-1",
            "hashed_chat_id": hashed_chat_id,
            "key_type": "master",
            "encrypted_chat_key": _encrypt_aes_gcm_bytes(wrapper_chat_key, master_key),
        }],
    })

    assert payload["chat"]["title"] == "Wrapper Title"
    assert payload["messages"][0]["content"] == "Wrapper message"
