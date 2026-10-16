"""Ordering and failure contracts for the dev CMS setup-gated restart."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts import sessions

# contract-test-file: infrastructure


def _harness(monkeypatch, tmp_path):
    checkout = tmp_path / "product-stack"
    checkout.mkdir()
    events = []
    state = {
        "commit": "a" * 40, "running": {"api", "workflow-worker", "app-ai-worker"},
        "failure": None, "cms_checks": 0, "cleanup_failure": False,
    }
    available = {"cms", "api", "workflow-worker", "task-worker", "task-scheduler", "app-ai-worker"}
    backend = available - {"cms"}
    monkeypatch.setattr(sessions, "PRODUCT_RUNTIME_CHECKOUT", checkout)
    monkeypatch.setattr(sessions, "_docker_checkout_root", lambda _session: checkout)
    monkeypatch.setattr(sessions, "available_docker_services", lambda _checkout: available)
    monkeypatch.setattr(sessions, "available_docker_setup_services", lambda _checkout: {"cms-setup"})
    monkeypatch.setattr(sessions, "_configured_backend_mount_services", lambda _checkout: backend)
    monkeypatch.setattr(sessions, "_persistent_coordination_enabled", lambda: True)
    monkeypatch.setattr(sessions, "request_docker_restart", lambda *_args: events.append("request") or {"id": "op"})
    monkeypatch.setattr(sessions, "wait_for_docker_operation_admitted", lambda *_args, **_kwargs: events.append("admitted"))
    monkeypatch.setattr(sessions, "wait_for_docker_test_leases", lambda *_args, **_kwargs: events.append("drained"))
    monkeypatch.setattr(sessions, "update_docker_operation", lambda _id, status, **fields: events.append(("status", status, fields)) or {"id": "op", "status": status})
    monkeypatch.setattr(sessions, "_docker_compose_command", lambda *args, checkout_root: list(args))
    def cms_state(_service, _checkout):
        state["cms_checks"] += 1
        if state["failure"] == "cms_preflight_none":
            return {"running": True, "health": "none"}
        if state["failure"] == "cms_preflight_unhealthy":
            return {"running": True, "health": "unhealthy"}
        if state["failure"] == "cms_after_stop" and state["cms_checks"] >= 2:
            return {"running": False, "health": "unhealthy"}
        if state["failure"] == "cms_before_setup" and state["cms_checks"] >= 3:
            return {"running": False, "health": "unhealthy"}
        if state["failure"] == "cms_postbuild_inspect_none" and state["cms_checks"] >= 4:
            return {"running": True, "health": "none"}
        return {"running": True, "health": "healthy"}

    monkeypatch.setattr(sessions, "_docker_service_state", cms_state)
    monkeypatch.setattr(
        sessions, "_strict_running_backend_consumers",
        lambda _checkout: events.append("snapshot") or set(state["running"]),
    )
    monkeypatch.setattr(sessions.product_runtime_translations, "source_commit", lambda _checkout: state["commit"])

    def run_cmd(command, **_kwargs):
        if command[:3] == ["git", "rev-parse", "origin/dev"]:
            return 0, "b" * 40, ""
        if command[:3] == ["git", "rev-parse", "HEAD:backend"]:
            return 0, "backend-tree", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "_run_cmd", run_cmd)

    def refresh(*, refresh):
        assert refresh is True
        events.append("refresh")
        if state["failure"] == "refresh":
            raise RuntimeError("refresh failed")
        state["commit"] = ("c" if state["failure"] == "source_drift" else "b") * 40
        return checkout

    monkeypatch.setattr(sessions, "_ensure_product_runtime_checkout", refresh)

    def prepare(_checkout, _store):
        events.append("translations")
        if state["failure"] == "translations":
            raise RuntimeError("translation generation failed")
        return tmp_path / "artifact/overlay.json"

    monkeypatch.setattr(sessions.product_runtime_translations, "prepare_artifact", prepare)
    monkeypatch.setattr(sessions, "_translation_mount_mismatches", lambda *_args: set())

    def compose(command, **_kwargs):
        events.append(tuple(command))
        if command[0] == "stop":
            if state["commit"] != "a" * 40:
                assert sessions._PRODUCT_TRANSLATION_SELECTION_ALLOWED.get() is False
            if state["cleanup_failure"] and state["commit"] == "b" * 40:
                return 1, "", "cleanup stop failed"
            if state["failure"] == "initial_stop" and state["commit"] == "a" * 40:
                state["running"].discard("api")
                return 1, "", "stop failed"
            state["running"].difference_update(command[3:])
        elif command[0] == "start":
            state["running"].update(command[1:])
        elif command[:4] == ["run", "--rm", "--no-deps", "--build"] and state["failure"] == "setup":
            return 1, "", "setup failed"
        elif command[:4] == ["up", "-d", "--no-deps", "--build"]:
            if command[-1] != "cms":
                state["running"].update(command[4:])
                if state["failure"] == "consumer_up":
                    return 1, "", "consumer up failed"
        return 0, "", ""

    monkeypatch.setattr(sessions, "_run_cmd_with_heartbeat", compose)

    def healthy(services, **_kwargs):
        events.append(("health", tuple(services)))
        if services == ["cms"] and state["failure"] == "cms_health":
            raise RuntimeError("CMS unhealthy")
        if services == ["cms"] and state["failure"] == "cms_postbuild_none":
            return {"cms": {"running": True, "health": "none"}}
        return {service: {"running": True, "health": "healthy"} for service in services}

    monkeypatch.setattr(sessions, "wait_for_docker_services_healthy", healthy)
    monkeypatch.setattr(sessions, "_record_product_runtime_services", lambda *_args: events.append("recorded"))
    args = argparse.Namespace(
        session="40fc", service=["cms", "api", "workflow-worker", "task-worker", "task-scheduler"],
        setup_service="cms-setup", build=True, timeout=10, poll=1, health_timeout=10,
    )
    return args, events, state


def test_strict_snapshot_inspects_all_live_mounts_and_preserves_cms(monkeypatch, tmp_path):
    checkout = tmp_path / "product-stack"
    (checkout / "backend").mkdir(parents=True)
    monkeypatch.setattr(sessions, "_configured_backend_mount_services", lambda _checkout: {"api", "workflow-worker"})
    monkeypatch.setattr(sessions, "_docker_compose_command", lambda *args, checkout_root: list(args))

    def run(command, **_kwargs):
        if command[:1] == ["ps"] and "--services" in command:
            return 0, "api\ncms\nworkflow-worker\n", ""
        if command[:2] == ["ps", "-q"]:
            return 0, command[-1] + "-id", ""
        if command[:2] == ["docker", "inspect"]:
            service = command[-1].removesuffix("-id")
            mounts = [] if service == "cms" else [{
                "Destination": "/app/backend", "Source": str(checkout / "backend"),
            }]
            return 0, json.dumps(mounts), ""
        raise AssertionError(command)

    monkeypatch.setattr(sessions, "_run_cmd", run)
    assert sessions._strict_running_backend_consumers(checkout) == {"api", "workflow-worker"}


def test_strict_snapshot_rejects_unexpected_live_backend_mount(monkeypatch, tmp_path):
    checkout = tmp_path / "product-stack"
    (checkout / "backend").mkdir(parents=True)
    monkeypatch.setattr(sessions, "_configured_backend_mount_services", lambda _checkout: {"api"})
    monkeypatch.setattr(sessions, "_docker_compose_command", lambda *args, checkout_root: list(args))

    def run(command, **_kwargs):
        if command[:1] == ["ps"] and "--services" in command:
            return 0, "api\n", ""
        if command[:2] == ["ps", "-q"]:
            return 0, "api-id", ""
        if command[:2] == ["docker", "inspect"]:
            return 0, json.dumps([{"Destination": "/app/backend", "Source": "/wrong/backend"}]), ""
        raise AssertionError(command)

    monkeypatch.setattr(sessions, "_run_cmd", run)
    with pytest.raises(RuntimeError, match="Unexpected live backend mount for api"):
        sessions._strict_running_backend_consumers(checkout)


def test_gate_stops_all_prior_consumers_before_refresh_and_starts_after_setup(monkeypatch, tmp_path):
    args, events, state = _harness(monkeypatch, tmp_path)
    sessions.cmd_docker_restart(args)
    stop = next(event for event in events if isinstance(event, tuple) and event[0] == "stop")
    setup = ("run", "--rm", "--no-deps", "--build", "cms-setup")
    cms_up = ("up", "-d", "--no-deps", "--build", "cms")
    consumer_up = next(event for event in events if isinstance(event, tuple) and event[:4] == cms_up[:4] and event != cms_up)
    assert events[:3] == ["request", "admitted", "drained"]
    assert events.index("drained") < events.index("snapshot") < events.index(stop)
    recorded_cohort = next(event for event in events if isinstance(event, tuple) and event[:2] == ("status", "restarting"))
    assert set(recorded_cohort[2]["prior_running_services"]) == set(stop[3:])
    assert events.index(recorded_cohort) < events.index(stop)
    assert set(stop[3:]) == {"api", "workflow-worker", "app-ai-worker"}
    assert events.index(stop) < events.index("refresh") < events.index("translations") < events.index(setup)
    assert events.index(setup) < events.index(cms_up) < events.index(("health", ("cms",))) < events.index(consumer_up)
    assert set(consumer_up[4:]) == {"api", "workflow-worker", "task-worker", "task-scheduler", "app-ai-worker"}
    assert state["running"] == set(consumer_up[4:])
    assert "recorded" in events
    assert any(event[:2] == ("status", "completed") for event in events if isinstance(event, tuple))


def test_dev_stack_operation_drain_is_independent_of_requested_services():
    assert sessions._docker_operation_resources(["cms", "api"]) == {sessions.DOCKER_RESOURCE_DEV_STACK}
    assert sessions._docker_operation_resources(["app-ai-worker"]) == {sessions.DOCKER_RESOURCE_DEV_STACK}


@pytest.mark.parametrize("failure", [
    "source_drift", "translations", "setup", "cms_before_setup", "cms_health",
    "cms_postbuild_none", "cms_postbuild_inspect_none", "consumer_up",
])
def test_gate_keeps_refreshed_consumers_stopped_on_failure(monkeypatch, tmp_path, failure):
    args, events, state = _harness(monkeypatch, tmp_path)
    state["failure"] = failure
    with pytest.raises(RuntimeError):
        sessions.cmd_docker_restart(args)
    assert state["commit"] == ("c" if failure == "source_drift" else "b") * 40
    assert state["running"] == set()
    assert not any(isinstance(event, tuple) and event[0] == "start" for event in events)
    if failure in {"source_drift", "translations", "setup", "cms_before_setup"}:
        assert not any(isinstance(event, tuple) and event[:4] == ("up", "-d", "--no-deps", "--build") for event in events)
    assert any(event[:2] == ("status", "failed") for event in events if isinstance(event, tuple))


@pytest.mark.parametrize("failure", ["cms_preflight_none", "cms_preflight_unhealthy"])
def test_gate_requires_cms_healthcheck_before_stopping_consumers(monkeypatch, tmp_path, failure):
    args, events, state = _harness(monkeypatch, tmp_path)
    state["failure"] = failure
    with pytest.raises(RuntimeError, match="CMS must be running and healthy"):
        sessions.cmd_docker_restart(args)
    assert state["commit"] == "a" * 40
    assert state["running"] == {"api", "workflow-worker", "app-ai-worker"}
    assert not any(isinstance(event, tuple) and event[0] == "stop" for event in events)
    assert "refresh" not in events


@pytest.mark.parametrize("failure", ["initial_stop", "refresh", "cms_after_stop"])
def test_gate_resumes_old_containers_only_when_source_is_unchanged(monkeypatch, tmp_path, failure):
    args, events, state = _harness(monkeypatch, tmp_path)
    state["failure"] = failure
    with pytest.raises(RuntimeError):
        sessions.cmd_docker_restart(args)
    assert state["commit"] == "a" * 40
    assert state["running"] == {"api", "workflow-worker", "app-ai-worker"}
    assert any(isinstance(event, tuple) and event[0] == "start" for event in events)
    assert not any(isinstance(event, tuple) and event[0] == "run" for event in events)


def test_gate_preserves_primary_error_when_cleanup_fails(monkeypatch, tmp_path):
    args, events, state = _harness(monkeypatch, tmp_path)
    state["failure"] = "translations"
    state["cleanup_failure"] = True
    with pytest.raises(RuntimeError, match="translation generation failed") as raised:
        sessions.cmd_docker_restart(args)
    assert any("cleanup stop failed" in note for note in raised.value.__notes__)
    assert any(event[:2] == ("status", "failed") for event in events if isinstance(event, tuple))


@pytest.mark.parametrize("setup_service,build,services", [
    ("vault-setup", True, ["cms"]),
    ("cms-setup", False, ["cms"]),
    ("cms-setup", True, ["api"]),
    ("cms-setup", True, ["cms", "cache"]),
])
def test_gate_rejects_invalid_request_before_lease(monkeypatch, tmp_path, setup_service, build, services):
    args, events, _state = _harness(monkeypatch, tmp_path)
    args.setup_service = setup_service
    args.build = build
    args.service = services
    with pytest.raises(RuntimeError):
        sessions.cmd_docker_restart(args)
    assert events == []
