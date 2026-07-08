"""OpenMates Python SDK contract tests.

Purpose: verify lazy API-key SDK behavior before implementation.
Architecture: docs/specs/sdk-packages-v1/spec.yml.
Security: SDK must not require email or explicit connect before calls.
Run: python3 -m pytest packages/openmates-python/tests/test_sdk.py
"""

import base64
import hashlib
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from openmates import OpenMates, OpenMatesConfigError


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("utf-8")


def _encrypt_combined(value: bytes, key: bytes) -> str:
    iv = os.urandom(12)
    return _b64(iv + AESGCM(key).encrypt(iv, value, None))


def _wrap_master_key(api_key: str, master_key: bytes) -> dict[str, str]:
    salt = os.urandom(16)
    iv = os.urandom(12)
    wrapping_key = hashlib.pbkdf2_hmac("sha256", api_key.encode("utf-8"), salt, 100_000, dklen=32)
    return {
        "encrypted_key": _b64(AESGCM(wrapping_key).encrypt(iv, master_key, None)),
        "salt": _b64(salt),
        "key_iv": _b64(iv),
    }


def test_missing_api_key_raises_typed_config_error(monkeypatch):
    monkeypatch.delenv("OPENMATES_API_KEY", raising=False)

    client = OpenMates()

    with pytest.raises(OpenMatesConfigError):
        client.apps.web.search({"requests": [{"query": "hello"}]})


def test_native_app_skill_method_uses_generated_namespace(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"success": True, "data": {"results": [{"title": "ok"}]}}

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    assert not hasattr(client.apps, "run")
    result = client.apps.web.search({"requests": [{"query": "hello"}]})

    assert result == {"success": True, "data": {"results": [{"title": "ok"}]}}
    assert requests[0]["url"] == "https://api.openmates.org/v1/apps/web/skills/search"
    assert requests[0]["json"] == {
        "input_data": {"requests": [{"query": "hello"}]},
        "parameters": {},
    }


def test_new_chat_defaults_to_non_persistent(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "persistent": False,
                "response": {
                    "content": "hi",
                    "raw": {"choices": [{"message": {"role": "assistant", "content": "hi"}}]},
                },
            }

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    response = client.chats.send("hello")

    assert response.content == "hi"
    assert requests[0]["url"] == "https://api.openmates.org/v1/sdk/chats"
    assert requests[0]["json"]["save_to_account"] is False


def test_new_chat_can_include_focus_mode(monkeypatch):
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "response": {
                    "content": "focused",
                    "raw": {"choices": [{"message": {"role": "assistant", "content": "focused"}}]},
                }
            }

    def fake_post(url, *, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    response = client.chats.send("research this", focus_mode={"app_id": "web", "focus_mode_id": "research"})

    assert response.content == "focused"
    assert requests[0]["json"]["focus_mode"] == {"app_id": "web", "focus_mode_id": "research"}


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


def test_lazily_unwraps_api_key_session_and_decrypts_chat_metadata(monkeypatch):
    api_key = "sk-api-python-test"
    master_key = os.urandom(32)
    chat_key = os.urandom(32)
    key_wrapper = _wrap_master_key(api_key, master_key)
    encrypted_chat_key = _encrypt_combined(chat_key, master_key)
    encrypted_title = _encrypt_combined(b"Decrypted Python SDK chat", chat_key)
    encrypted_summary = _encrypt_combined(b"Encrypted Python summary", chat_key)
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append(("GET", url, None))
        assert headers["Authorization"] == f"Bearer {api_key}"
        return FakeResponse({
            "chats": [{
                "id": "chat-1",
                "encrypted_chat_key": encrypted_chat_key,
                "encrypted_title": encrypted_title,
                "encrypted_chat_summary": encrypted_summary,
            }]
        })

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append(("POST", url, json))
        assert headers["Authorization"] == f"Bearer {api_key}"
        return FakeResponse({"key_wrapper": key_wrapper})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key)
    chats = client.chats.list(limit=1)

    assert chats[0]["title"] == "Decrypted Python SDK chat"
    assert chats[0]["chat_summary"] == "Encrypted Python summary"
    assert chats[0]["encrypted_title"] == encrypted_title
    assert requests_seen == [
        ("GET", "https://api.openmates.org/v1/sdk/chats?limit=1&offset=0", None),
        ("POST", "https://api.openmates.org/v1/sdk/session", {"sdk_name": "pip", "device_identity": os.name}),
    ]


