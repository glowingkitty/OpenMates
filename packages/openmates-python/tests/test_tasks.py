"""Python SDK user task contract tests.

Purpose: verify the pip SDK encrypts/decrypts task content behind plaintext
task helpers, matching the CLI contract without real network calls.
Security: monkeypatches requests; no API keys or task payloads leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_tasks.py
"""

from openmates import OpenMates
from openmates.sdk import _create_api_key_material


def test_pip_sdk_decrypted_task_helpers_use_api_key_master_key(monkeypatch):
    master_key = bytes([7]) * 32
    api_key, material = _create_api_key_material("sdk task parity", master_key)
    requests_seen = []
    stored_task = None

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        assert headers["Authorization"] == f"Bearer {api_key}"
        requests_seen.append({"method": "GET", "url": url})
        return FakeResponse({"tasks": [stored_task] if stored_task else []})

    def fake_post(url, *, json, headers, timeout):
        nonlocal stored_task
        assert headers["Authorization"] == f"Bearer {api_key}"
        requests_seen.append({"method": "POST", "url": url, "json": json})
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({
                "key_wrapper": {
                    "encrypted_key": material["encrypted_master_key"],
                    "salt": material["salt"],
                    "key_iv": material["key_iv"],
                }
            })
        if url.endswith("/v1/user-tasks"):
            assert isinstance(json.get("encrypted_title"), str)
            assert "title" not in json
            stored_task = {**json, "short_id": "TASK-1"}
            return FakeResponse({"task": stored_task})
        if url.endswith("/start-ai"):
            assert isinstance(json.get("plaintext_title"), str)
            stored_task = {**stored_task, "status": "in_progress", "ai_execution_state": "running"}
            return FakeResponse({"task": stored_task})
        if url.endswith("/block"):
            stored_task = {**stored_task, "status": "blocked", "blocked_reason_code": json.get("blocked_reason_code")}
            return FakeResponse({"task": stored_task})
        if url.endswith("/unblock"):
            stored_task = {**stored_task, "status": "todo", "blocked_reason_code": None}
            return FakeResponse({"task": stored_task})
        if url.endswith("/skip"):
            stored_task = {**stored_task, "status": "backlog", "queue_state": "skipped", "ai_execution_state": "skipped"}
            return FakeResponse({"task": stored_task})
        if url.endswith("/complete"):
            stored_task = {**stored_task, "status": "done"}
            return FakeResponse({"task": stored_task})
        if url.endswith("/reorder"):
            move = json["moves"][0]
            stored_task = {**stored_task, "position": move["position"], "status": move.get("status", stored_task["status"])}
            return FakeResponse({"tasks": [stored_task]})
        raise AssertionError(f"unexpected POST {url}")

    def fake_patch(url, *, json, headers, timeout):
        nonlocal stored_task
        assert headers["Authorization"] == f"Bearer {api_key}"
        requests_seen.append({"method": "PATCH", "url": url, "json": json})
        stored_task = {**stored_task, **json}
        return FakeResponse({"task": stored_task})

    def fake_delete(url, *, json, headers, timeout):
        nonlocal stored_task
        assert headers["Authorization"] == f"Bearer {api_key}"
        requests_seen.append({"method": "DELETE", "url": url})
        stored_task = None
        return FakeResponse({"deleted": True, "task_id": "deleted-task"})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)
    monkeypatch.setattr("openmates.sdk.requests.delete", fake_delete)

    client = OpenMates(api_key=api_key)
    created = client.tasks.create({"title": "SDK parity task", "description": "Plain task body", "assign": "user"})
    assert created["title"] == "SDK parity task"
    assert "encrypted" not in created
    assert client.tasks.list()[0]["title"] == "SDK parity task"
    edited = client.tasks.edit("TASK-1", {"title": "SDK parity task edited", "status": "in_progress"})
    assert edited["title"] == "SDK parity task edited"
    assert edited["status"] == "in_progress"
    assert client.tasks.start_ai("TASK-1")["status"] == "in_progress"
    assert client.tasks.block("TASK-1", "needs_input")["status"] == "blocked"
    assert client.tasks.unblock("TASK-1")["status"] == "todo"
    assert client.tasks.skip("TASK-1")["queue_state"] == "skipped"
    assert client.tasks.done("TASK-1")["status"] == "done"
    assert client.tasks.move("TASK-1", {"position": 42, "status": "todo"})[0]["position"] == 42
    assert client.tasks.delete_by_id("TASK-1", confirmed=True)["deleted"] is True
    assert any(request["url"].endswith("/v1/sdk/session") for request in requests_seen)
