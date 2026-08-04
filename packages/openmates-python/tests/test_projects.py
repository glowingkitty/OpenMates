"""Python SDK Project contract tests.

Purpose: verify the pip SDK exposes Project listing and plain encrypted Project
links without remote-access/source management APIs.
Security: monkeypatches requests; no API keys or Project ciphertext leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_projects.py.
"""

import json
import hashlib

import pytest

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
        if url.endswith("/v1/projects/project-1"):
            return FakeResponse({"project": {"project_id": "project-1", "encrypted_project_key": encrypted_project_key}})
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
    assert client.projects.list(include_archived=False, personal=True)[0]["project_id"] == "project-1"

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


def test_pip_sdk_projects_explicit_personal_and_team_crud(monkeypatch):
    master_key = bytes([3]) * 32
    team_key = bytes([4]) * 32
    personal_key = bytes([5]) * 32
    team_project_key = bytes([6]) * 32
    api_key, material = _create_api_key_material("pip project crud", master_key)
    team_id = "team-1"
    team_hash = hashlib.sha256(team_id.encode()).hexdigest()

    def record(project_id, name, key, team=False):
        return {
            "project_id": project_id,
            "encrypted_project_key": None if team else _encrypt_aes_gcm_bytes(key, master_key),
            "encrypted_name": _encrypt_aes_gcm_text(name, key),
            "encrypted_description": _encrypt_aes_gcm_text("", key),
            "encrypted_icon": _encrypt_aes_gcm_text("folder", key),
            "encrypted_color": _encrypt_aes_gcm_text("default", key),
            "archived": False,
            "version": 1,
            "key_wrappers": [{
                "key_type": "team",
                "hashed_team_id": team_hash,
                "team_key_epoch": 1,
                "encrypted_project_key": _encrypt_aes_gcm_bytes(key, team_key),
            }] if team else [],
        }

    records = {
        "personal-1": record("personal-1", "Personal Project", personal_key),
        "team-project-1": record("team-project-1", "Team Project", team_project_key, True),
    }

    class FakeResponse:
        status_code = 200

        def __init__(self, payload): self._payload = payload
        def json(self): return self._payload

    def fake_request(method, url, *, json=None, headers, timeout):
        assert headers["Authorization"] == f"Bearer {api_key}"
        path = url.split("https://api.openmates.org", 1)[-1]
        if path == "/v1/sdk/session":
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        if path == f"/v1/teams/{team_id}":
            return FakeResponse({"team": {"team_id": team_id, "encrypted_team_key": _encrypt_aes_gcm_bytes(team_key, master_key)}})
        team = f"team_id={team_id}" in path
        clean_path = path.split("?", 1)[0]
        if method == "GET" and clean_path == "/v1/projects":
            return FakeResponse({"projects": [records["team-project-1" if team else "personal-1"]]})
        if method == "GET" and clean_path.startswith("/v1/projects/"):
            project_id = clean_path.rsplit("/", 1)[-1]
            return FakeResponse({"project": records[project_id], "folders": [], "items": []})
        if method == "POST" and clean_path == "/v1/projects":
            records[json["project_id"]] = {**json, "version": 1}
            return FakeResponse({"project": records[json["project_id"]]})
        if method == "PATCH" and clean_path.startswith("/v1/projects/"):
            project_id = clean_path.rsplit("/", 1)[-1]
            records[project_id] = {**records[project_id], **json, "version": 2}
            return FakeResponse({"project": records[project_id]})
        if method == "DELETE" and clean_path.startswith("/v1/projects/"):
            return FakeResponse({"deleted": True})
        raise AssertionError(f"Unexpected {method} {path}")

    monkeypatch.setattr("openmates.sdk.requests.get", lambda url, **kwargs: fake_request("GET", url, **kwargs))
    monkeypatch.setattr("openmates.sdk.requests.post", lambda url, **kwargs: fake_request("POST", url, **kwargs))
    monkeypatch.setattr("openmates.sdk.requests.patch", lambda url, **kwargs: fake_request("PATCH", url, **kwargs))
    monkeypatch.setattr("openmates.sdk.requests.delete", lambda url, **kwargs: fake_request("DELETE", url, **kwargs))

    client = OpenMates(api_key=api_key, device_id="test-device")
    assert client.projects.list(personal=True)[0]["name"] == "Personal Project"
    assert client.projects.list(team_id=team_id)[0]["name"] == "Team Project"
    assert client.projects.show("team-project-1", team_id=team_id)["name"] == "Team Project"
    created = client.projects.create({"name": "Created Team"}, team_id=team_id)
    assert created["name"] == "Created Team"
    assert client.projects.update(created["project_id"], {"name": "Updated Team"}, team_id=team_id)["name"] == "Updated Team"
    assert client.projects.archive(created["project_id"], team_id=team_id)["archived"] is True
    assert client.projects.unarchive(created["project_id"], team_id=team_id)["archived"] is False
    with pytest.raises(Exception, match="confirmed=True"):
        client.projects.delete(created["project_id"], team_id=team_id, confirmed=False)
    assert client.projects.delete(created["project_id"], team_id=team_id, confirmed=True) == {"deleted": True}
    with pytest.raises(Exception, match="explicit Personal or Team context"):
        client.projects.list()
    assert not hasattr(client.projects, "files")