def test_searches_decrypted_chat_metadata_locally(monkeypatch):
    api_key = "sk-api-python-search"
    master_key = os.urandom(32)
    madrid_chat_key = os.urandom(32)
    berlin_chat_key = os.urandom(32)
    key_wrapper = _wrap_master_key(api_key, master_key)
    requests_seen = []
    chats = [
        {
            "id": "chat-madrid",
            "encrypted_chat_key": _encrypt_combined(madrid_chat_key, master_key),
            "encrypted_title": _encrypt_combined(b"Madrid itinerary", madrid_chat_key),
        },
        {
            "id": "chat-berlin",
            "encrypted_chat_key": _encrypt_combined(berlin_chat_key, master_key),
            "encrypted_title": _encrypt_combined(b"Berlin itinerary", berlin_chat_key),
        },
    ]

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append(("GET", url))
        return FakeResponse({"chats": chats})

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append(("POST", url))
        return FakeResponse({"key_wrapper": key_wrapper})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key)
    results = client.chats.search("Madrid")

    assert [chat["id"] for chat in results] == ["chat-madrid"]
    assert results[0]["title"] == "Madrid itinerary"
    assert requests_seen == [
        ("GET", "https://api.openmates.org/v1/sdk/chats?limit=0&offset=0"),
        ("POST", "https://api.openmates.org/v1/sdk/session"),
    ]


def test_load_decrypts_chat_messages_client_side(monkeypatch):
    api_key = "sk-api-python-load"
    master_key = os.urandom(32)
    chat_key = os.urandom(32)
    embed_key = os.urandom(32)
    key_wrapper = _wrap_master_key(api_key, master_key)
    encrypted_chat_key = _encrypt_combined(chat_key, master_key)
    encrypted_title = _encrypt_combined(b"Loaded Python SDK chat", chat_key)
    encrypted_content = _encrypt_combined(b"Hello from encrypted Python storage", chat_key)
    encrypted_sender = _encrypt_combined(b"OpenMates", chat_key)
    encrypted_embed_key = _encrypt_combined(embed_key, master_key)
    encrypted_embed_type = _encrypt_combined(b"math.calculate", embed_key)
    encrypted_embed_content = _encrypt_combined(b'{"result": 4}', embed_key)
    encrypted_embed_preview = _encrypt_combined(b"2 + 2 = 4", embed_key)
    hashed_embed_id = hashlib.sha256(b"embed-1").hexdigest()
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append(("GET", url))
        return FakeResponse({
            "chat": {"id": "chat-1", "encrypted_chat_key": encrypted_chat_key, "encrypted_title": encrypted_title},
            "messages": [{"id": "message-1", "encrypted_content": encrypted_content, "encrypted_sender_name": encrypted_sender}],
            "embeds": [{
                "embed_id": "embed-1",
                "encrypted_type": encrypted_embed_type,
                "encrypted_content": encrypted_embed_content,
                "encrypted_text_preview": encrypted_embed_preview,
            }],
            "embed_keys": [{"hashed_embed_id": hashed_embed_id, "key_type": "master", "encrypted_embed_key": encrypted_embed_key}],
        })

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append(("POST", url))
        return FakeResponse({"key_wrapper": key_wrapper})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key)
    loaded = client.chats.load("chat-1")

    assert loaded["chat"]["title"] == "Loaded Python SDK chat"
    assert loaded["messages"][0]["content"] == "Hello from encrypted Python storage"
    assert loaded["messages"][0]["sender_name"] == "OpenMates"
    assert loaded["messages"][0]["encrypted_content"] == encrypted_content
    assert loaded["embeds"][0]["type"] == "math.calculate"
    assert loaded["embeds"][0]["content"] == {"result": 4}
    assert loaded["embeds"][0]["text_preview"] == "2 + 2 = 4"
    assert requests_seen == [
        ("GET", "https://api.openmates.org/v1/sdk/chats/chat-1"),
        ("POST", "https://api.openmates.org/v1/sdk/session"),
    ]


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


