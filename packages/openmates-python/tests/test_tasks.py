"""Python SDK user task contract tests.

Purpose: verify the pip SDK encrypts/decrypts task content behind plaintext
task helpers, matching the CLI contract without real network calls.
Security: monkeypatches requests; no API keys or task payloads leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_tasks.py
"""

import hashlib
import hmac

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from openmates import OpenMates
from openmates.sdk import OpenMatesConfigError
from openmates.sdk import _build_task_create_input, _create_api_key_material, _encrypt_aes_gcm_bytes, _encrypt_aes_gcm_text, _external_chat_lookup_hash


# contract-test: direct surface=sdks.pip assertions=tasks.activity.client-encrypted,tasks.activity.context-attribution,tasks.activity.deletion-tombstone,tasks.surface.semantic-parity
def test_pip_sdk_manages_decrypted_task_activity(monkeypatch):
    master_key = bytes([12]) * 32
    api_key, material = _create_api_key_material("sdk activity parity", master_key)
    task = {**_build_task_create_input(master_key, {"title": "SDK Activity task"}), "short_id": "TASK-ACT"}
    stored_activity = None

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        if "/activity" in url:
            return FakeResponse({"entries": [stored_activity] if stored_activity else []})
        return FakeResponse({"tasks": [task]})

    def fake_post(url, *, json, headers, timeout):
        nonlocal stored_activity
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        assert "/activity" in url
        assert "SDK Activity comment" not in str(json)
        stored_activity = {**json, "task_id": task["task_id"], "kind": "comment", "actor_type": "user", "actor_hash": "author-hash", "event_type": "comment_added", "source_surface": "sdk_pip"}
        return FakeResponse({"entry": stored_activity})

    def fake_delete(url, *, json, headers, timeout):
        assert "/activity/" in url
        return FakeResponse({"entry": {**stored_activity, "kind": "tombstone", "encrypted_message": None, "encrypted_embed_key_material": None, "embed_refs": [], "author_hash": "author-hash", "deleted_by_hash": "author-hash", "deleted_at": 101}})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.delete", fake_delete)

    client = OpenMates(api_key=api_key)
    added = client.tasks.add_activity_comment("TASK-ACT", {"message": "SDK Activity comment", "entry_id": "activity-1", "created_at": 100})
    assert added["message"] == "SDK Activity comment"
    assert added["source_surface"] == "sdk_pip"
    assert not any(key.startswith("encrypted_") for key in added)
    assert client.tasks.list_activity("TASK-ACT")[0]["message"] == "SDK Activity comment"
    deleted = client.tasks.delete_activity_comment("TASK-ACT", "activity-1")
    assert deleted["kind"] == "tombstone"
    assert "message" not in deleted


# contract-test: supporting surface=sdks.pip assertions=tasks.external-chat.encrypted-context
def test_external_chat_lookup_hash_uses_shared_hkdf_info_literal():
    master_key = bytes(range(32))
    context = {"provider": "opencode", "id": "ses_known_derivation"}
    index_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"",
        info=b"openmates-task-external-chat-index-v1",
    ).derive(master_key)
    expected = hmac.new(index_key, b"opencode\x00ses_known_derivation", hashlib.sha256).hexdigest()

    assert _external_chat_lookup_hash(master_key, context) == expected


