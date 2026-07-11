"""Python SDK read-only encrypted draft access contract tests."""

from openmates import OpenMates


def test_pip_sdk_exposes_read_only_encrypted_draft_access(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append(("GET", url, None))
        draft = {"chat_id": "chat-1", "encrypted_draft_md": "cipher-1", "draft_v": 2}
        return FakeResponse({"drafts": [draft]} if url.endswith("/drafts") else {"draft": draft})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)

    client = OpenMates(api_key="sk-api-test")
    assert client.drafts.list_encrypted()[0]["chat_id"] == "chat-1"
    assert client.drafts.get_encrypted("chat-1")["draft_v"] == 2
    assert not hasattr(client.drafts, "create")
    assert not hasattr(client.drafts, "clear")

    assert [(method, url.removeprefix("https://api.openmates.org")) for method, url, _ in requests_seen] == [
        ("GET", "/v1/sdk/drafts"),
        ("GET", "/v1/sdk/drafts/chat-1"),
    ]
    assert "draft plaintext" not in str(requests_seen)
