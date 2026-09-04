"""Python SDK workflow contract tests.

Purpose: verify the pip SDK exposes the same workflow CRUD/run/history contract
as CLI/npm without real network calls.
Security: monkeypatches requests; no API keys or workflow payloads leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_workflows.py
"""

import pytest

from openmates import OpenMates, OpenMatesApiError, OpenMatesConfigError
from openmates.sdk import _create_api_key_material, _encrypted_object_slug_metadata, _encrypt_aes_gcm_bytes, _encrypt_aes_gcm_text


CHAT_ID = "11111111-1111-4111-8111-111111111111"
PROJECT_ID = "22222222-2222-4222-8222-222222222222"


def minimal_graph():
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "config": {}},
        ],
        "edges": [],
    }


def blank_graph():
    return {
        "version": 1,
        "trigger_node_id": None,
        "nodes": [],
        "edges": [],
    }


def template_import_payload():
    return {
        "template_version": 1,
        "title": "Morning",
        "trigger_template": {"type": "manual_trigger", "config": {}},
        "node_templates": [],
        "edge_templates": [],
        "variables_schema": {},
        "required_capabilities": [],
        "binding_requirements": [],
    }


def assert_public_workflow_slug(workflow, slug):
    assert workflow["slug"] == slug
    assert "encrypted_slug" not in workflow
    assert "slug_lookup_hash" not in workflow


