"""Python SDK Project source contract tests.

Purpose: verify the pip SDK exposes encrypted /v1/projects/{id}/sources parity
with CLI/npm without real network calls.
Security: monkeypatches requests; no API keys or source ciphertext leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_projects.py.
"""

from openmates import OpenMates


SOURCE = {
    "source_id": "source-1",
    "source_type": "remote_git_repository",
    "encrypted_display_name": "cipher-name",
    "encrypted_metadata": "cipher-metadata",
    "capabilities": ["read", "search"],
    "status": "connected",
    "created_at": 100,
    "updated_at": 100,
}


def test_pip_sdk_project_source_methods_use_shared_projects_api(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        assert headers["X-OpenMates-SDK"] == "pip"
        return FakeResponse({"sources": [SOURCE]})

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url, "json": json})
        assert headers["X-OpenMates-SDK"] == "pip"
        return FakeResponse({"source": {**SOURCE, **json}})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="x")
    assert client.projects.list_sources("project-1")[0]["source_id"] == "source-1"
    assert client.projects.create_source("project-1", SOURCE)["encrypted_display_name"] == "cipher-name"

    assert requests_seen == [
        {"method": "GET", "url": "https://api.openmates.org/v1/projects/project-1/sources"},
        {"method": "POST", "url": "https://api.openmates.org/v1/projects/project-1/sources", "json": SOURCE},
    ]
