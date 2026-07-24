"""Python SDK Project source contract tests.

Purpose: verify the pip SDK exposes encrypted /v1/projects/{id}/sources parity
with CLI/npm without real network calls.
Security: monkeypatches requests; no API keys or source ciphertext leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_projects.py.
"""

import pytest

from openmates import OpenMates, OpenMatesConfigError
from openmates.sdk import _create_api_key_material, _encrypt_aes_gcm_bytes, _encrypt_aes_gcm_text


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

SOURCE_INPUT = {
    "source_id": "source-1",
    "source_type": "remote_git_repository",
    "display_name": "Repository Source",
    "metadata": {"root": "/repo", "redacted": True},
    "capabilities": ["read", "search"],
    "status": "connected",
    "created_at": 100,
    "updated_at": 100,
}

ITEM = {
    "project_item_id": "project-item-1",
    "item_type": "chat",
    "target_id": "chat-1",
    "target_id_encrypted": "cipher-target",
    "encrypted_display_name": "cipher-display",
    "encrypted_note": "cipher-note",
    "encrypted_metadata": "cipher-metadata",
    "created_at": 100,
    "updated_at": 100,
}


def test_pip_sdk_project_source_methods_use_shared_projects_api(monkeypatch):
    master_key = bytes([5]) * 32
    project_key = bytes([6]) * 32
    api_key, material = _create_api_key_material("pip source parity", master_key)
    encrypted_project_key = _encrypt_aes_gcm_bytes(project_key, master_key)
    encrypted_source = {
        **SOURCE,
        "encrypted_display_name": _encrypt_aes_gcm_text("Repository Source", project_key),
        "encrypted_metadata": _encrypt_aes_gcm_text('{"root":"/repo","redacted":true}', project_key),
    }
    requests_seen = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        if url.endswith("/v1/projects?include_archived=true"):
            return FakeResponse({"projects": [{"project_id": "project-1", "encrypted_project_key": encrypted_project_key}]})
        return FakeResponse({"sources": [encrypted_source]})

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url, "json": json})
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        if url.endswith("/items"):
            return FakeResponse({"item": {**ITEM, **json}})
        return FakeResponse({"source": {**encrypted_source, **json}})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key, device_id="test-device")
    assert client.projects.list(include_archived=True)[0]["project_id"] == "project-1"
    assert client.projects.list_sources("project-1")[0]["display_name"] == "Repository Source"
    assert client.projects.create_source("project-1", SOURCE_INPUT)["display_name"] == "Repository Source"
    assert client.projects.create_item("project-1", ITEM)["project_item_id"] == "project-item-1"

    assert [(request["method"], request["url"]) for request in requests_seen] == [
        ("GET", "https://api.openmates.org/v1/projects?include_archived=true"),
        ("GET", "https://api.openmates.org/v1/projects?include_archived=true"),
        ("POST", "https://api.openmates.org/v1/sdk/session"),
        ("GET", "https://api.openmates.org/v1/projects/project-1/sources"),
        ("GET", "https://api.openmates.org/v1/projects?include_archived=true"),
        ("POST", "https://api.openmates.org/v1/projects/project-1/sources"),
        ("POST", "https://api.openmates.org/v1/projects/project-1/items"),
    ]
    assert requests_seen[5]["json"]["encrypted_display_name"] != SOURCE_INPUT["display_name"]
    assert requests_seen[6]["json"] == ITEM


def test_pip_sdk_project_source_create_requires_source_type_and_display_name():
    client = OpenMates(api_key="x")
    with pytest.raises(OpenMatesConfigError, match="requires source_type"):
        client.projects.create_source("project-1", {"display_name": "Repository Source"})
    with pytest.raises(OpenMatesConfigError, match="requires display_name"):
        client.projects.create_source("project-1", {"source_type": "remote_git_repository"})