# contract-test: direct surface=sdks.pip assertions=workflows.activation.reachable-side-effect,workflows.surface.semantic-parity,workflows-ui.identity.automatic-category-icon,sdk.encryption.local-only,sdk.surface.semantic-parity
def test_pip_sdk_workflow_methods_use_shared_workflows_api(monkeypatch):
    requests_seen = []
    graph = minimal_graph()
    master_key = bytes([11]) * 32
    chat_key = bytes([12]) * 32
    project_key = bytes([13]) * 32
    api_key, material = _create_api_key_material("pip workflow parity", master_key)
    encrypted_chat_key = _encrypt_aes_gcm_bytes(chat_key, master_key)
    encrypted_project_key = _encrypt_aes_gcm_bytes(project_key, master_key)
    slug_metadata = _encrypted_object_slug_metadata("Morning", encryption_key=master_key, lookup_key=master_key)
    temp_slug_metadata = _encrypted_object_slug_metadata("Temporary", encryption_key=master_key, lookup_key=master_key)
    encrypted_slug_fields = {
        "encrypted_slug": slug_metadata["encrypted_slug"],
        "slug_lookup_hash": slug_metadata["slug_lookup_hash"],
    }
    encrypted_temp_slug_fields = {
        "encrypted_slug": temp_slug_metadata["encrypted_slug"],
        "slug_lookup_hash": temp_slug_metadata["slug_lookup_hash"],
    }

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        if url.endswith("/v1/sdk/chats?limit=0&offset=0"):
            return FakeResponse({"chats": [{"id": CHAT_ID, "encrypted_chat_key": encrypted_chat_key, "encrypted_title": _encrypt_aes_gcm_text("Chat", chat_key)}]})
        if url.endswith("/v1/projects?include_archived=true"):
            return FakeResponse({"projects": [{"project_id": PROJECT_ID, "encrypted_project_key": encrypted_project_key, "encrypted_name": _encrypt_aes_gcm_text("Project", project_key)}]})
        if url.endswith("/v1/workflows"):
            return FakeResponse({"workflows": [{"id": "wf-1", "title": "Morning", "category": "science", "icon": "cloud-rain", **encrypted_slug_fields}]})
        if url.endswith("/v1/workflows/temporary"):
            return FakeResponse({"workflows": [{"id": "wf-temp", "title": "Temporary", "lifecycle": "temporary", **encrypted_temp_slug_fields}]})
        if url.endswith("/v1/workflows/capabilities"):
            return FakeResponse({"capabilities": [{"id": "weather:forecast", "enabled": True}]})
        if url.endswith("/v1/workflows/input/session-1"):
            return FakeResponse({"session": {"session_id": "session-1", "status": "executed", "event_cursor": 4, "undo_available": True, "events": []}})
        if url.endswith("/v1/workflows/input/session-1/events?after_event_id=2"):
            return FakeResponse({"events": [{"id": "event-3", "session_id": "session-1", "event_id": 3, "type": "validation_passed", "status": "ok", "redacted_summary": "object:0", "created_at": 1}]})
        if url.endswith("/v1/workflows/wf-1/runs"):
            return FakeResponse({"runs": [{"id": "run-1", "status": "completed"}]})
        if url.endswith("/v1/workflows/wf-1/runs/run-1"):
            return FakeResponse({"run": {"id": "run-1", "status": "completed", "node_runs": [{"id": "node-run-1", "node_id": "weather", "status": "completed", "output_summary": {"forecast": "rain"}, "credits_charged": 2}]}})
        return FakeResponse({"workflow": {"id": "wf-1", "title": "Morning", "graph": graph, **encrypted_slug_fields}})

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url, "json": json})
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        if url.endswith("/v1/share/short-url"):
            return FakeResponse({"success": True, "expires_at": 999})
        if url.endswith("/v1/workflows/template-import"):
            return FakeResponse({"workflow": {"id": "wf-imported", "title": "Morning", "binding_requirements": [], **encrypted_slug_fields}})
        if url.endswith("/v1/workflows/input"):
            return FakeResponse({"session": {"session_id": "session-1", "status": "executed", "event_cursor": 4, "undo_available": True}})
        if url.endswith("/v1/workflows/input/session-1/follow-up"):
            return FakeResponse({"session": {"session_id": "session-1", "status": "executed", "event_cursor": 7, "undo_available": True}})
        if url.endswith("/v1/workflows/input/session-1/stop"):
            return FakeResponse({"session": {"session_id": "session-1", "status": "stopped", "event_cursor": 8, "undo_available": True}})
        if url.endswith("/v1/workflows/input/session-1/undo"):
            return FakeResponse({"session": {"session_id": "session-1", "status": "undone", "event_cursor": 9, "undo_available": False}})
        if url.endswith("/v1/workflows/validate"):
            assert json == {"source": "title: Morning\n"}
            return FakeResponse({"validation": {"draft_valid": True, "enable_ready": False, "diagnostics": [{"code": "REQUIRED_RUNTIME_INPUT"}]}})
        if url.endswith("/v1/workflows/yaml"):
            assert json == {"source": "title: Morning\n"}
            return FakeResponse({"workflow": {"id": "wf-yaml", "title": "Morning", "graph": graph, **encrypted_slug_fields}, "validation": {"draft_valid": True, "enable_ready": True, "diagnostics": []}})
        if url.endswith("/v1/workflows/wf-1/yaml"):
            assert json == {"source": "title: Updated\n"}
            return FakeResponse({"workflow": {"id": "wf-1", "title": "Updated", "graph": graph, **encrypted_slug_fields}, "validation": {"draft_valid": True, "enable_ready": True, "diagnostics": []}})
        if url.endswith("/run"):
            assert headers["Idempotency-Key"] == "stable-run-1"
            return FakeResponse({"run": {"id": "run-1", "status": "completed"}})
        if url.endswith("/v1/workflows/wf-1/steps/math/test"):
            assert json == {"input": {"expression": "2 + 2"}, "confirmed": True}
            return FakeResponse({"run": {"id": "run-step-1", "trigger_type": "step_test", "status": "completed", "node_runs": [{"id": "node-run-step-1", "node_id": "math", "status": "completed", "output_summary": {"result": "4"}}]}})
        if url.endswith("/runs/run-1/cancel"):
            return FakeResponse({"run_id": "run-1", "status": "cancellation_requested"})
        if url.endswith("/runs/run-1/respond"):
            assert json == {"step_id": "ask", "input": {"answer": "Berlin"}}
            return FakeResponse({"run": {"id": "run-1", "status": "completed"}})
        return FakeResponse({"workflow": {"id": "wf-1", "title": json.get("title", "Morning"), "enabled": json.get("enabled", True), "graph": json.get("graph", graph), **encrypted_slug_fields}})

    def fake_patch(url, *, json, headers, timeout):
        requests_seen.append({"method": "PATCH", "url": url, "json": json})
        return FakeResponse({"workflow": {"id": "wf-1", "title": "Updated", "graph": graph, **encrypted_slug_fields}})

    def fake_put(url, *, json, headers, timeout):
        requests_seen.append({"method": "PUT", "url": url, "json": json})
        return FakeResponse({"template_id": "tpl-1", "source_version": 2, "updated_at": 123})

    def fake_delete(url, *, json, headers, timeout):
        requests_seen.append({"method": "DELETE", "url": url, "json": json})
        if url.endswith("/v1/share/short-url/Abc123XY"):
            return FakeResponse({"success": True, "revoked_at": 1000})
        return FakeResponse({"deleted": True})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)
    monkeypatch.setattr("openmates.sdk.requests.put", fake_put)
    monkeypatch.setattr("openmates.sdk.requests.delete", fake_delete)

    client = OpenMates(api_key=api_key)
    listed_workflow = client.workflows.list()[0]
    temporary_workflow = client.workflows.temporary()[0]
    assert listed_workflow["id"] == "wf-1"
    assert listed_workflow["category"] == "science"
    assert listed_workflow["icon"] == "cloud-rain"
    assert temporary_workflow["id"] == "wf-temp"
    assert_public_workflow_slug(listed_workflow, "morning")
    assert_public_workflow_slug(temporary_workflow, "temporary")
    assert client.workflows.capabilities()[0]["id"] == "weather:forecast"
    assert client.workflows.start_input(text="alert me if it rains", selected_project_id=PROJECT_ID)["session_id"] == "session-1"
    assert client.workflows.input_session("session-1")["status"] == "executed"
    assert client.workflows.input_events("session-1", after_event_id=2)[0]["type"] == "validation_passed"
    assert client.workflows.follow_up_input("session-1", "weekdays only")["event_cursor"] == 7
    assert client.workflows.stop_input("session-1")["status"] == "stopped"
    assert client.workflows.undo_input("session-1")["status"] == "undone"
    assert client.workflows.validate_yaml("title: Morning\n")["draft_valid"] is True
    created_from_yaml = client.workflows.create_from_yaml("title: Morning\n")["workflow"]
    updated_from_yaml = client.workflows.update_from_yaml("wf-1", "title: Updated\n")["workflow"]
    blank_workflow = client.workflows.create(title="Blank", graph=blank_graph(), enabled=False)
    created_workflow = client.workflows.create(
        title="Morning",
        graph=graph,
        enabled=True,
        run_content_retention="none",
        lifecycle="temporary",
        source="chat",
        source_chat_id=CHAT_ID,
        created_by_assistant=True,
    )
    fetched_workflow = client.workflows.get("wf-1")
    updated_workflow = client.workflows.update("wf-1", enabled=False, run_content_retention="last_5")
    enabled_workflow = client.workflows.enable("wf-1")
    disabled_workflow = client.workflows.disable("wf-1")
    kept_workflow = client.workflows.keep("wf-1")
    assert created_from_yaml["id"] == "wf-yaml"
    assert updated_from_yaml["title"] == "Updated"
    assert blank_workflow["graph"]["trigger_node_id"] is None
    assert blank_workflow["graph"]["nodes"] == []
    assert created_workflow["id"] == "wf-1"
    assert fetched_workflow["id"] == "wf-1"
    assert updated_workflow["id"] == "wf-1"
    assert enabled_workflow["id"] == "wf-1"
    assert disabled_workflow["id"] == "wf-1"
    assert kept_workflow["id"] == "wf-1"
    for workflow in [created_from_yaml, updated_from_yaml, blank_workflow, created_workflow, fetched_workflow, updated_workflow, enabled_workflow, disabled_workflow, kept_workflow]:
        assert_public_workflow_slug(workflow, "morning")
    assert client.workflows.run("wf-1", idempotency_key="stable-run-1", mode="test", input_data={"dry": True})["id"] == "run-1"
    assert client.workflows.runs("wf-1")[0]["id"] == "run-1"
    assert client.workflows.run_detail("wf-1", "run-1")["node_runs"][0]["output_summary"]["forecast"] == "rain"
    assert client.workflows.step_test("wf-1", "math", input_data={"expression": "2 + 2"}, confirmed=True)["trigger_type"] == "step_test"
    assert client.workflows.cancel_run("wf-1", "run-1")["status"] == "cancellation_requested"
    assert client.workflows.respond("wf-1", "run-1", "ask", {"answer": "Berlin"})["status"] == "completed"
    assert client.workflows.upsert_template_projection(
        "wf-1",
        template_id="tpl-1",
        source_version=2,
        ciphertext="opaque-ciphertext",
        ciphertext_checksum="sha256:abc",
        owner_wrapped_key="wrapped-key",
        projection_schema_version=1,
    )["updated_at"] == 123
    assert client.workflows.create_template_short_url(
        token="Abc123XY",
        encrypted_url="opaque-url",
        template_id="tpl-1",
        ttl_seconds=3600,
    )["expires_at"] == 999
    assert client.workflows.revoke_short_url("Abc123XY")["revoked_at"] == 1000
    imported_workflow = client.workflows.import_template(template_import_payload())
    assert imported_workflow["id"] == "wf-imported"
    assert_public_workflow_slug(imported_workflow, "morning")
    assert client.workflows.delete("wf-1", confirmed=True)["deleted"] is True

    workflow_input = next(request for request in requests_seen if request["method"] == "POST" and request["url"].endswith("/v1/workflows/input"))
    assert workflow_input["json"] == {"input_type": "text", "text": "alert me if it rains", "selected_project_id": PROJECT_ID}
    workflow_create = next(request for request in requests_seen if request["method"] == "POST" and request["url"].endswith("/v1/workflows") and request["json"].get("title") == "Morning")
    blank_create = next(request for request in requests_seen if request["method"] == "POST" and request["url"].endswith("/v1/workflows") and request["json"].get("title") == "Blank")
    assert blank_create["json"]["graph"] == blank_graph()
    assert blank_create["json"]["enabled"] is False
    assert workflow_create["json"]["source_chat_id"] == CHAT_ID
    assert isinstance(workflow_create["json"].get("encrypted_slug"), str)
    assert isinstance(workflow_create["json"].get("slug_lookup_hash"), str)
    assert "slug" not in workflow_create["json"]
    assert {"method": "POST", "url": "https://api.openmates.org/v1/workflows/wf-1/run", "json": {"mode": "test", "input": {"dry": True}}} in requests_seen
    assert {"method": "PUT", "url": "https://api.openmates.org/v1/workflows/wf-1/template-projection", "json": {"template_id": "tpl-1", "source_version": 2, "ciphertext": "opaque-ciphertext", "ciphertext_checksum": "sha256:abc", "owner_wrapped_key": "wrapped-key", "projection_schema_version": 1}} in requests_seen
    assert {"method": "DELETE", "url": "https://api.openmates.org/v1/workflows/wf-1", "json": None} in requests_seen