# contract-test: direct surface=sdks.pip assertions=tasks.content.client-encrypted,tasks.lifecycle.visible,tasks.project-links.encrypted,tasks.surface.semantic-parity
def test_pip_sdk_decrypted_task_helpers_use_api_key_master_key(monkeypatch):
    master_key = bytes([7]) * 32
    project_key = bytes([8]) * 32
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
        if url.endswith("/v1/projects?include_archived=true"):
            return FakeResponse({"projects": [{
                "project_id": "project-1",
                "encrypted_project_key": _encrypt_aes_gcm_bytes(project_key, master_key),
                "encrypted_name": _encrypt_aes_gcm_text("Project", project_key),
            }]})
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
            assert isinstance(json.get("encrypted_labels"), str)
            assert len(json.get("label_hashes", [])) == 2
            assert json.get("priority") == 3
            assert "title" not in json
            assert "labels" not in json
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
        if json.get("label_hashes"):
            assert len(json["label_hashes"]) == 2
            assert json.get("priority") == 4
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
    created = client.tasks.create({"title": "SDK parity task", "description": "Plain task body", "labels": ["SDK", "Urgent"], "priority": "high", "assign": "user"})
    assert created["title"] == "SDK parity task"
    assert created["labels"] == ["sdk", "urgent"]
    assert created["priority"] == 3
    assert created["priority_level"] == "high"
    assert "encrypted" not in created
    assert client.tasks.list(labels=["sdk", "urgent"], priority="high")[0]["title"] == "SDK parity task"
    client.tasks.list(team_id="team-1")
    edited = client.tasks.edit("TASK-1", {"title": "SDK parity task edited", "status": "in_progress", "add_labels": ["docs"], "remove_labels": ["urgent"], "priority": "urgent"}, team_id="team-1")
    assert edited["title"] == "SDK parity task edited"
    assert edited["status"] == "in_progress"
    assert edited["labels"] == ["sdk", "docs"]
    assert edited["priority_level"] == "urgent"
    assert client.tasks.start_ai("TASK-1", {"team_id": "team-1"})["status"] == "in_progress"
    assert client.tasks.block("TASK-1", "needs_user_input", team_id="team-1")["status"] == "blocked"
    assert client.tasks.unblock("TASK-1", team_id="team-1")["status"] == "todo"
    assert client.tasks.skip("TASK-1", team_id="team-1")["queue_state"] == "skipped"
    assert client.tasks.done("TASK-1", team_id="team-1")["status"] == "done"
    assert client.tasks.move("TASK-1", {"position": 42, "status": "todo"}, team_id="team-1")[0]["position"] == 42
    assert client.tasks.add_to_project("TASK-1", "project-1")["linked_project_ids"] == ["project-1"]
    assert client.tasks.remove_from_project("TASK-1", "project-1")["linked_project_ids"] == []
    assert client.tasks.delete_by_id("TASK-1", confirmed=True, team_id="team-1")["deleted"] is True
    assert any(request["url"].endswith("/v1/sdk/session") for request in requests_seen)
    assert any("priority=3" in request["url"] and request["url"].count("label_hash=") == 2 for request in requests_seen if request["method"] == "GET")
    assert any(request["method"] == "PATCH" and "team_id=team-1" in request["url"] for request in requests_seen)
    assert any(request["url"].endswith("/start-ai") and request["json"].get("team_id") == "team-1" for request in requests_seen)
    assert any(request["url"].endswith("/complete") and request["json"].get("team_id") == "team-1" for request in requests_seen)
    assert any(request["url"].endswith("/reorder") and request["json"].get("team_id") == "team-1" for request in requests_seen)
    assert any(request["method"] == "DELETE" and "team_id=team-1" in request["url"] for request in requests_seen)


