"""Python SDK workflow contract tests.

Purpose: verify the pip SDK exposes the same workflow CRUD/run/history contract
as CLI/npm without real network calls.
Security: monkeypatches requests; no API keys or workflow payloads leave tests.
Run: python3 -m pytest packages/openmates-python/tests/test_workflows.py
"""

import pytest

from openmates import OpenMates, OpenMatesConfigError


def minimal_graph():
    return {
        "version": 1,
        "trigger_node_id": "trigger",
        "nodes": [
            {"id": "trigger", "type": "manual_trigger", "config": {}},
        ],
        "edges": [],
    }


def test_pip_sdk_workflow_methods_use_shared_workflows_api(monkeypatch):
    requests_seen = []
    graph = minimal_graph()

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, *, headers, timeout):
        requests_seen.append({"method": "GET", "url": url})
        if url.endswith("/v1/workflows"):
            return FakeResponse({"workflows": [{"id": "wf-1", "title": "Morning"}]})
        if url.endswith("/v1/workflows/temporary"):
            return FakeResponse({"workflows": [{"id": "wf-temp", "title": "Temporary", "lifecycle": "temporary"}]})
        if url.endswith("/v1/workflows/capabilities"):
            return FakeResponse({"capabilities": [{"id": "weather:forecast", "enabled": True}]})
        if url.endswith("/v1/workflows/wf-1/runs"):
            return FakeResponse({"runs": [{"id": "run-1", "status": "completed"}]})
        if url.endswith("/v1/workflows/wf-1/runs/run-1"):
            return FakeResponse({"run": {"id": "run-1", "status": "completed"}})
        return FakeResponse({"workflow": {"id": "wf-1", "title": "Morning", "graph": graph}})

    def fake_post(url, *, json, headers, timeout):
        requests_seen.append({"method": "POST", "url": url, "json": json})
        if url.endswith("/run"):
            return FakeResponse({"run": {"id": "run-1", "status": "completed"}})
        return FakeResponse({"workflow": {"id": "wf-1", "title": json.get("title", "Morning"), "graph": graph}})

    def fake_patch(url, *, json, headers, timeout):
        requests_seen.append({"method": "PATCH", "url": url, "json": json})
        return FakeResponse({"workflow": {"id": "wf-1", "title": "Updated", "graph": graph}})

    def fake_delete(url, *, json, headers, timeout):
        requests_seen.append({"method": "DELETE", "url": url, "json": json})
        return FakeResponse({"deleted": True})

    monkeypatch.setattr("openmates.sdk.requests.get", fake_get)
    monkeypatch.setattr("openmates.sdk.requests.post", fake_post)
    monkeypatch.setattr("openmates.sdk.requests.patch", fake_patch)
    monkeypatch.setattr("openmates.sdk.requests.delete", fake_delete)

    client = OpenMates(api_key="x")
    assert client.workflows.list()[0]["id"] == "wf-1"
    assert client.workflows.temporary()[0]["id"] == "wf-temp"
    assert client.workflows.capabilities()[0]["id"] == "weather:forecast"
    assert client.workflows.create(
        title="Morning",
        graph=graph,
        enabled=True,
        run_content_retention="none",
        lifecycle="temporary",
        source="chat",
        source_chat_id="chat-1",
        created_by_assistant=True,
    )["id"] == "wf-1"
    assert client.workflows.get("wf-1")["id"] == "wf-1"
    assert client.workflows.update("wf-1", enabled=False, run_content_retention="last_5")["id"] == "wf-1"
    assert client.workflows.enable("wf-1")["id"] == "wf-1"
    assert client.workflows.disable("wf-1")["id"] == "wf-1"
    assert client.workflows.keep("wf-1")["id"] == "wf-1"
    assert client.workflows.run("wf-1", mode="test", input_data={"dry": True})["id"] == "run-1"
    assert client.workflows.runs("wf-1")[0]["id"] == "run-1"
    assert client.workflows.run_detail("wf-1", "run-1")["id"] == "run-1"
    assert client.workflows.delete("wf-1", confirmed=True)["deleted"] is True

    assert requests_seen == [
        {"method": "GET", "url": "https://api.openmates.org/v1/workflows"},
        {"method": "GET", "url": "https://api.openmates.org/v1/workflows/temporary"},
        {"method": "GET", "url": "https://api.openmates.org/v1/workflows/capabilities"},
        {"method": "POST", "url": "https://api.openmates.org/v1/workflows", "json": {"title": "Morning", "graph": graph, "enabled": True, "run_content_retention": "none", "lifecycle": "temporary", "source": "chat", "created_by_assistant": True, "source_chat_id": "chat-1"}},
        {"method": "GET", "url": "https://api.openmates.org/v1/workflows/wf-1"},
        {"method": "PATCH", "url": "https://api.openmates.org/v1/workflows/wf-1", "json": {"enabled": False, "run_content_retention": "last_5"}},
        {"method": "POST", "url": "https://api.openmates.org/v1/workflows/wf-1/enable", "json": {}},
        {"method": "POST", "url": "https://api.openmates.org/v1/workflows/wf-1/disable", "json": {}},
        {"method": "POST", "url": "https://api.openmates.org/v1/workflows/wf-1/keep", "json": {}},
        {"method": "POST", "url": "https://api.openmates.org/v1/workflows/wf-1/run", "json": {"mode": "test", "input": {"dry": True}}},
        {"method": "GET", "url": "https://api.openmates.org/v1/workflows/wf-1/runs"},
        {"method": "GET", "url": "https://api.openmates.org/v1/workflows/wf-1/runs/run-1"},
        {"method": "DELETE", "url": "https://api.openmates.org/v1/workflows/wf-1", "json": None},
    ]


def test_pip_sdk_workflows_require_api_key():
    client = OpenMates(api_key=None)
    with pytest.raises(OpenMatesConfigError, match="API key is required"):
        client.workflows.list()


def test_pip_sdk_workflow_delete_requires_confirmation():
    client = OpenMates(api_key="x")
    with pytest.raises(OpenMatesConfigError, match="Deleting a workflow"):
        client.workflows.delete("wf-1")