# contract-test: supporting surface=sdks.pip assertions=workflows.surface.semantic-parity,sdk.surface.semantic-parity
def test_pip_sdk_workflows_require_api_key():
    client = OpenMates(api_key=None)
    with pytest.raises(OpenMatesConfigError, match="API key is required"):
        client.workflows.list()


# contract-test: direct surface=sdks.pip assertions=workflows.surface.semantic-parity,sdk.surface.semantic-parity
def test_pip_sdk_workflow_template_sharing_transport_uses_shared_api(monkeypatch):
    requests_seen = []
    master_key = bytes([14]) * 32
    api_key, material = _create_api_key_material("pip workflow templates", master_key)

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        if url.endswith("/v1/workflows"):
            assert headers["Authorization"] == f"Bearer {api_key}"
            return FakeResponse({"workflows": [{"id": "wf-1", "title": "Morning"}]})
        assert url.endswith("/v1/workflows/template-projections/tpl-1")
        assert "Authorization" not in headers
        return FakeResponse({
            "template_id": "tpl-1",
            "ciphertext": "opaque-ciphertext",
            "ciphertext_checksum": "sha256:abc",
            "projection_schema_version": 1,
        })

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url, "json": json})
        if url.endswith("/v1/sdk/session"):
            return FakeResponse({"key_wrapper": {"encrypted_key": material["encrypted_master_key"], "salt": material["salt"], "key_iv": material["key_iv"]}})
        if url.endswith("/v1/workflows/wf-1/template-projection/revoke"):
            assert json == {}
            return FakeResponse({"template_id": "tpl-1", "revoked_at": 1000})
        if url.endswith("/v1/workflows/wf-1/template-projection/unrevoke"):
            assert json == {}
            return FakeResponse({"template_id": "tpl-1", "revoked_at": None})
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key=None)
    assert client.workflows.get_public_template_projection("tpl-1")["ciphertext"] == "opaque-ciphertext"
    client = OpenMates(api_key=api_key)
    assert client.workflows.revoke_template_projection("wf-1")["revoked_at"] == 1000
    assert client.workflows.unrevoke_template_projection("wf-1")["revoked_at"] is None

    assert requests_seen == [
        {"method": "GET", "url": "https://api.openmates.org/v1/workflows/template-projections/tpl-1"},
        {"method": "GET", "url": "https://api.openmates.org/v1/workflows"},
        {"method": "POST", "url": "https://api.openmates.org/v1/workflows/wf-1/template-projection/revoke", "json": {}},
        {"method": "GET", "url": "https://api.openmates.org/v1/workflows"},
        {"method": "POST", "url": "https://api.openmates.org/v1/workflows/wf-1/template-projection/unrevoke", "json": {}},
    ]


# contract-test: supporting surface=sdks.pip assertions=workflows.surface.semantic-parity,sdk.surface.semantic-parity
def test_pip_sdk_workflow_delete_requires_confirmation():
    client = OpenMates(api_key="x")
    with pytest.raises(OpenMatesConfigError, match="Deleting a workflow"):
        client.workflows.delete("wf-1")


# contract-test: supporting surface=sdks.pip assertions=workflows.surface.semantic-parity,sdk.surface.semantic-parity
def test_pip_sdk_workflow_template_import_rejects_malformed_response(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {}

    def fake_post(url, *, json, headers, timeout):
        assert url.endswith("/v1/workflows/template-import")
        return FakeResponse()

    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)

    client = OpenMates(api_key="x")
    with pytest.raises(OpenMatesApiError, match="HTTP 500"):
        client.workflows.import_template(template_import_payload())
