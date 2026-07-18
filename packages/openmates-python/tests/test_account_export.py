"""Account Export V1 Python SDK contract tests.

Purpose: verify pip SDK helpers use the shared resumable export job endpoints.
Architecture: docs/specs/account-export-v1/spec.yml.
Security: tests monkeypatch requests and never call a real OpenMates API.
Run: python3 -m pytest packages/openmates-python/tests/test_account_export.py
"""

from __future__ import annotations

from typing import Any

from openmates import OpenMates


def test_account_export_download_uses_shared_job_contract(monkeypatch):
    requests_seen: list[tuple[str, str, dict[str, Any] | None]] = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload: dict[str, Any]):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append(("POST", url, json))
        if url.endswith("/v1/account-exports"):
            return FakeResponse({"export": {"export_id": "export-1", "status": "queued"}})
        if url.endswith("/v1/account-exports/export-1/complete"):
            return FakeResponse({"export": {"export_id": "export-1", "status": "complete"}})
        return FakeResponse({"ok": True})

    def fake_get(url, *, headers, timeout):
        requests_seen.append(("GET", url, None))
        if url.endswith("/v1/account-exports/export-1/manifest"):
            return FakeResponse({"manifest": {"selected_domains": ["chats"]}})
        if url.endswith("/v1/account-exports/export-1/chunks"):
            return FakeResponse({"chunks": [{"chunk_id": "chats-0001"}]})
        if url.endswith("/v1/account-exports/export-1/chunks/chats-0001"):
            return FakeResponse({"chunk": {"chunk_id": "chats-0001", "payload": {"items": []}}})
        return FakeResponse({"ok": True})

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)

    client = OpenMates(api_key="sk-api-test")
    bundle = client.account.download_export(domains=["chats"])
    chunks = list(client.account.iter_export_chunks("export-1"))

    assert bundle["export"]["status"] == "complete"
    assert chunks[0]["chunk_id"] == "chats-0001"
    assert requests_seen == [
        ("POST", "https://api.openmates.org/v1/account-exports", {"domains": ["chats"], "filters": {}, "format": "zip", "include_advanced_metadata": False}),
        ("GET", "https://api.openmates.org/v1/account-exports/export-1/manifest", None),
        ("GET", "https://api.openmates.org/v1/account-exports/export-1/chunks", None),
        ("POST", "https://api.openmates.org/v1/account-exports/export-1/complete", {}),
        ("GET", "https://api.openmates.org/v1/account-exports/export-1/chunks", None),
        ("GET", "https://api.openmates.org/v1/account-exports/export-1/chunks/chats-0001", None),
    ]