def test_pip_sdk_returns_non_mutating_project_remote_copy_proposals(monkeypatch):
    master_key = bytes([9]) * 32
    project_key = bytes([8]) * 32
    chat_key = bytes([7]) * 32
    api_key, material = _create_api_key_material("pip project proposals", master_key)
    encrypted_project_key = _encrypt_aes_gcm_bytes(project_key, master_key)
    encrypted_chat_key = _encrypt_aes_gcm_bytes(chat_key, master_key)
    encrypted_title = _encrypt_aes_gcm_text("Planning Chat", chat_key)
    encrypted_message = _encrypt_aes_gcm_text("Email me at test@example.com", chat_key)
    workflow = {
        "id": "workflow-1",
        "title": "Release Workflow",
        "description": "Ship safely",
        "status": "draft",
        "enabled": False,
        "current_version_id": "version-1",
        "created_at": 100,
        "updated_at": 200,
        "graph": {
            "version": 1,
            "nodes": [{"id": "manual:trigger", "type": "manual_trigger", "title": "Manual trigger"}],
            "edges": [{"from": "manual:trigger", "to": "end"}],
        },
    }

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        if url.endswith("/v1/projects/project-1/sources"):
            return FakeResponse({"sources": [SOURCE]})
        if url.endswith("/v1/projects?include_archived=true"):
            return FakeResponse({"projects": [{"project_id": "project-1", "encrypted_project_key": encrypted_project_key}]})
        if url.endswith("/v1/sdk/chats/chat-1"):
            return FakeResponse({
                "chat": {"id": "chat-1", "encrypted_chat_key": encrypted_chat_key, "encrypted_title": encrypted_title, "updated_at": 200},
                "messages": [{"id": "message-1", "role": "user", "created_at": 100, "encrypted_content": encrypted_message}],
            })
        if url.endswith("/v1/workflows/workflow-1"):
            return FakeResponse({"workflow": workflow})
        raise AssertionError(f"Unexpected GET {url}")

    def fake_post(url, *, json, headers, timeout):
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        if url.endswith("/v1/projects/project-1/items"):
            return FakeResponse({"item": {**ITEM, **json}})
        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=api_key, device_id="test-device")
    chat_link = client.chats.add_to_project("chat-1", "project-1", remote_cache_copy=True)
    assert chat_link["targetMode"] == "store_local_only_on_remote_machine"
    assert chat_link["remoteCopyProposal"]["writes_files"] is False
    assert chat_link["remoteCopyProposal"]["target_path"] == "~/.openmates/remote-cache/source-1/exports/chat/planning-chat.md"
    assert chat_link["remoteCopyProposal"]["pii_scan_result"]["found"] is True

    workflow_link = client.workflows.add_to_project("workflow-1", "project-1", remote_copy=True)
    assert workflow_link["targetMode"] == "store_on_remote_machine_and_include_in_git"
    assert workflow_link["remoteCopyProposal"]["target_path"] == ".openmates/workflows/release-workflow.yml"
    workflow_yaml = workflow_link["remoteCopyProposal"]["diff_or_create_file_patch"]["content"]
    assert 'graph:\n  version: 1\n  nodes:\n    -\n      id: "manual:trigger"' in workflow_yaml
    assert '  edges:\n    -\n      from: "manual:trigger"\n      to: end' in workflow_yaml


def test_pip_sdk_exposes_reserved_instruction_audit_methods_with_consent_gates():
    client = OpenMates(api_key="x")
    with pytest.raises(OpenMatesConfigError, match="requires confirmed=True"):
        client.projects.audit_instructions("project-1", "source-1")
    with pytest.raises(OpenMatesConfigError, match="Project instruction audit is not available"):
        client.projects.audit_instructions("project-1", "source-1", confirmed=True)
    with pytest.raises(OpenMatesConfigError, match="requires confirmed=True"):
        client.projects.apply_selected_instruction_audit_suggestions("project-1", "source-1", ["suggestion-1"])
    with pytest.raises(OpenMatesConfigError, match="Project instruction audit status is not available"):
        client.projects.get_instruction_audit_status("project-1", "source-1")
