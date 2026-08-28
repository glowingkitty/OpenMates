#!/usr/bin/env python3
"""Docker restart orchestration contracts for sessions.py.

The tests keep all state in a temporary sessions file and replace Docker calls.
They verify restart/test exclusion, operation history, and health-gated success.
Run: python3 -m pytest scripts/tests/test_sessions_docker_orchestration.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import sessions

# contract-test-file: tooling


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def use_local_coordination(monkeypatch):
    monkeypatch.setenv("OPENMATES_COORDINATION_BACKEND", "local")


def load_run_tests_module():
    spec = importlib.util.spec_from_file_location("docker_orchestration_run_tests", PROJECT_ROOT / "scripts" / "run_tests.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def configure_state(monkeypatch, tmp_path):
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps(sessions._default_sessions()), encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("OPENMATES_DEPLOYMENT_MODE=self_host\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "ENV_FILE", env_file)
    return sessions_file


def configure_runtime_checkout(monkeypatch, checkout_root: Path) -> None:
    monkeypatch.setattr(sessions, "_docker_checkout_root", lambda _session_id: checkout_root)
    monkeypatch.setattr(sessions, "_ensure_product_runtime_checkout", lambda *, refresh: checkout_root)
    monkeypatch.setattr(sessions, "_current_git_sha", lambda _root: "a" * 40)
    monkeypatch.setattr(
        sessions,
        "_coherent_docker_services",
        lambda requested, _root, _commit: sorted(requested),
    )
    monkeypatch.setattr(sessions, "_incoherent_docker_services", lambda _root, _tree: set())
    monkeypatch.setattr(sessions, "_record_product_runtime_services", lambda *_args: None)
    monkeypatch.setattr(
        sessions,
        "_run_cmd",
        lambda command, **_kwargs: (0, "backend-tree\n", "")
        if command[:3] == ["git", "rev-parse", "HEAD:backend"]
        else (0, "", ""),
    )


def test_restart_request_blocks_new_dependent_tests(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)

    operation = sessions.request_docker_restart("a111", ["api", "task-worker"])

    assert operation["status"] == "queued"
    with pytest.raises(RuntimeError, match="Docker restart .* is queued"):
        sessions.acquire_test_resource_lease("run-1", "test-session", {"dev-stack"}, timeout=0)


def test_restart_requests_queue_and_same_session_reattaches(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)

    first = sessions.request_docker_restart("a111", ["api"])
    repeated = sessions.request_docker_restart("a111", ["api"])
    second = sessions.request_docker_restart("b222", ["api"])

    assert repeated["id"] == first["id"]
    assert second["id"] != first["id"]
    assert second["status"] == "queued"
    assert sessions._active_docker_operation(sessions._load_sessions())["id"] == first["id"]


def test_persistent_blocking_leases_reclaims_dead_same_host_owner(monkeypatch):
    monkeypatch.setattr(sessions, "_persistent_coordination_enabled", lambda: True)
    monkeypatch.setattr(sessions, "_process_is_alive", lambda _pid: False)
    host = sessions.socket.gethostname()
    calls = []

    def api_request(method, path, *, data=None):
        calls.append((method, path, data))
        if method == "GET":
            if any(call[0] == "DELETE" for call in calls):
                return {"leases": []}
            return {
                "leases": [
                    {
                        "lease_key": "test-dead",
                        "owner_key": f"{host}:999999",
                        "resources": ["dev-stack"],
                        "status": "active",
                        "acquired_at": "2026-08-27T00:00:00Z",
                        "expires_at": "2026-08-27T00:30:00Z",
                    }
                ]
            }
        if method == "DELETE":
            return {"released": True}
        raise AssertionError((method, path, data))

    monkeypatch.setattr(sessions, "control_plane_api_request", api_request)

    assert sessions._blocking_test_resource_leases("docker-1") == []
    assert ("DELETE", "/v1/coordination/leases/test-dead", None) in calls


def test_persistent_acquire_reclaims_dead_same_host_conflict_and_preserves_mode(monkeypatch):
    monkeypatch.setattr(sessions, "_persistent_coordination_enabled", lambda: True)
    monkeypatch.setattr(sessions, "_process_is_alive", lambda _pid: False)
    host = sessions.socket.gethostname()
    calls = []
    attempts = 0

    def api_request(method, path, *, data=None):
        nonlocal attempts
        calls.append((method, path, data))
        if method == "POST":
            attempts += 1
            if attempts == 1:
                raise sessions.ControlPlaneApiError(
                    409,
                    "requested resources are already leased: stale-lease",
                )
            return {
                "lease": {
                    "lease_key": "new-lease",
                    "owner_key": f"{host}:1234",
                    "resources": ["dev-stack"],
                    "status": "active",
                    "mode": "shared",
                }
            }
        if method == "GET":
            return {
                "lease": {
                    "lease_key": "stale-lease",
                    "owner_key": f"{host}:999999",
                    "resources": ["dev-stack"],
                    "status": "active",
                }
            }
        if method == "DELETE":
            return {"released": True}
        raise AssertionError((method, path, data))

    monkeypatch.setattr(sessions, "control_plane_api_request", api_request)

    lease = sessions.acquire_test_resource_lease(
        "new-lease",
        "tests",
        {"dev-stack"},
        timeout=0,
        mode="shared",
    )

    assert lease["lease_id"] == "new-lease"
    assert calls[-1][2]["mode"] == "shared"
    assert calls[-1][2]["ttl_seconds"] == 30 * 60
    assert ("DELETE", "/v1/coordination/leases/stale-lease", None) in calls


def test_persistent_acquire_reports_its_blocker_while_waiting(monkeypatch, capsys):
    monkeypatch.setattr(sessions, "_persistent_coordination_enabled", lambda: True)
    monkeypatch.setattr(
        sessions,
        "control_plane_api_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            sessions.ControlPlaneApiError(409, "runtime operation owns requested resources: docker-first")
        ),
    )
    timestamps = iter([100.0, 100.0, 100.0, 100.0, 102.0])
    monkeypatch.setattr(sessions.time, "time", lambda: next(timestamps))
    monkeypatch.setattr(sessions.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="docker-first"):
        sessions.acquire_test_resource_lease("new-lease", "tests", {"dev-stack"}, timeout=1)

    assert "Waiting for test resource admission" in capsys.readouterr().err


def test_local_shared_test_leases_can_coexist(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)

    sessions.acquire_test_resource_lease("reader-a", "a", {"dev-stack"}, timeout=0, mode="shared")
    sessions.acquire_test_resource_lease("reader-b", "b", {"dev-stack"}, timeout=0, mode="shared")

    with pytest.raises(RuntimeError):
        sessions.acquire_test_resource_lease("writer", "c", {"dev-stack"}, timeout=0, mode="exclusive")


def test_persistent_operation_blockers_include_operation_owner_and_phase(monkeypatch):
    monkeypatch.setattr(sessions, "_persistent_coordination_enabled", lambda: True)
    monkeypatch.setattr(sessions, "_process_is_alive", lambda _pid: True)
    monkeypatch.setattr(
        sessions,
        "control_plane_api_request",
        lambda *_args, **_kwargs: {
            "leases": [],
            "operations": [
                {
                    "operation_key": "docker-first",
                    "status": "restarting",
                    "resources": ["dev-stack"],
                    "requested_at": "2026-08-27T00:00:00Z",
                    "metadata": {"session_id": "abcd", "services": ["api"]},
                }
            ],
        },
    )

    blockers = sessions._runtime_operation_blockers("docker-second")

    assert blockers["leases"] == []
    assert blockers["operations"][0]["id"] == "docker-first"
    assert blockers["operations"][0]["session_id"] == "abcd"
    assert blockers["operations"][0]["status"] == "restarting"


def test_official_cloud_docker_command_includes_overlay(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENMATES_DEPLOYMENT_MODE=official_cloud\n"
        "OPENMATES_CLOUD_OVERLAY_ENABLED=true\n"
        "OPENMATES_CLOUD_OVERLAY_PACKAGE=OpenMatesCloud\n"
        f"OPENMATES_CLOUD_OVERLAY_PATH={tmp_path}\n",
        encoding="utf-8",
    )
    overlay_file = tmp_path / "docker-compose.openmatescloud.yml"
    overlay_file.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "ENV_FILE", env_file)

    command = sessions._docker_compose_command("restart", "api")

    assert command[-4:] == ["-f", str(overlay_file), "restart", "api"]


def test_docker_command_uses_session_worktree_compose_files(monkeypatch, tmp_path):
    checkout_root = tmp_path / "agent-abcd"
    compose_file = checkout_root / "backend" / "core" / "docker-compose.yml"
    override_file = checkout_root / "backend" / "core" / "docker-compose.override.yml"
    compose_file.parent.mkdir(parents=True)
    compose_file.write_text("services: {}\n", encoding="utf-8")
    override_file.write_text("services: {}\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("OPENMATES_DEPLOYMENT_MODE=self_host\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "ENV_FILE", env_file)

    command = sessions._docker_compose_command("config", "--services", checkout_root=checkout_root)

    assert command == [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(compose_file),
        "-f",
        str(override_file),
        "config",
        "--services",
    ]


def test_runtime_coherence_expands_restart_for_mixed_mounts_and_generations(monkeypatch, tmp_path):
    checkout_root = tmp_path / "runtime"
    (checkout_root / "backend").mkdir(parents=True)
    monkeypatch.setattr(
        sessions,
        "_running_backend_mounts",
        lambda _root: {
            "api": {"source": str(checkout_root / "backend"), "container_id": "api-current"},
            "core-worker": {"source": "/old/session/backend", "container_id": "worker-old"},
            "workflow-worker": {"source": str(checkout_root / "backend"), "container_id": "workflow-new"},
        },
    )
    monkeypatch.setattr(
        sessions,
        "_load_product_runtime_state",
        lambda: {
            "services": {
                "api": {"backend_tree": "new", "container_id": "api-current"},
                "core-worker": {"backend_tree": "old", "container_id": "worker-old"},
                "workflow-worker": {"backend_tree": "old", "container_id": "workflow-new"},
            }
        },
    )

    services = sessions._coherent_docker_services(["api"], checkout_root, "new")

    assert services == ["api", "core-worker", "workflow-worker"]


def test_runtime_coherence_keeps_matching_services_parallel_and_scoped(monkeypatch, tmp_path):
    checkout_root = tmp_path / "runtime"
    (checkout_root / "backend").mkdir(parents=True)
    monkeypatch.setattr(
        sessions,
        "_running_backend_mounts",
        lambda _root: {
            "api": {"source": str(checkout_root / "backend"), "container_id": "api-current"},
            "core-worker": {"source": str(checkout_root / "backend"), "container_id": "worker-current"},
        },
    )
    monkeypatch.setattr(
        sessions,
        "_load_product_runtime_state",
        lambda: {
            "services": {
                "api": {"backend_tree": "new", "container_id": "api-current"},
                "core-worker": {"backend_tree": "new", "container_id": "worker-current"},
            }
        },
    )

    assert sessions._coherent_docker_services(["api"], checkout_root, "new") == ["api"]


def test_runtime_coherence_restores_previously_managed_stopped_service(monkeypatch, tmp_path):
    checkout_root = tmp_path / "runtime"
    (checkout_root / "backend").mkdir(parents=True)
    monkeypatch.setattr(
        sessions,
        "_running_backend_mounts",
        lambda _root: {
            "api": {"source": str(checkout_root / "backend"), "container_id": "api-current"},
        },
    )
    monkeypatch.setattr(
        sessions,
        "_load_product_runtime_state",
        lambda: {
            "services": {
                "api": {"backend_tree": "new", "container_id": "api-current"},
                "core-worker": {"backend_tree": "new", "container_id": "worker-stopped"},
            }
        },
    )

    assert sessions._coherent_docker_services(["api"], checkout_root, "new") == ["api", "core-worker"]


def test_runtime_provenance_rejects_healthy_container_on_wrong_mount(monkeypatch, tmp_path):
    checkout_root = tmp_path / "runtime"
    (checkout_root / "backend").mkdir(parents=True)
    monkeypatch.setattr(
        sessions,
        "_running_backend_mounts",
        lambda _root: {"api": {"source": "/old/session/backend", "container_id": "api-old"}},
    )

    with pytest.raises(RuntimeError, match="mount coherence failed for: api"):
        sessions._record_product_runtime_services(["api"], checkout_root, "commit", "tree")


@pytest.mark.parametrize(
    ("build", "expected_compose_args"),
    [
        (False, ["up", "-d", "--no-deps", "--force-recreate", "api"]),
        (True, ["up", "-d", "--no-deps", "--build", "api"]),
    ],
)
def test_restart_command_routes_all_compose_operations_through_shared_runtime(
    monkeypatch, tmp_path, build, expected_compose_args
):
    checkout_root = tmp_path / "agent-abcd"
    checkout_root.mkdir()
    monkeypatch.setattr(
        sessions,
        "_load_sessions",
        lambda: {"sessions": {"abcd": {"worktree": {"path": str(checkout_root), "status": "active"}}}},
    )
    configure_runtime_checkout(monkeypatch, checkout_root)
    monkeypatch.setattr(sessions, "_incoherent_docker_services", lambda _root, _tree: {"api"})
    roots = []
    monkeypatch.setattr(sessions, "available_docker_services", lambda root: roots.append(("available", root)) or {"api"})
    monkeypatch.setattr(sessions, "request_docker_restart", lambda *_args: {"id": "op-1"})
    monkeypatch.setattr(sessions, "_wait_and_acquire_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "wait_for_docker_test_leases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sessions, "_acquire_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_release_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "update_docker_operation", lambda operation_id, status, **kwargs: {"id": operation_id, "status": status, **kwargs})
    monkeypatch.setattr(sessions, "_docker_compose_command", lambda *args, checkout_root: [str(checkout_root), *args])
    monkeypatch.setattr(
        sessions,
        "_run_cmd_with_heartbeat",
        lambda command, *, cwd, **_kwargs: roots.append(("restart", Path(cwd), command)) or (0, "", ""),
    )
    monkeypatch.setattr(
        sessions,
        "wait_for_docker_services_healthy",
        lambda _services, *, checkout_root, **_kwargs: roots.append(("health", checkout_root)) or {"api": {"running": True}},
    )
    args = argparse.Namespace(session="abcd", service=["api"], timeout=1, poll=1, health_timeout=1, build=build)

    sessions.cmd_docker_restart(args)

    assert roots == [
        ("available", checkout_root),
        ("restart", checkout_root, [str(checkout_root), *expected_compose_args]),
        ("health", checkout_root),
    ]


def test_setup_command_runs_one_shot_service_through_shared_runtime(monkeypatch, tmp_path):
    checkout_root = tmp_path / "agent-abcd"
    checkout_root.mkdir()
    configure_runtime_checkout(monkeypatch, checkout_root)
    events = []
    monkeypatch.setattr(
        sessions,
        "available_docker_setup_services",
        lambda root: events.append(("available", root)) or {"cms-setup", "vault-setup"},
    )
    monkeypatch.setattr(
        sessions,
        "request_docker_restart",
        lambda _session, services: events.append(("request", tuple(services))) or {"id": "op-1"},
    )
    monkeypatch.setattr(sessions, "_wait_and_acquire_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "wait_for_docker_test_leases", lambda *_args, **_kwargs: events.append(("drain", "tests")) or [])
    monkeypatch.setattr(sessions, "_acquire_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_release_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        sessions,
        "update_docker_operation",
        lambda operation_id, status, **kwargs: events.append(("status", status, kwargs)) or {"id": operation_id, "status": status, **kwargs},
    )
    monkeypatch.setattr(sessions, "_docker_compose_command", lambda *args, checkout_root: [str(checkout_root), *args])
    monkeypatch.setattr(
        sessions,
        "_run_cmd_with_heartbeat",
        lambda command, *, cwd, **_kwargs: events.append(("run", Path(cwd), command)) or (0, "", ""),
    )
    args = argparse.Namespace(session="abcd", service=["cms-setup"], timeout=1, poll=1, build=True)

    sessions.cmd_docker_run_setup(args)

    assert ("available", checkout_root) in events
    assert ("request", ("cms-setup",)) in events
    assert ("drain", "tests") in events
    assert ("run", checkout_root, [str(checkout_root), "run", "--rm", "--build", "cms-setup"]) in events
    assert any(event[0] == "status" and event[1] == "completed" for event in events)


def test_persistent_restart_waits_for_runtime_operation_admission(monkeypatch, tmp_path):
    checkout_root = tmp_path / "agent-abcd"
    checkout_root.mkdir()
    configure_runtime_checkout(monkeypatch, checkout_root)
    monkeypatch.setattr(sessions, "_persistent_coordination_enabled", lambda: True)
    monkeypatch.setattr(sessions, "available_docker_services", lambda _root: {"api"})
    monkeypatch.setattr(sessions, "request_docker_restart", lambda *_args: {"id": "op-1", "status": "queued"})
    admission_statuses = iter(["queued", "queued", "admitted"])
    events = []

    def update_operation(operation_id, status, **kwargs):
        if status == "queued":
            status = next(admission_statuses)
        events.append(("update", status))
        return {"id": operation_id, "status": status, **kwargs}

    monkeypatch.setattr(sessions, "update_docker_operation", update_operation)
    monkeypatch.setattr(sessions, "_runtime_operation_blockers", lambda _operation_id: {"leases": [], "operations": []})
    monkeypatch.setattr(sessions.time, "sleep", lambda _seconds: events.append(("sleep", "admission")))
    monkeypatch.setattr(
        sessions,
        "_wait_and_acquire_session_lock",
        lambda *_args, **_kwargs: pytest.fail("persistent Docker restarts must not use the legacy lock"),
    )
    monkeypatch.setattr(sessions, "wait_for_docker_test_leases", lambda *_args, **_kwargs: events.append(("drain", "tests")) or [])
    monkeypatch.setattr(
        sessions,
        "_acquire_session_lock",
        lambda *_args, **_kwargs: pytest.fail("persistent Docker restarts must not acquire the legacy lock"),
    )
    monkeypatch.setattr(
        sessions,
        "_release_session_lock",
        lambda *_args, **_kwargs: pytest.fail("persistent Docker restarts must not release the legacy lock"),
    )
    monkeypatch.setattr(sessions, "_docker_compose_command", lambda *args, checkout_root: [str(checkout_root), *args])
    monkeypatch.setattr(
        sessions,
        "_run_cmd_with_heartbeat",
        lambda *_args, **_kwargs: events.append(("compose", "restart")) or (0, "", ""),
    )
    monkeypatch.setattr(
        sessions,
        "wait_for_docker_services_healthy",
        lambda *_services, **_kwargs: events.append(("health", "verify")) or {"api": {"running": True}},
    )
    args = argparse.Namespace(session="abcd", service=["api"], timeout=10, poll=1, health_timeout=1, build=True)

    sessions.cmd_docker_restart(args)

    assert events[:4] == [
        ("update", "queued"),
        ("update", "queued"),
        ("sleep", "admission"),
        ("update", "admitted"),
    ]
    assert events.index(("drain", "tests")) > events.index(("update", "admitted"))
    assert events.index(("compose", "restart")) > events.index(("drain", "tests"))


def test_docker_checkout_root_rejects_unknown_session(monkeypatch) -> None:
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {}})

    with pytest.raises(RuntimeError, match="session not found"):
        sessions._docker_checkout_root("missing")


def test_restart_stops_if_runtime_checkout_cannot_refresh(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sessions, "_docker_checkout_root", lambda _session_id: tmp_path)
    monkeypatch.setattr(
        sessions,
        "_ensure_product_runtime_checkout",
        lambda *, refresh: (_ for _ in ()).throw(RuntimeError("product runtime checkout refresh failed")),
    )
    monkeypatch.setattr(sessions, "available_docker_services", lambda _root: {"api"})
    monkeypatch.setattr(sessions, "request_docker_restart", lambda *_args: {"id": "op-1"})
    monkeypatch.setattr(sessions, "_wait_and_acquire_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "wait_for_docker_test_leases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sessions, "_acquire_session_lock", lambda *_args, **_kwargs: True)
    released = []
    monkeypatch.setattr(sessions, "_release_session_lock", lambda *_args, **kwargs: released.append(kwargs["released_by"]) or True)
    monkeypatch.setattr(sessions, "update_docker_operation", lambda operation_id, status, **kwargs: {"id": operation_id, "status": status, **kwargs})
    compose_calls = []
    monkeypatch.setattr(sessions, "_run_cmd_with_heartbeat", lambda *_args, **_kwargs: compose_calls.append(True))
    args = argparse.Namespace(session="abcd", service=["api"], timeout=1, poll=1, health_timeout=1, build=True)

    with pytest.raises(RuntimeError, match="runtime checkout refresh failed"):
        sessions.cmd_docker_restart(args)

    assert compose_calls == []
    assert released == ["abcd"]


def test_official_cloud_docker_command_fails_closed_without_overlay(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENMATES_DEPLOYMENT_MODE=official_cloud\n"
        "OPENMATES_CLOUD_OVERLAY_ENABLED=false\n"
        "OPENMATES_CLOUD_OVERLAY_PACKAGE=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "ENV_FILE", env_file)

    with pytest.raises(RuntimeError, match="official-cloud Docker restart requires"):
        sessions._docker_compose_command("restart", "api")


def test_official_cloud_docker_command_fails_closed_without_compose_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENMATES_DEPLOYMENT_MODE=official_cloud\n"
        "OPENMATES_CLOUD_OVERLAY_ENABLED=true\n"
        "OPENMATES_CLOUD_OVERLAY_PACKAGE=OpenMatesCloud\n"
        f"OPENMATES_CLOUD_OVERLAY_PATH={tmp_path}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "ENV_FILE", env_file)

    with pytest.raises(RuntimeError, match="official-cloud Docker restart requires"):
        sessions._docker_compose_command("restart", "api")


def test_direct_dev_runner_does_not_hold_a_suite_wide_docker_resource_lease(monkeypatch):
    run_tests = load_run_tests_module()
    args = SimpleNamespace(
        environment="development",
        hourly_prod=False,
        prod_free_hourly=False,
        prod_paid_chat=False,
        prod_app_skill=False,
        dry_run=False,
    )
    acquired = []
    released = []
    monkeypatch.delenv("OPENMATES_DOCKER_TEST_LEASE_HELD", raising=False)
    monkeypatch.setattr(
        run_tests.session_control,
        "acquire_test_resource_lease",
        lambda lease_id, owner, resources: acquired.append((lease_id, owner, resources)),
    )
    monkeypatch.setattr(
        run_tests.session_control,
        "release_test_resource_lease",
        lambda lease_id: released.append(lease_id),
    )

    assert run_tests._run_with_dev_stack_lease(args, lambda: 7) == 7
    assert acquired == []
    assert released == []


def test_restart_waits_for_existing_dependent_test(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)
    sessions.acquire_test_resource_lease("run-1", "test-session", {"dev-stack"}, timeout=0)
    operation = sessions.request_docker_restart("a111", ["api"])

    with pytest.raises(RuntimeError, match="run-1"):
        sessions.wait_for_docker_test_leases(operation["id"], timeout=0, poll=1)

    sessions.release_test_resource_lease("run-1")
    assert sessions.wait_for_docker_test_leases(operation["id"], timeout=0, poll=1) == []


def test_test_lease_transfer_requires_current_owner_and_updates_child_pid(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)
    parent_pid = sessions.os.getpid()
    sessions.acquire_test_resource_lease("run-1", "test-session", {"dev-stack"}, timeout=0)

    transferred = sessions.transfer_test_resource_lease(
        "run-1",
        expected_owner_pid=parent_pid,
        new_owner_pid=4321,
    )

    assert transferred["owner_pid"] == 4321
    assert sessions.test_resource_lease_owned_by("run-1", owner_pid=4321) is True
    assert sessions.test_resource_lease_owned_by("run-1", owner_pid=parent_pid) is False
    with pytest.raises(RuntimeError, match="not owned by the launching process"):
        sessions.transfer_test_resource_lease(
            "run-1",
            expected_owner_pid=parent_pid,
            new_owner_pid=9999,
        )


def test_completed_restart_is_retained_with_health_evidence(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)
    operation = sessions.request_docker_restart("a111", ["api"])

    completed = sessions.update_docker_operation(
        operation["id"],
        "completed",
        health={"api": {"running": True, "health": "healthy"}},
    )
    state = sessions._load_sessions()

    assert completed["completed_at"]
    assert state["infrastructure"]["docker_operations"][-1]["health"]["api"]["health"] == "healthy"


def test_abandoned_restart_is_failed_before_new_test_lease(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)
    operation = sessions.request_docker_restart("a111", ["api"])
    monkeypatch.setattr(sessions, "_process_is_alive", lambda _pid: False)

    lease = sessions.acquire_test_resource_lease("run-1", "tests", {"dev-stack"}, timeout=0)
    recorded = sessions._load_sessions()["infrastructure"]["docker_operations"][-1]

    assert lease["lease_id"] == "run-1"
    assert recorded["id"] == operation["id"]
    assert recorded["status"] == "failed"
    assert "process ended" in recorded["error"]


def test_dead_local_persistent_restart_blocker_is_failed(monkeypatch):
    calls = []
    monkeypatch.setattr(sessions.socket, "gethostname", lambda: "dev-server")
    monkeypatch.setattr(sessions, "_process_is_alive", lambda _pid: False)
    monkeypatch.setattr(
        sessions,
        "update_docker_operation",
        lambda operation_id, status, **fields: calls.append((operation_id, status, fields)) or {},
    )

    failed = sessions._fail_dead_local_persistent_operation_blockers([
        {
            "id": "docker-orphan",
            "status": "admitted",
            "owner_pid": 1234,
            "owner_host": "dev-server",
        },
        {
            "id": "docker-remote",
            "status": "admitted",
            "owner_pid": 5678,
            "owner_host": "other-host",
        },
    ])

    assert failed == ["docker-orphan"]
    assert calls == [(
        "docker-orphan",
        "failed",
        {
            "failure_class": "owner-exited",
            "error": "Restart owner process ended before completion",
        },
    )]


def test_stale_session_save_preserves_new_infrastructure_state(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)
    stale = sessions._load_sessions()
    operation = sessions.request_docker_restart("a111", ["api"])

    stale.setdefault("sessions", {})["b222"] = {"task": "stale writer"}
    sessions._save_sessions(stale)
    saved = sessions._load_sessions()

    assert saved["infrastructure"]["docker_operations"][-1]["id"] == operation["id"]


def test_lock_release_requires_current_owner(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)
    sessions._acquire_session_lock("docker_rebuild", "owner")

    assert sessions._release_session_lock("docker_rebuild", released_by="other") is False
    assert sessions._load_sessions()["locks"]["docker_rebuild"]["claimed_by"] == "owner"


def test_restart_command_records_failure_and_releases_lock(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)
    configure_runtime_checkout(monkeypatch, tmp_path)
    monkeypatch.setattr(sessions, "available_docker_services", lambda _checkout_root: {"api"})
    monkeypatch.setattr(sessions, "wait_for_docker_test_leases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sessions, "_wait_and_acquire_session_lock", lambda *_args, **_kwargs: True)
    released = []
    monkeypatch.setattr(sessions, "_release_session_lock", lambda *_args, **kwargs: released.append(kwargs["released_by"]) or True)
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (1, "", "restart failed"))
    args = argparse.Namespace(session="a111", service=["api"], timeout=1, poll=1, health_timeout=1)

    with pytest.raises(RuntimeError, match="restart failed"):
        sessions.cmd_docker_restart(args)

    operation = sessions._load_sessions()["infrastructure"]["docker_operations"][-1]
    assert operation["status"] == "failed"
    assert released == ["a111"]


def test_restart_command_records_keyboard_interrupt(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)
    configure_runtime_checkout(monkeypatch, tmp_path)
    monkeypatch.setattr(sessions, "available_docker_services", lambda _checkout_root: {"api"})
    monkeypatch.setattr(sessions, "wait_for_docker_test_leases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sessions, "_wait_and_acquire_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_release_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
    args = argparse.Namespace(session="a111", service=["api"], timeout=1, poll=1, health_timeout=1)

    with pytest.raises(KeyboardInterrupt):
        sessions.cmd_docker_restart(args)

    operation = sessions._load_sessions()["infrastructure"]["docker_operations"][-1]
    assert operation["status"] == "failed"
    assert operation["error"] == "KeyboardInterrupt"


def test_long_docker_command_heartbeats_lock(monkeypatch):
    beats = []
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (time.sleep(0.04) or (0, "ok", "")))

    result = sessions._run_cmd_with_heartbeat(
        ["docker", "compose", "up"],
        cwd="/tmp",
        timeout=10,
        heartbeat=lambda: beats.append("beat"),
        interval=0.01,
    )

    assert result == (0, "ok", "")
    assert beats


def test_waiting_for_docker_lock_heartbeats_queued_operation(monkeypatch):
    beats = []
    attempts = 0

    def acquire(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("held")
        return True

    monkeypatch.setattr(sessions, "_acquire_session_lock", acquire)
    monkeypatch.setattr(sessions, "_active_lock_snapshot", lambda *_args: {})
    monkeypatch.setattr(sessions.time, "time", iter([0, 1]).__next__)
    monkeypatch.setattr(sessions.time, "sleep", lambda *_args: None)

    assert sessions._wait_and_acquire_session_lock(
        "docker_rebuild",
        "a111",
        timeout=10,
        poll=1,
        heartbeat=lambda: beats.append("beat"),
    ) is True
    assert beats == ["beat"]


def test_api_health_incident_has_single_live_investigator(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)
    probe = {"ok": False, "status_code": 502, "error": "Bad Gateway"}

    first = sessions._claim_api_health_incident("a111", "https://api.dev.openmates.org/health", probe)
    second = sessions._claim_api_health_incident("b222", "https://api.dev.openmates.org/health", probe)

    assert first["owned"] is True
    assert second["owned"] is False
    assert second["incident"]["owner_session_id"] == "a111"

    monkeypatch.setattr(sessions, "_minutes_since", lambda _value: 6)
    takeover = sessions._claim_api_health_incident("b222", "https://api.dev.openmates.org/health", probe)

    assert takeover["owned"] is True
    assert takeover["incident"]["owner_session_id"] == "b222"


def test_wait_health_returns_ready_signal(monkeypatch, tmp_path, capsys):
    configure_state(monkeypatch, tmp_path)
    monkeypatch.setattr(sessions, "_probe_health_url", lambda _url, *, timeout: {"ok": True, "status_code": 200, "error": ""})
    monkeypatch.setattr(sessions, "_active_lock_snapshot", lambda _lock_type: {})

    sessions.cmd_wait_health(
        argparse.Namespace(
            url="https://api.dev.openmates.org/health",
            session="a111",
            follow=False,
            timeout=0,
            poll=1,
            probe_timeout=1,
        )
    )

    assert "OPENMATES_HEALTH_READY" in capsys.readouterr().out


def test_wait_health_elects_investigator_when_no_runtime_owner(monkeypatch, tmp_path, capsys):
    configure_state(monkeypatch, tmp_path)
    monkeypatch.setattr(sessions, "_probe_health_url", lambda _url, *, timeout: {"ok": False, "status_code": 502, "error": "Bad Gateway"})
    monkeypatch.setattr(sessions, "_active_lock_snapshot", lambda _lock_type: {})

    sessions.cmd_wait_health(
        argparse.Namespace(
            url="https://api.dev.openmates.org/health",
            session="a111",
            follow=False,
            timeout=0,
            poll=1,
            probe_timeout=1,
        )
    )

    output = capsys.readouterr().out
    assert "OPENMATES_HEALTH_INVESTIGATE" in output
    assert "single API-health investigator" in output
