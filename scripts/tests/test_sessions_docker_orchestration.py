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


def test_restart_request_blocks_new_dependent_tests(monkeypatch, tmp_path):
    configure_state(monkeypatch, tmp_path)

    operation = sessions.request_docker_restart("a111", ["api", "task-worker"])

    assert operation["status"] == "queued"
    with pytest.raises(RuntimeError, match="Docker restart .* is queued"):
        sessions.acquire_test_resource_lease("run-1", "test-session", {"dev-stack"}, timeout=0)


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


def test_restart_command_routes_all_compose_operations_through_worktree(monkeypatch, tmp_path):
    checkout_root = tmp_path / "agent-abcd"
    checkout_root.mkdir()
    monkeypatch.setattr(
        sessions,
        "_load_sessions",
        lambda: {"sessions": {"abcd": {"worktree": {"path": str(checkout_root), "status": "active"}}}},
    )
    monkeypatch.setattr(sessions, "_validate_managed_worktree_path", lambda path: Path(path))
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
    args = argparse.Namespace(session="abcd", service=["api"], timeout=1, poll=1, health_timeout=1, build=True)

    sessions.cmd_docker_restart(args)

    assert roots == [
        ("available", checkout_root),
        ("restart", checkout_root, [str(checkout_root), "up", "-d", "--build", "api"]),
        ("health", checkout_root),
    ]


def test_docker_checkout_root_rejects_unknown_session(monkeypatch) -> None:
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {}})

    with pytest.raises(RuntimeError, match="session not found"):
        sessions._docker_checkout_root("missing")


def test_restart_stops_if_worktree_disappears_while_waiting(monkeypatch, tmp_path) -> None:
    roots = iter([tmp_path, RuntimeError("Docker restart worktree is missing")])

    def checkout_root(_session_id):
        result = next(roots)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(sessions, "_docker_checkout_root", checkout_root)
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

    with pytest.raises(RuntimeError, match="worktree is missing"):
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


def test_direct_dev_runner_holds_docker_resource_lease(monkeypatch):
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
    assert acquired[0][2] == {"dev-stack"}
    assert released == [acquired[0][0]]


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
    monkeypatch.setattr(sessions, "_docker_checkout_root", lambda _session_id: tmp_path)
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
