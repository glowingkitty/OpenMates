"""The core update must finish schema setup before starting new email code."""
# contract-test-file: infrastructure

import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SETUP_OPERATION = [
    "up", "--no-deps", "--force-recreate",
    "--exit-code-from", "cms-setup", "cms-setup",
]


@pytest.fixture
def sidecar(monkeypatch, tmp_path):
    # Importing the sidecar normally marks the checkout as a Git safe.directory.
    monkeypatch.setenv("GIT_WORK_DIR", "")
    module_name = "backend.admin_sidecar.main"
    previous_module = sys.modules.pop(module_name, None)
    module = importlib.import_module("backend.admin_sidecar.main")
    monkeypatch.setattr(module, "_GIT_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(module, "_COMPOSE_PROJECT", "openmates")
    monkeypatch.setattr(module, "_COMPOSE_FILE", "backend/core/docker-compose.selfhost.yml")
    monkeypatch.setattr(module, "_SERVICE_UPDATE_TARGET", "api")
    monkeypatch.setattr(module, "_SERVICE_UPDATE_ALL", True)
    monkeypatch.setattr(module, "_SERVICE_UPDATE_EXTRAS", ["vault-setup", "cms-setup"])
    monkeypatch.setattr(module, "_CLEAR_CACHE_ON_UPDATE", False)
    yield module
    sys.modules.pop(module_name, None)
    if previous_module is not None:
        sys.modules[module_name] = previous_module


def _commands(sidecar, monkeypatch, *, failed_operation=None, timed_out_operation=None, timeouts=None):
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        operation = (
            command[command.index("--project-name") + 4 :]
            if command[:2] == ["docker", "compose"] else command
        )
        if timeouts is not None:
            timeouts.append((operation, _kwargs["timeout"]))
        if operation == timed_out_operation:
            raise subprocess.TimeoutExpired(command, _kwargs["timeout"])
        return SimpleNamespace(
            returncode=int(operation == failed_operation), stdout="", stderr=""
        )

    monkeypatch.setattr(sidecar.subprocess, "run", fake_run)
    return commands


def _operations(commands):
    # Strip Docker Compose's project and compose-file arguments.
    return [command[6:] for command in commands]


# contract-test: supporting surface=rest_api assertions=server-management.update.safety-sequence
def test_core_image_update_runs_fresh_setup_before_new_api_and_workers(sidecar, monkeypatch):
    timeouts = []
    commands = _commands(sidecar, monkeypatch, timeouts=timeouts)

    success, _log, steps = sidecar._run_update_script()

    assert success
    assert _operations(commands) == [
        ["pull"],
        ["stop", "api", "task-worker", "task-scheduler"],
        ["up", "-d", "--no-deps", "cms"],
        SETUP_OPERATION,
        ["up", "-d"],
        ["up", "-d", "vault-setup"],
    ]
    assert all(step["success"] for step in steps)
    assert (SETUP_OPERATION, sidecar._STEP_TIMEOUT_SETUP) in timeouts
    assert (["up", "-d"], sidecar._STEP_TIMEOUT_SETUP + sidecar._STEP_TIMEOUT_UP) in timeouts


# contract-test: supporting surface=rest_api assertions=server-management.update.safety-sequence
def test_core_update_blocks_new_stack_when_schema_setup_fails(sidecar, monkeypatch):
    commands = _commands(
        sidecar, monkeypatch, failed_operation=SETUP_OPERATION
    )

    success, log, steps = sidecar._run_update_script()

    assert not success
    assert _operations(commands) == [
        ["pull"],
        ["stop", "api", "task-worker", "task-scheduler"],
        ["up", "-d", "--no-deps", "cms"],
        SETUP_OPERATION,
    ]
    assert steps[-1]["success"] is False
    assert "old API and email consumers remain stopped" in log


# contract-test: supporting surface=rest_api assertions=server-management.update.safety-sequence
def test_core_update_blocks_full_swap_when_setup_times_out(sidecar, monkeypatch):
    commands = _commands(sidecar, monkeypatch, timed_out_operation=SETUP_OPERATION)

    success, log, steps = sidecar._run_update_script()

    assert not success
    assert _operations(commands)[-1] == SETUP_OPERATION
    assert steps[-1]["success"] is False
    assert "Timed out after 900s" in log


# contract-test: supporting surface=rest_api assertions=server-management.update.safety-sequence
def test_core_update_does_not_migrate_until_old_consumers_stop(sidecar, monkeypatch):
    commands = _commands(
        sidecar, monkeypatch, failed_operation=["stop", "api", "task-worker", "task-scheduler"]
    )

    success, _log, steps = sidecar._run_update_script()

    assert not success
    assert _operations(commands) == [
        ["pull"],
        ["stop", "api", "task-worker", "task-scheduler"],
    ]
    assert steps[-1]["success"] is False


# contract-test: supporting surface=rest_api assertions=server-management.update.safety-sequence
def test_core_update_does_not_run_setup_when_target_cms_fails_to_start(sidecar, monkeypatch):
    commands = _commands(
        sidecar, monkeypatch, failed_operation=["up", "-d", "--no-deps", "cms"]
    )

    success, _log, steps = sidecar._run_update_script()

    assert not success
    assert _operations(commands) == [
        ["pull"],
        ["stop", "api", "task-worker", "task-scheduler"],
        ["up", "-d", "--no-deps", "cms"],
    ]
    assert steps[-1]["success"] is False


# contract-test: supporting surface=rest_api assertions=server-management.update.safety-sequence
def test_core_git_update_builds_before_setup_and_clears_cache_after(sidecar, monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(sidecar, "_CLEAR_CACHE_ON_UPDATE", True)
    monkeypatch.setattr(sidecar, "_CACHE_VOLUME_NAME", "openmates-cache-data")
    commands = _commands(sidecar, monkeypatch)

    success, _log, _steps = sidecar._run_update_script()

    assert success
    assert commands[0] == ["git", "pull"]
    assert _operations(commands[1:5]) == [
        ["build"],
        ["stop", "api", "task-worker", "task-scheduler"],
        ["up", "-d", "--no-deps", "cms"],
        SETUP_OPERATION,
    ]
    assert _operations(commands[5:6]) == [["stop", "cache"]]
    assert commands[6] == ["docker", "volume", "rm", "-f", "openmates-cache-data"]
    assert _operations(commands[7:]) == [["up", "-d"], ["up", "-d", "vault-setup"]]


def test_satellite_update_keeps_target_and_extras_scope(sidecar, monkeypatch):
    monkeypatch.setattr(sidecar, "_SERVICE_UPDATE_ALL", False)
    monkeypatch.setattr(sidecar, "_SERVICE_UPDATE_TARGET", "preview")
    monkeypatch.setattr(sidecar, "_SERVICE_UPDATE_EXTRAS", ["vault-setup"])
    commands = _commands(sidecar, monkeypatch)

    success, _log, _steps = sidecar._run_update_script()

    assert success
    assert _operations(commands) == [
        ["pull", "preview"],
        ["up", "-d", "preview"],
        ["up", "-d", "vault-setup"],
    ]


@pytest.mark.parametrize(
    "compose_file",
    [
        "backend/core/docker-compose.yml",
        "backend/core/docker-compose.selfhost.yml",
        "frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml",
    ],
)
# contract-test: supporting surface=rest_api assertions=server-management.update.safety-sequence
def test_core_compose_requires_successful_setup_before_email_cohort(compose_file):
    compose = yaml.safe_load((ROOT / compose_file).read_text(encoding="utf-8"))
    for service in ("api", "task-worker", "task-scheduler"):
        assert compose["services"][service]["depends_on"]["cms-setup"] == {
            "condition": "service_completed_successfully"
        }