def test_named_cli_parity_namespaces_use_sdk_routes(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": True, "suggestions": ["next"]}

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        return FakeResponse()

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    assert not hasattr(client.apps, "run")
    assert not hasattr(client, "newsletter")
    assert not hasattr(client.notifications, "set_email")
    assert not hasattr(client.notifications, "set_backup_reminder")
    assert not hasattr(client.notifications, "stream")
    client.account.info()
    client.account.set_timezone("Europe/Berlin")
    client.chats.search("Madrid", limit=5)
    client.chats.load("chat-1")
    client.settings.set_dark_mode(True)
    client.billing.list_invoices()
    client.docs.search("sdk")
    client.embeds.versions("embed-1")
    client.notifications.list(limit=2)
    client.reminders.list()
    client.learning_mode.status()
    client.inspirations.list(language="de")
    client.new_chat_suggestions.list(limit=4)

    assert requests_seen == [
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/account"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/account/timezone"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/chats?limit=0&offset=0"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/chats/chat-1"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/settings/dark-mode"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/billing/invoices"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/docs/search?q=sdk"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/embeds/embed-1/versions"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/notifications?limit=2"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/reminders"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/learning-mode"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/inspirations?lang=de"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/new-chat-suggestions?limit=4"},
    ]


def test_previously_blocked_sdk_surfaces_route_to_concrete_endpoints(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = b"ok"

        def __init__(self, payload=None):
            self._payload = payload or {"ok": True, "memories": [], "suggestions": [], "embed_keys": []}

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        if url.endswith("/v1/sdk/chats/chat-1"):
            return FakeResponse({"chat": {"id": "chat-1"}, "messages": []})
        return FakeResponse()

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url})
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="sk-api-test")
    client.chats.follow_ups("chat-1")
    client.chats.export("chat-1")
    client.account.list_interests()
    client.memories.types(app_id="code")
    client.billing.usage_export()
    client.billing.create_bank_transfer_order(110000)
    client.embeds.show("embed-1")
    with pytest.raises(OpenMatesConfigError, match="must start with OMCA1"):
        client.connected_accounts.import_account(payload="invalid", passcode="123456")
    client.feedback.assistant_response(rating=5)
    client.benchmark.estimate({"suite": "quick"})
    with pytest.raises(OpenMatesConfigError, match="not available through the API-key SDK yet"):
        client.settings.share_debug_logs(confirmed=True)

    assert requests_seen == [
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/chats/chat-1"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/chats/chat-1"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/chats/chat-1/export"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/account/topic-preferences"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/memories/types?app_id=code"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/billing/usage/export"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/billing/bank-transfer-orders"},
        {"method": "GET", "url": "https://api.openmates.org/v1/sdk/embeds/embed-1"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/feedback/assistant-response"},
        {"method": "POST", "url": "https://api.openmates.org/v1/sdk/benchmark/estimate"},
    ]


def test_destructive_sdk_operations_require_confirmation():
    client = OpenMates(api_key="sk-api-test")

    with pytest.raises(OpenMatesConfigError, match="requires confirmed=True"):
        client.chats.delete("chat-1")
    with pytest.raises(OpenMatesConfigError, match="requires confirmed=True"):
        client.memories.delete("memory-1")
    with pytest.raises(OpenMatesConfigError, match="requires confirmed=True"):
        client.embeds.restore_version("embed-1", 1)
