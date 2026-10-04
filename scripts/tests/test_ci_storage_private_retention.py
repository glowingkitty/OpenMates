# contract-test-file: infrastructure
"""Exact private storage diagnostics survive credential teardown and stay bounded."""

import importlib.util
import json
import os
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_diagnostics_survive_real_stop_path_and_upload_allowlist(tmp_path, monkeypatch):
    environment = _load(SCRIPTS / "ci_environment.py", "_private_retention_environment")
    monkeypatch.setitem(sys.modules, "ci_environment", environment)
    repository = next(parent for parent in SCRIPTS.parents
                      if (parent / "scripts/ci_pytest_targets.py").is_file())
    monkeypatch.syspath_prepend(str(repository))
    runner = _load(SCRIPTS / "ci_run_tests.py", "_private_retention_runner")
    results = tmp_path / "test-results"
    private = results / "ci-private"
    accountability = private / "accountability"
    accountability.mkdir(parents=True, mode=0o700)
    os.chmod(accountability, 0o700)
    (private / "compose.json").write_text("{}")
    (private / "account-token").write_text("secret")
    receipt = accountability / "receipt.json"
    receipt.write_text('{"private_fixture_id":"synthetic"}')
    os.chmod(receipt, 0o600)
    failures = private / "capacity-results.jsonl"
    failures.write_text(json.dumps({"kind": "failure", "phase": "version_readback",
                                    "error_class": "Error", "source_location": "adapter:99",
                                    "reason": "synthetic detail"}) + "\n")
    monkeypatch.setattr(runner, "RESULTS", results)
    monkeypatch.setattr(runner, "COMPOSE_PATH", private / "compose.json")
    assert runner.retain_capacity_failure_rows(failures, private) == 1
    assert runner.retain_storage_accountability_private_evidence() == ["receipt.retained.json"]
    capacity_file = results / "ci-capacity-private/capacity-failure-rows.jsonl"
    account_file = results / "ci-accountability-private/receipt.retained.json"
    for path in (capacity_file, account_file):
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
    monkeypatch.setattr(environment, "SOURCE", tmp_path)
    monkeypatch.setattr(environment, "COMPOSE_PATH", private / "compose.json")
    monkeypatch.setattr(environment, "require_runner", lambda: None)
    monkeypatch.setattr(environment, "compose", lambda *args: None)
    monkeypatch.setattr(environment.subprocess, "check_output", lambda *args, **kwargs: "")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setattr(sys, "argv", ["ci_environment.py", "stop"])
    environment.main()
    assert not private.exists()
    assert capacity_file.is_file() and account_file.is_file()
    workflow = (SCRIPTS.parent / ".github/workflows/isolated-tests.yml").read_text()
    assert "isolated-storage-private-diagnostics" in workflow
    assert "subject/test-results/ci-capacity-private/capacity-failure-rows.jsonl" in workflow
    assert "subject/test-results/ci-accountability-private/receipt.retained.json" in workflow
    public_upload = workflow.split("name: isolated-test-results", 1)[1].split("name: isolated-storage-private-diagnostics", 1)[0]
    assert "ci-capacity-private" not in public_upload
    assert "ci-accountability-private" not in public_upload


def test_capacity_retention_refuses_unbounded_or_reused_private_path(tmp_path, monkeypatch):
    environment = _load(SCRIPTS / "ci_environment.py", "_private_retention_environment_reject")
    monkeypatch.setitem(sys.modules, "ci_environment", environment)
    repository = next(parent for parent in SCRIPTS.parents
                      if (parent / "scripts/ci_pytest_targets.py").is_file())
    monkeypatch.syspath_prepend(str(repository))
    runner = _load(SCRIPTS / "ci_run_tests.py", "_private_retention_runner_reject")
    results = tmp_path / "test-results"
    private = results / "ci-private"
    private.mkdir(parents=True)
    failures = private / "capacity-results.jsonl"
    failures.write_text(json.dumps({"kind": "failure", "reason": "x" * 5000}) + "\n")
    monkeypatch.setattr(runner, "RESULTS", results)
    assert runner.retain_capacity_failure_rows(failures, private) == 0
    failures.write_text(json.dumps({"kind": "failure", "reason": "synthetic"}) + "\n")
    assert runner.retain_capacity_failure_rows(failures, private) == 1
    import pytest
    with pytest.raises(FileExistsError):
        runner.retain_capacity_failure_rows(failures, private)
