"""Python SDK Project contract tests.

Purpose: verify the pip SDK exposes Project listing and plain encrypted Project
links without remote-access/source management APIs.
Security: monkeypatches requests; no API keys or Project ciphertext leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_projects.py.
"""

import json

from openmates import OpenMates
from openmates.sdk import _create_api_key_material, _decrypt_aes_gcm_text, _encrypt_aes_gcm_bytes, _encrypt_aes_gcm_text


def test_pip_sdk_project_links_are_openmates_only(monkeypatch):
    master_key = bytes([9]) * 32
    project_key = bytes([8]) * 32
    chat_key = bytes([7]) * 32
    api_key, material = _create_api_key_material("pip project links", master_key)
    encrypted_project_key = _encrypt_aes_gcm_bytes(project_key, master_key)
    encrypted_chat_key = _encrypt_aes_gcm_bytes(chat_key, master_key)
    encrypted_title = _encrypt_aes_gcm_text("Planning Chat", chat_key)
    requests_seen = []
    workflow = {
        "id": "workflow-1",
        "title": "Release Workflow",
        "description": "Ship safely",
        "status": "draft",
        "enabled": False,
        "current_version_id": "version-1",
        "created_at": 100,
        "updated_at": 200,
        "graph": {"version": 1, "nodes": [], "edges": []},
    }

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
        if url.endswith("/v1/projects?include_archived=false"):
            return FakeResponse({"projects": [{"project_id": "project-1", "encrypted_project_key": encrypted_project_key}]})
        if url.endswith("/v1/projects?include_archived=true"):
            return FakeResponse({"projects": [{"project_id": "project-1", "encrypted_project_key": encrypted_project_key}]})
        if url.endswith("/v1/sdk/chats/chat-1"):
            return FakeResponse({
                "chat": {"id": "chat-1", "encrypted_chat_key": encrypted_chat_key, "encrypted_title": encrypted_title, "updated_at": 200},
                "messages": [],
            })
        if url.endswith("/v1/workflows/workflow-1"):
            return FakeResponse({"workflow": workflow})
        raise AssertionError(f"Unexpected GET {url}")

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url, "json": json})
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        if url.endswith("/v1/projects/project-1/items"):
            return FakeResponse({"item": {**json}})
        raise AssertionError(f"Unexpected POST {url}")

    def fake_delete(url, *, json, headers, timeout):
        requests_seen.append({"method": "DELETE", "url": url, "json": json})
        assert headers["Authorization"] == f"Bearer {api_key}"
        assert headers["X-OpenMates-SDK"] == "pip"
        if "/v1/projects/project-1/items?" in url:
            return FakeResponse({"deleted": True, "deleted_count": 1})
        raise AssertionError(f"Unexpected DELETE {url}")

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.delete", fake_delete)

    client = OpenMates(api_key=api_key, device_id="test-device")
    assert client.projects.list(include_archived=False)[0]["project_id"] == "project-1"

    chat_link = client.chats.add_to_project("chat-1", "project-1", folder="folder-1")
    assert chat_link["item_type"] == "chat"
    assert chat_link["folder_id"] == "folder-1"
    assert "targetMode" not in chat_link
    assert "remoteCopyProposal" not in chat_link

    workflow_link = client.workflows.add_to_project("workflow-1", "project-1")
    assert workflow_link["item_type"] == "workflow"
    assert "targetMode" not in workflow_link
    assert "remoteCopyProposal" not in workflow_link

    embed_link = client.embeds.add_to_project("embed-1", "project-1")
    assert embed_link["item_type"] == "embed"
    assert "targetMode" not in embed_link
    assert "remoteCopyProposal" not in embed_link

    assert client.chats.remove_from_project("chat-1", "project-1") == {"deleted": True, "deleted_count": 1}
    assert client.workflows.remove_from_project("workflow-1", "project-1") == {"deleted": True, "deleted_count": 1}
    assert client.embeds.remove_from_project("embed-1", "project-1") == {"deleted": True, "deleted_count": 1}

    item_bodies = [request["json"] for request in requests_seen if request["method"] == "POST" and request["url"].endswith("/v1/projects/project-1/items")]
    metadata = json.loads(_decrypt_aes_gcm_text(item_bodies[0]["encrypted_metadata"], project_key) or "{}")
    assert metadata == {"storage": "save_only_in_openmates", "source": "sdk_add_to_project"}
    delete_urls = [request["url"] for request in requests_seen if request["method"] == "DELETE"]
    assert any("item_type=chat" in url and "target_id=chat-1" in url for url in delete_urls)
    assert any("item_type=workflow" in url and "target_id=workflow-1" in url for url in delete_urls)
    assert any("item_type=embed" in url and "target_id=embed-1" in url for url in delete_urls)
    assert all("/sources" not in request["url"] for request in requests_seen)
