# contract-test-file: tooling
"""Capacity startup retains exact guards and reports only safe failure facts."""
import contextlib
import io
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import ci_environment as environment

SOURCE = "a" * 40


def completed(details, code=0):
    return SimpleNamespace(returncode=code, stdout=json.dumps(details), stderr="secret-response-body")


def verified():
    return {"status": "published", "source_commit": SOURCE, "api_processes": 2, "expires_in_seconds": 180}


def verify(result):
    return environment.run_capacity_startup_guard(
        "inventory_refresh", lambda: result, expected_status="published", source_commit=SOURCE,
    )


def test_inventory_requires_typed_exact_source_process_count_and_short_expiry():
    assert verify(completed(verified()))["api_processes"] == 2
    for field, value in [("source_commit", "b" * 40), ("api_processes", 0), ("api_processes", True),
                         ("api_processes", 129), ("expires_in_seconds", 181), ("status", "paused")]:
        with pytest.raises(RuntimeError, match="inventory_refresh"):
            verify(completed({**verified(), field: value}))


@pytest.mark.parametrize("raw", ["{bad-json", "private-value" * 7000, "[]", "null"])
def test_malformed_or_oversized_output_cannot_attest_or_escape_diagnostics(raw):
    with pytest.raises(RuntimeError) as error:
        verify(SimpleNamespace(returncode=1, stdout=raw, stderr="secret-response-body"))
    assert "private-value" not in str(error.value)
    assert "secret-response-body" not in str(error.value)


def test_failure_details_are_allowlisted_and_untrusted_fields_never_print():
    result = completed({"status": "paused", "stage": "inspect", "reason": "api_worker_inventory_incomplete",
                        "error_class": "ValueError", "api_processes": 0, "exit_code": 1,
                        "source_commit": SOURCE, "message": "private-body", "provider": "private-name"}, 1)
    with pytest.raises(RuntimeError) as error:
        verify(result)
    message = str(error.value)
    assert "failed_stage=inspect" in message and "api_worker_inventory_incomplete" in message
    assert "class=ValueError" in message and "api_processes=0" in message
    assert "private" not in message
    result = completed({"status": {}, "stage": [], "reason": "private-name", "error_class": "private-key",
                        "source_commit": "private-source", "api_processes": "private-pid"}, 2)
    with pytest.raises(RuntimeError) as error:
        verify(result)
    assert "private" not in str(error.value)


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("secret-command", 90),
                                    subprocess.CalledProcessError(3, "secret-command", output="secret-body", stderr="secret-key")])
def test_subprocess_failures_keep_only_stage_exit_or_timeout(failure):
    def fail():
        raise failure
    with pytest.raises(RuntimeError) as error:
        environment.run_capacity_startup_guard("inventory_refresh", fail, expected_status="published", source_commit=SOURCE)
    assert "inventory_refresh" in str(error.value) and "secret" not in str(error.value)


@pytest.mark.parametrize("fault", [None, "bootstrap", "rollout"])
def test_fixture_setup_records_only_source_count_or_failed_stage(monkeypatch, fault):
    calls = []
    task = SimpleNamespace(directus_service=object(), initialize_core_services=AsyncMock(), cleanup_services=AsyncMock())
    if fault == "bootstrap":
        task.initialize_core_services.side_effect = ValueError("secret-value")
    async def write(service, collection, row):
        if fault == "rollout":
            raise RuntimeError("secret-value")
        calls.append((service, collection, row))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.base_task", SimpleNamespace(BaseServiceTask=lambda: task))
    monkeypatch.setitem(sys.modules, "scripts.storage_rollout", SimpleNamespace(COLLECTIONS=("chat", "embed"), write_rollout=write))
    monkeypatch.setenv("BUILD_COMMIT_SHA", SOURCE)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        if fault:
            with pytest.raises(SystemExit) as error:
                exec(environment.CAPACITY_FIXTURE_SETUP, {})
            assert error.value.code == 1
        else:
            exec(environment.CAPACITY_FIXTURE_SETUP, {})
    data = json.loads(output.getvalue())
    assert "secret" not in output.getvalue()
    assert task.cleanup_services.await_count == 1
    if fault:
        assert data["status"] == "failed" and data["stage"] == fault
    else:
        assert data == {"status": "ready", "source_commit": SOURCE, "collections_count": 2}
        assert len(calls) == 2
        assert all(row["reader_receipt"] == "ci-storage-capacity:" + SOURCE for _, _, row in calls)
        assert environment.run_capacity_startup_guard("fixture_setup", lambda: completed(data),
            expected_status="ready", source_commit=SOURCE) == data


def test_retained_startup_report_contains_only_typed_allowlisted_facts(tmp_path):
    path = tmp_path / "startup.json"
    environment.run_capacity_startup_guard("inventory_refresh", lambda: completed(verified()),
        expected_status="published", source_commit=SOURCE, diagnostic_path=path)
    with pytest.raises(RuntimeError):
        environment.run_capacity_startup_guard("fixture_setup", lambda: completed({
            "status": "failed", "stage": "bootstrap", "reason": "runtime_inventory_bootstrap_failed",
            "error_class": "ModuleNotFoundError", "message": "private-secret-value", "source_commit": "private-source",
        }, 1), expected_status="ready", source_commit=SOURCE, diagnostic_path=path)
    raw = path.read_text()
    assert "private" not in raw
    report = json.loads(raw)
    assert report["schema"] == "agentic-storage-capacity-startup-v1"
    assert [item["admitted"] for item in report["checks"]] == [True, False]
    assert report["checks"][0]["api_processes"] == 2
    assert report["checks"][1]["reason"] == "runtime_inventory_bootstrap_failed"
    assert path.stat().st_mode & 0o777 == 0o600
