"""Contract runner must never revive obsolete probes from an existing container."""
# contract-test-file: tooling
import json
from types import SimpleNamespace

import pytest

from scripts import run_provider_contracts as runner


def test_no_configured_probes_does_not_start_container_or_read_credentials(monkeypatch):
    assert runner.CONFIGURED_PROVIDER_PROBES == {}
    monkeypatch.setattr(runner, "_run", lambda *a, **k: pytest.fail("No container execution is allowed"))
    monkeypatch.setattr(runner, "_load_env_value", lambda *a: pytest.fail("No credentials are needed"))
    code, report = runner._run_probes(None)
    assert code == 0
    assert report == {"status": "not_configured", "tests": [], "summary": {"collected": 0, "total": 0}}


def test_unknown_explicit_provider_is_rejected_without_execution(monkeypatch):
    monkeypatch.setattr(runner, "_run", lambda *a, **k: pytest.fail("Unknown probes must not execute"))
    code, report = runner._run_probes("unconfigured-provider")
    assert code == 2 and report["status"] == "not_configured"
    assert "no configured probe" in report["error"]


def test_default_main_reports_no_checks_instead_of_passing(monkeypatch, capsys):
    reports = []
    monkeypatch.setattr(runner.sys, "argv", ["run_provider_contracts.py"])
    monkeypatch.setattr(runner, "write_nightly_report", lambda **kwargs: reports.append(kwargs))
    monkeypatch.setattr(runner, "_run", lambda *a, **k: pytest.fail("No provider calls are allowed"))
    monkeypatch.setattr(runner, "_notify_broken_providers", lambda *a: pytest.fail("No notification is needed"))
    assert runner.main() == 0
    assert reports == [{"job": "provider-contracts", "status": "skipped",
                        "summary": "No provider contract probes configured; no checks executed.",
                        "details": {"configured_providers": [], "checks_executed": 0}}]
    assert "all passing" not in capsys.readouterr().out


def test_registered_probe_uses_explicit_files_without_directory_discovery(monkeypatch, tmp_path):
    calls = []
    report = {"tests": [{"nodeid": "test_sample_contract.py::test_shape", "outcome": "passed"}],
              "summary": {"passed": 1, "total": 1}}
    def fake_run(command):
        calls.append(command)
        if command[:2] == ["docker", "cp"]:
            (tmp_path / "provider-contracts-raw.json").write_text(json.dumps(report))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(runner, "CONFIGURED_PROVIDER_PROBES", {"sample": "test_sample_contract.py"})
    monkeypatch.setattr(runner, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(runner, "_run", fake_run)
    code, actual = runner._run_probes(None)
    assert code == 0 and actual == report
    assert runner.CONTAINER_TESTS_PATH not in calls[0]
    assert f"{runner.CONTAINER_TESTS_PATH}/test_sample_contract.py" in calls[0]
    assert runner._summarise(actual)["sample"]["passed"] == 1
