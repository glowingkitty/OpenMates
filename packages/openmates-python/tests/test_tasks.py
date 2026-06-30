"""Python SDK user task contract tests.

Purpose: verify the pip SDK exposes the same encrypted /v1/user-tasks contract
as CLI/npm without real network calls.
Security: monkeypatches requests; no API keys or task payloads leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_tasks.py
"""

from openmates import OpenMates


TASK = {
    "task_id": "task-1",
    "encrypted_task_key": "cipher-key",
    "encrypted_title": "cipher-title",
    "status": "todo",
    "assignee_type": "user",
    "created_at": 100,
    "updated_at": 100,
}


def test_pip_sdk_user_task_methods_use_shared_tasks_api(monkeypatch):
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        return FakeResponse({"tasks": [TASK]})

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url, "json": json})
        return FakeResponse({"task": {**TASK, **json}})

    def fake_patch(url, *, json, headers, timeout):
        requests_seen.append({"method": "PATCH", "url": url, "json": json})
        return FakeResponse({"task": {**TASK, **json}})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)

    client = OpenMates(api_key="x")
    assert client.tasks.list(status="todo", chat_id="chat-1")[0]["task_id"] == "task-1"
    assert client.tasks.create(TASK)["encrypted_title"] == "cipher-title"
    assert client.tasks.update("task-1", {"status": "done", "version": 1})["status"] == "done"
    start_payload = {"version": 2, "plaintext_title": "Draft launch plan"}
    assert client.tasks.start_ai("task-1", start_payload)["task_id"] == "task-1"

    assert requests_seen == [
        {"method": "GET", "url": "https://api.openmates.org/v1/user-tasks?status=todo&chat_id=chat-1"},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-tasks", "json": TASK},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/user-tasks/task-1", "json": {"status": "done", "version": 1}},
        {"method": "POST", "url": "https://api.openmates.org/v1/user-tasks/task-1/start-ai", "json": start_payload},
    ]
