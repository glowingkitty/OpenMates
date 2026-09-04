#!/usr/bin/env python3
"""Contract tests for the private control-plane client in scripts/tests.py.

The adapter must preserve normalized state and campaign semantics while using
only the independent API token. It must never mint Directus credentials or
silently fall back to product PostgreSQL or local JSON state.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_CONTROL_PATH = PROJECT_ROOT / "scripts" / "tests.py"


def load_tests_control():
    spec = importlib.util.spec_from_file_location("openmates_tests_control_api", TESTS_CONTROL_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_default_store_requires_independent_api_token(monkeypatch) -> None:
    control = load_tests_control()
    monkeypatch.delenv("OPENMATES_TEST_CONTROL_BACKEND", raising=False)
    monkeypatch.delenv("ENGINEERING_CONTROL_PLANE_API_TOKEN", raising=False)
    monkeypatch.setenv("OPENMATES_DISABLE_CONTROL_PLANE_ENV_FILE", "1")
    monkeypatch.setenv("DIRECTUS_TOKEN", "must-not-be-used")

    with pytest.raises(RuntimeError, match="no Directus, product-database, or local-JSON fallback"):
        control.get_store()


def test_api_store_loads_state_without_product_access(monkeypatch) -> None:
    control = load_tests_control()
    monkeypatch.setenv("ENGINEERING_CONTROL_PLANE_API_TOKEN", "private-token")
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        if "/test_current_state?" in request.full_url:
            return FakeResponse(
                {
                    "records": [
                        {
                            "test_key": "pytest::one",
                            "suite": "pytest",
                            "test_name": "one",
                            "stable_status": "passed",
                            "stable_run_key": "run-1",
                            "active_status": None,
                            "active_run_key": None,
                            "metadata": {},
                            "updated_at": "2026-08-26T12:00:00Z",
                        }
                    ]
                }
            )
        if "/test_runs?" in request.full_url:
            return FakeResponse({"records": [{"run_key": "run-1", "summary": {"passed": 1}}]})
        raise AssertionError(request.full_url)

    monkeypatch.setattr(control.urllib.request, "urlopen", fake_urlopen)
    state = control.get_store().load_state()

    assert state["tests"]["pytest::one"]["status"] == "passed"
    assert state["latest_run_summary"] == {"passed": 1}
    assert all(call[0].headers["Authorization"] == "Bearer private-token" for call in calls)
    assert all("8055" not in call[0].full_url for call in calls)


def test_state_save_uses_one_atomic_import(monkeypatch) -> None:
    control = load_tests_control()
    monkeypatch.setenv("ENGINEERING_CONTROL_PLANE_API_TOKEN", "private-token")
    captured = []

    def fake_urlopen(request, timeout):
        del timeout
        captured.append(request)
        return FakeResponse({"counts": {"test_current_state": 1}})

    monkeypatch.setattr(control.urllib.request, "urlopen", fake_urlopen)
    control.get_store().save_current_state(
        {
            "latest_run_id": "run-1",
            "updated_at": "2026-08-26T12:00:00Z",
            "replace_current_state": True,
            "tests": {
                "pytest::one": {
                    "suite": "pytest",
                    "test": "one",
                    "status": "passed",
                    "run_id": "run-1",
                }
            },
        },
        [
            {
                "event_id": "event-1",
                "event": "passed",
                "status": "passed",
                "run_id": "run-1",
                "key": "pytest::one",
                "suite": "pytest",
                "test": "one",
                "timestamp": "2026-08-26T12:00:00Z",
            }
        ],
    )

    assert len(captured) == 1
    assert captured[0].full_url.endswith("/v1/import")
    payload = json.loads(captured[0].data)
    assert payload["replace_current_state"] is True
    assert payload["collections"]["test_current_state"][0]["test_key"] == "pytest::one"
    assert payload["collections"]["test_results"][0]["result_key"] == "event-1"


def test_api_store_uses_private_dispatch_routes(monkeypatch) -> None:
    control = load_tests_control()
    monkeypatch.setenv("ENGINEERING_CONTROL_PLANE_API_TOKEN", "private-token")
    captured = []

    def fake_urlopen(request, timeout):
        del timeout
        captured.append(request)
        if request.full_url.endswith("/v1/coordination/dispatches"):
            return FakeResponse({"dispatch": {"dispatch_key": "dispatch-1", "status": "queued"}, "reused": False})
        if request.full_url.endswith("/canaries"):
            return FakeResponse({"dispatch": {"dispatch_key": "dispatch-1", "status": "queued"}})
        return FakeResponse({"dispatch": {"dispatch_key": "dispatch-1", "status": "running"}})

    monkeypatch.setattr(control.urllib.request, "urlopen", fake_urlopen)
    store = control.get_store()
    dispatch, reused = store.request_dispatch(
        commit="abc123",
        tests=["pytest::one"],
        profile="pytest",
        required_services=["dev-stack"],
    )
    store.record_dispatch_canary(dispatch["dispatch_key"], "dev-stack", healthy=True)
    store.update_dispatch(dispatch["dispatch_key"], "running")

    assert reused is False
    assert [request.method for request in captured] == ["POST", "PUT", "PATCH"]
    assert all("8055" not in request.full_url for request in captured)