# contract-test: direct surface=sdks.pip assertions=tasks.external-chat.encrypted-context,tasks.blocking.encrypted-reason,tasks.surface.semantic-parity
def test_pip_sdk_encrypts_external_chat_context_and_blocked_reason(monkeypatch):
    master_key = bytes([10]) * 32
    api_key, material = _create_api_key_material("sdk external task parity", master_key)
    stored_task = None
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        if url.endswith("/v1/user-tasks") or "/v1/user-tasks?" in url:
            return FakeResponse({"tasks": [stored_task] if stored_task else []})
        raise AssertionError(f"unexpected GET {url}")

    def fake_post(url, *, json, headers, timeout):
        nonlocal stored_task
        requests_seen.append({"method": "POST", "url": url, "json": json})
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {
                "encrypted_key": material["encrypted_master_key"],
                "salt": material["salt"],
                "key_iv": material["key_iv"],
            }})
        if url.endswith("/v1/user-tasks"):
            assert json["external_chat_provider"] == "opencode"
            assert len(json["external_chat_lookup_hash"]) == 64
            assert "ses_external_123" not in str(json)
            assert "OpenCode task bridge" not in str(json)
            stored_task = {**json, "short_id": "TASK-EXT"}
            return FakeResponse({"task": stored_task})
        if url.endswith("/block"):
            assert json["blocked_reason_code"] == "missing_credentials"
            assert "reason_text" not in json
            assert "repository write token" not in str(json)
            stored_task = {**stored_task, "status": "blocked", **json}
            return FakeResponse({"task": stored_task})
        raise AssertionError(f"unexpected POST {url}")

    def fake_patch(url, *, json, headers, timeout):
        nonlocal stored_task
        requests_seen.append({"method": "PATCH", "url": url, "json": json})
        if json.get("primary_chat_id"):
            assert json["external_chat_provider"] is None
            assert json["external_chat_lookup_hash"] is None
            assert json["encrypted_external_chat_id"] is None
            assert json["encrypted_external_chat_title"] is None
        else:
            assert json["external_chat_provider"] == "opencode"
            assert "ses_external_456" not in str(json)
            assert "Updated OpenCode task bridge" not in str(json)
        stored_task = {**stored_task, **json}
        return FakeResponse({"task": stored_task})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)

    client = OpenMates(api_key=api_key)
    created = client.tasks.create({
        "title": "Implement task bridge",
        "external_chat": "opencode:ses_external_123",
        "external_chat_title": "OpenCode task bridge",
    })

    assert created["external_chat"] == {
        "provider": "opencode",
        "id": "ses_external_123",
        "title": "OpenCode task bridge",
    }
    edited = client.tasks.edit("TASK-EXT", {
        "external_chat": {
            "provider": "opencode",
            "id": "ses_external_456",
            "title": "Updated OpenCode task bridge",
        },
    })
    assert edited["external_chat"] == {
        "provider": "opencode",
        "id": "ses_external_456",
        "title": "Updated OpenCode task bridge",
    }
    assert client.tasks.list(external_chat={"provider": "opencode", "id": "ses_external_456"})[0]["external_chat"] == edited["external_chat"]
    blocked = client.tasks.block(
        "TASK-EXT",
        "missing_credentials",
        reason_text="A repository write token is required.",
    )
    assert blocked["blocked_reason"] == "A repository write token is required."
    native = client.tasks.edit("TASK-EXT", {"chat_id": "11111111-1111-4111-8111-111111111111"})
    assert native["primary_chat_id"] == "11111111-1111-4111-8111-111111111111"
    assert native["external_chat"] is None
    native_patch = next(request["json"] for request in requests_seen if request["method"] == "PATCH" and request["json"].get("primary_chat_id"))
    assert native_patch["external_chat_provider"] is None
    assert native_patch["external_chat_lookup_hash"] is None
    assert native_patch["encrypted_external_chat_id"] is None
    assert native_patch["encrypted_external_chat_title"] is None
    assert any(
        request["method"] == "GET"
        and "external_chat_provider=opencode" in request["url"]
        and "external_chat_lookup_hash=" in request["url"]
        and "ses_external_456" not in request["url"]
        for request in requests_seen
    )
    with pytest.raises(OpenMatesConfigError, match="both native chat and external chat"):
        client.tasks.create({"title": "Invalid mixed context", "chat_id": "chat-1", "external_chat": "opencode:ses_external_123"})
    with pytest.raises(OpenMatesConfigError, match="Only opencode"):
        client.tasks.create({"title": "Unsupported provider", "external_chat": "other:session"})


# contract-test: direct surface=sdks.pip assertions=tasks.workflow-projections.read-only,tasks.surface.semantic-parity
def test_pip_sdk_keeps_workflow_projection_metadata(monkeypatch):
    api_key, _material = _create_api_key_material("sdk workflow task parity", bytes([9]) * 32)

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "tasks": [
                    {
                        "task_id": "workflow-schedule:trigger-1:1000",
                        "source": "workflow_run",
                        "projection_kind": "next_run",
                        "workflow_id": "workflow-1",
                        "workflow_run_id": None,
                        "trigger_id": "trigger-1",
                        "title": "Morning rain - 1970-01-01 00:16 UTC",
                        "status": "todo",
                        "run_status": "planned",
                        "due_at": 1000,
                        "scheduled_at": 1000,
                        "can_cancel": False,
                        "can_delete": True,
                        "position": 1000,
                        "read_only": True,
                    }
                ]
            }

    def fake_get(url, *, headers, timeout):
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert url.endswith("/v1/user-tasks")
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)

    [task] = OpenMates(api_key=api_key).tasks.list()

    assert task["source"] == "workflow_run"
    assert task["projection_kind"] == "next_run"
    assert task["workflow_id"] == "workflow-1"
    assert task["workflow_run_id"] is None
    assert task["trigger_id"] == "trigger-1"
    assert task["title"] == "Morning rain - 1970-01-01 00:16 UTC"
    assert task["due_at"] == 1000
    assert task["scheduled_at"] == 1000
    assert task["can_cancel"] is False
    assert task["can_delete"] is True
    assert task["read_only"] is True
