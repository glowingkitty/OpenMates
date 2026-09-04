#!/usr/bin/env python3
"""Resource-path contracts that preserve safe parallel test execution."""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_isolated_and_live_suites_claim_only_real_runtime_resources() -> None:
    tests = load_module("resource_path_tests", ROOT / "scripts/tests.py")

    for suite in ("vitest", "pytest", "apple"):
        assert tests.docker_resources_for_run(["--suite", suite]) == set()
    for args in (
        ["--suite", "playwright"],
        ["--suite", "cli"],
        ["--spec", "chat-flow.spec.ts"],
        ["--hourly-dev"],
    ):
        assert tests.docker_resources_for_run(args) == {tests.session_control.DOCKER_RESOURCE_DEV_STACK}


def test_apple_remote_remains_one_low_memory_lane() -> None:
    source = (ROOT / "scripts/apple_remote.py").read_text()

    assert 'SIMULATOR_LOCK_PATH = "/tmp/openmates-apple-xcode.lock"' in source
    assert "fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)" in source
    assert "8 GB RAM" in source


def test_dispatch_identity_deduplicates_equivalent_work_but_not_other_accounts() -> None:
    coordination = load_module(
        "resource_path_coordination", ROOT / "backend/engineering_control_plane/coordination.py"
    )
    store = coordination.InMemoryCoordinationStore()
    now = datetime.now(timezone.utc)
    common = dict(
        repository="OpenMates",
        commit="abc123",
        tests=["chat-flow.spec.ts"],
        profile="playwright",
        mocks={},
        required_services=["dev-stack"],
        runtime_epoch=4,
    )
    first_spec = coordination.DispatchSpec.create(account="testacct1", **common)
    other_account_spec = coordination.DispatchSpec.create(account="testacct2", **common)

    first, reused_first = store.request_dispatch(first_spec, requested_by="one", now=now)
    repeated, reused_repeated = store.request_dispatch(first_spec, requested_by="two", now=now)
    other, reused_other = store.request_dispatch(other_account_spec, requested_by="three", now=now)

    assert reused_first is False
    assert reused_repeated is True
    assert repeated.dispatch_key == first.dispatch_key
    assert reused_other is False
    assert other.dispatch_key != first.dispatch_key


def test_health_investigator_uses_restart_stable_persistent_lease(monkeypatch) -> None:
    sessions = load_module("resource_path_sessions_claim", ROOT / "scripts/sessions.py")
    calls: list[tuple[str, str, dict | None]] = []
    monkeypatch.setattr(sessions, "_persistent_coordination_enabled", lambda: True)
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"abcd": {}}})
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback({"sessions": {"abcd": {}}}))

    def request(method: str, path: str, *, data=None):
        calls.append((method, path, data))
        return {"lease": {"acquired_at": "2026-08-27T00:00:00Z"}}

    monkeypatch.setattr(sessions, "control_plane_api_request", request)
    result = sessions._claim_api_health_incident(
        "abcd", "https://api.dev.openmates.org/health", {"status_code": 502, "error": "bad gateway"}
    )

    assert result["owned"] is True
    payload = calls[0][2]
    assert payload["owner_key"] == "health-session:abcd"
    assert payload["resources"] == [f"api-health:{sessions._health_url_key(result['incident']['url'])}"]
    assert payload["mode"] == "exclusive"


def test_health_recovery_releases_owner_and_publishes_typed_event(monkeypatch) -> None:
    sessions = load_module("resource_path_sessions_ready", ROOT / "scripts/sessions.py")
    calls: list[tuple[str, str, dict | None]] = []
    monkeypatch.setattr(sessions, "_persistent_coordination_enabled", lambda: True)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback({"infrastructure": {}}))

    def request(method: str, path: str, *, data=None):
        calls.append((method, path, data))
        return {"released": True} if method == "DELETE" else {"event": {"cursor": 1}}

    monkeypatch.setattr(sessions, "control_plane_api_request", request)
    url = "https://api.dev.openmates.org/health"
    sessions._clear_api_health_incident(url)

    assert calls[0][:2] == ("DELETE", f"/v1/coordination/leases/{sessions._health_lease_key(url)}")
    event = calls[1][2]
    assert event["payload"]["signal"] == "OPENMATES_HEALTH_READY"
    assert event["payload"]["operation_type"] == "health_ready"
    assert event["target_type"] == "runtime_operation"
