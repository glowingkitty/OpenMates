"""Python SDK cleartext boundary tests.

Purpose: verify public pip SDK callers pass/receive cleartext while durable
write requests remain encrypted.
Architecture: monkeypatched requests against synthetic API-key key material.
Security: no network calls or real credentials are used.
Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
Run: python3 -m pytest packages/openmates-python/tests/test_cleartext_boundary.py
"""

from openmates import OpenMates
from openmates.sdk import _create_api_key_material


CLEAR_PUBLIC_TASK = "CLEAR_PUBLIC_TASK"
CLEAR_PUBLIC_PLAN = "CLEAR_PUBLIC_PLAN"
CLEAR_PUBLIC_PROJECT = "CLEAR_PUBLIC_PROJECT"


def _assert_no_plaintext_marker(value, marker: str) -> None:
    assert marker not in str(value)


def test_pip_sdk_cleartext_asks_encrypt_storage_payloads(monkeypatch):
    master_key = bytes([13]) * 32
    api_key, material = _create_api_key_material("pip cleartext", master_key)

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, *, json, headers, timeout):
        assert headers["Authorization"] == f"Bearer {api_key}"
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        if url.endswith("/v1/user-tasks/ask/plan"):
            return FakeResponse({"proposed_tasks": [{"title": CLEAR_PUBLIC_TASK, "description": "task body"}]})
        if url.endswith("/v1/user-tasks/ask"):
            assert isinstance(json["encrypted_creates"], list)
            assert isinstance(json["encrypted_creates"][0]["encrypted_title"], str)
            _assert_no_plaintext_marker(json["encrypted_creates"], CLEAR_PUBLIC_TASK)
            return FakeResponse({"summary": "Created 1 task.", "task": json["encrypted_creates"][0], "tasks": json["encrypted_creates"]})
        if url.endswith("/v1/user-plans/ask/plan"):
            return FakeResponse({"proposed_plan": {"title": CLEAR_PUBLIC_PLAN, "goal": "plan goal"}})
        if url.endswith("/v1/user-plans/ask"):
            assert isinstance(json["encrypted_create"]["encrypted_title"], str)
            _assert_no_plaintext_marker(json["encrypted_create"], CLEAR_PUBLIC_PLAN)
            return FakeResponse({"summary": "Created 1 plan.", "plan": json["encrypted_create"], "plans": [json["encrypted_create"]]})
        if url.endswith("/v1/projects/ask/plan"):
            return FakeResponse({"proposed_project": {"name": CLEAR_PUBLIC_PROJECT, "description": "project body", "icon": "folder", "color": "blue"}})
        if url.endswith("/v1/projects/ask"):
            assert isinstance(json["encrypted_create"]["encrypted_name"], str)
            _assert_no_plaintext_marker(json["encrypted_create"], CLEAR_PUBLIC_PROJECT)
            return FakeResponse({"summary": "Created 1 project.", "project": json["encrypted_create"], "projects": [json["encrypted_create"]]})
        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    client = OpenMates(api_key=api_key, device_id="test-device")

    task = client.tasks.ask(f"create {CLEAR_PUBLIC_TASK}")
    plan = client.plans.ask(f"create {CLEAR_PUBLIC_PLAN}")
    project = client.projects.ask(f"create {CLEAR_PUBLIC_PROJECT}")

    assert task["tasks"][0]["title"] == CLEAR_PUBLIC_TASK
    assert task["tasks"][0]["description"] == "task body"
    assert plan["plans"][0]["title"] == CLEAR_PUBLIC_PLAN
    assert plan["plans"][0]["goal"] == "plan goal"
    assert project["projects"][0]["name"] == CLEAR_PUBLIC_PROJECT
    assert project["projects"][0]["description"] == "project body"
