#!/usr/bin/env python3
"""Contracts for renewable shared-Docker test leases."""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_tests_control():
    path = PROJECT_ROOT / "scripts" / "tests.py"
    spec = importlib.util.spec_from_file_location("openmates_tests_control_lease", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_docker_lease_heartbeat_renews_until_runner_finishes(monkeypatch) -> None:
    control = load_tests_control()
    renewed = []
    monkeypatch.setattr(control.session_control, "DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(
        control.session_control,
        "renew_test_resource_lease",
        lambda lease_id, owner, resources, *, mode: renewed.append((lease_id, owner, resources, mode)),
    )

    def slow_run(command, **_kwargs):
        time.sleep(0.035)
        return control.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(control.subprocess, "run", slow_run)

    result = control.run_with_resource_lease_heartbeats(
        ["runner"],
        env={},
        leases=[("test-123", "session-1", {"dev-stack"}, "shared")],
    )

    assert result == 0
    assert renewed
    assert renewed[0] == ("test-123", "session-1", {"dev-stack"}, "shared")
