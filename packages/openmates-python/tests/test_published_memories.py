from openmates import OpenMates


# contract-test: supporting surface=sdks.pip assertions=app-memories.catalog.declared-types-only,app-memories.surface.semantic-parity
def test_public_memories_preserve_exact_context_without_private_credentials(monkeypatch):
    memory = {"id": "app:code:svelte", "source": "app", "app_id": "code", "revision": "a" * 64, "body": "Exact published guidance"}
    seen = []

    class Response:
        status_code = 200

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    def get(url, *, headers, timeout):
        assert "Authorization" not in headers
        seen.append(url)
        return Response({"memories": [memory]} if "/code/" in url else {"apps": {"code": {"memories": [memory]}, "other": {}}})

    monkeypatch.setattr("openmates.sdk.requests.get", get)
    client = OpenMates(api_key="sk-api-private-never-send", api_url="https://example.invalid", device_id="memory-test")
    assert client.memories.published() == {"memories": [memory]}
    assert client.memories.published(app_id="code") == {"memories": [memory]}
    assert seen == ["https://example.invalid/v1/apps/metadata?include_unavailable=true", "https://example.invalid/v1/apps/code/metadata?include_unavailable=true"]
