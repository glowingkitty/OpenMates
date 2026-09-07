# contract-test-file: tooling
"""Protect daily unit coverage and honest failure aggregation in the CI harness.

The harness invokes subprocesses only on GitHub; this unit test substitutes a
recording transport and checks that a failed suite does not hide the SDK gate.
No application requests, browser, Docker or real test account are started here.
See docs/architecture/isolated-github-tests.md.
"""

import json
import sys
from types import SimpleNamespace
from scripts import ci_environment


def test_daily_pytest_preserves_sdk_gate_after_unit_failure(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "RESULTS", tmp_path / "test-results")
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setenv("CI_TEST_MODE", "pytest")
    monkeypatch.setenv("GITHUB_RUN_ID", "7")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1 if "backend/tests" in command else 0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(
        runner.subprocess, "check_output", lambda *args, **kwargs: "a" * 40
    )
    assert runner.main() == 1
    assert any(
        "packages/openmates-python/tests/test_account_import.py" in command
        for command in calls
    )
    assert any(
        "packages/openmates-python/tests/test_account_export.py" in command
        for command in calls
    )
    report = json.loads((runner.RESULTS / "ci-results.json").read_text())
    assert report["success"] is False
    assert [item["exit_code"] for item in report["results"]] == [1, 0]


def test_fixture_cms_auth_uses_generated_credentials_and_checks_identity(monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    profile = ci_environment.compose_profile("a" * 40)
    environment = profile["services"]["api"]["environment"]
    calls = []

    def request(url, data=None, token=None):
        calls.append((url, data, token))
        if url.endswith("/auth/login"):
            assert data["password"] == environment["DATABASE_ADMIN_PASSWORD"]
            return {"data": {"access_token": "synthetic-access"}}
        assert token == "synthetic-access"
        return {"data": {"email": environment["DATABASE_ADMIN_EMAIL"]}}

    monkeypatch.setattr(runner, "request", request)
    assert runner.cms_admin_token(profile) == "synthetic-access"
    assert len(calls) == 2

    monkeypatch.setattr(runner, "request", lambda *args, **kwargs: {"data": {}})
    import pytest

    with pytest.raises(RuntimeError, match="did not issue"):
        runner.cms_admin_token(profile)
