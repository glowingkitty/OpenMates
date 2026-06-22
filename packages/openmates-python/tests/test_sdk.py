"""OpenMates Python SDK contract tests.

Purpose: verify lazy API-key SDK behavior before implementation.
Architecture: docs/specs/sdk-packages-v1/spec.yml.
Security: SDK must not require email or explicit connect before calls.
Run: python3 -m pytest packages/openmates-python/tests/test_sdk.py
"""

import pytest

from openmates import OpenMates, OpenMatesConfigError


def test_missing_api_key_raises_typed_config_error(monkeypatch):
    monkeypatch.delenv("OPENMATES_API_KEY", raising=False)

    client = OpenMates()

    with pytest.raises(OpenMatesConfigError):
        client.apps.run("web", "search", {"requests": [{"query": "hello"}]})


def test_new_chat_defaults_to_non_persistent(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"persistent": False, "response": {"content": "hi"}}

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    chat = client.chats.create()
    response = chat.send("hello")

    assert response.content == "hi"
    assert requests[0]["url"] == "https://api.openmates.org/v1/sdk/chats"
    assert requests[0]["json"]["save_to_account"] is False


def test_lists_latest_encrypted_account_chats(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"chats": [{"id": "chat-1", "encrypted_title": "ciphertext"}]}

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"url": url, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)

    client = OpenMates(api_key="sk-api-test")
    chats = client.chats.list(limit=3)

    assert chats == [{"id": "chat-1", "encrypted_title": "ciphertext"}]
    assert requests_seen[0]["url"] == "https://api.openmates.org/v1/sdk/chats?limit=3&offset=0"
    assert requests_seen[0]["headers"]["X-OpenMates-SDK"] == "pip"


def test_chat_list_defaults_to_10_and_limit_zero_requests_all(monkeypatch):
    urls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"chats": []}

    def fake_get(url, *, headers, timeout):
        urls.append(url)
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)

    client = OpenMates(api_key="sk-api-test")
    client.chats.list()
    client.chats.list(limit=0)

    assert urls == [
        "https://api.openmates.org/v1/sdk/chats?limit=10&offset=0",
        "https://api.openmates.org/v1/sdk/chats?limit=0&offset=0",
    ]
