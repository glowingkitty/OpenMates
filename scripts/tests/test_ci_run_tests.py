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


def test_artifact_profile_rejects_application_specs_and_shared_dev(monkeypatch):
    import pytest
    from scripts import ci_coverage
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    monkeypatch.setitem(sys.modules, "ci_coverage", ci_coverage)
    from scripts import ci_run_tests as runner
    with pytest.raises(ValueError, match="cannot run application"):
        runner.verify_artifact_profile(["tasks-flow.spec.ts"])
    monkeypatch.setattr(runner.socket, "gethostbyname_ex", lambda host: (host, [], ["192.0.2.1"]))
    with pytest.raises(RuntimeError, match="DNS"):
        runner.verify_artifact_profile(["security-reporting-email-proof.spec.ts"])
    monkeypatch.setattr(runner.socket, "gethostbyname_ex", lambda host: (host, [], ["127.0.0.2"]))
    monkeypatch.setattr(runner.socket, "create_connection", lambda *args, **kwargs: SimpleNamespace(close=lambda: None))
    with pytest.raises(RuntimeError, match="HTTPS"):
        runner.verify_artifact_profile(["security-reporting-email-proof.spec.ts"])


def test_artifact_browser_never_starts_stack_web_or_accounts(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner
    web = tmp_path / "web"
    (web / "tests").mkdir(parents=True)
    spec = "security-reporting-email-proof.spec.ts"
    (web / "tests" / spec).write_text("// synthetic artifact")
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(runner, "WEB", web)
    monkeypatch.setattr(runner, "RESULTS", results)
    monkeypatch.setattr(runner, "verify_artifact_profile", lambda specs: None)
    monkeypatch.setattr(runner, "provision_account", lambda *args: pytest.fail("Artifact proof must not provision accounts"))
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Artifact proof must not launch an app server"))
    monkeypatch.setenv("PLAYWRIGHT_TEST_API_URL", "https://shared.invalid")
    def browser(command, **kwargs):
        assert command[:4] == ["pnpm", "exec", "playwright", "test"]
        assert kwargs["env"]["PLAYWRIGHT_TEST_API_URL"] == "http://localhost:8000"
        Path(kwargs["env"]["PLAYWRIGHT_JSON_OUTPUT_NAME"]).write_text(json.dumps({"stats": {"expected": 1}}))
        return SimpleNamespace(returncode=0)
    from pathlib import Path
    monkeypatch.setattr(runner.subprocess, "run", browser)
    result = runner.run_e2e([spec], artifact=True)
    assert result[0]["exit_code"] == 0
    def partial_browser(command, **kwargs):
        Path(kwargs["env"]["PLAYWRIGHT_JSON_OUTPUT_NAME"]).write_text(json.dumps({"stats": {"expected": 1, "skipped": 1}}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, "run", partial_browser)
    incomplete = runner.run_e2e([spec], artifact=True)[0]
    assert incomplete["exit_code"] == 1
    assert incomplete["coverage_complete"] is False
    assert "incomplete" in incomplete["error"]


def test_reserved_account_policy_is_read_from_candidate_without_import(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/run_tests.py").write_text(
        "raise RuntimeError('old dispatcher must not execute')\n"
        "RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC = {'security.spec.ts': 18}\n"
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    assert runner.reserved_account_slot("security.spec.ts") == 18
    assert runner.reserved_account_slot("ordinary.spec.ts") == 1


def test_inherited_legacy_credentials_fail_before_account_setup(monkeypatch):
    import pytest
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner
    monkeypatch.setenv("TEST_ACCOUNT1", "synthetic-forbidden")
    with pytest.raises(RuntimeError, match="Inherited test credentials"):
        runner.reject_inherited_accounts()


def test_fresh_sdk_key_uses_private_session_and_bounded_lifetime(monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner
    import pytest
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"api_key":"sk-api-synthetic"}')
    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.provision_api_key({"OPENMATES_STATE_DIR": "/private/fresh"}) == "sk-api-synthetic"
    command, kwargs = calls[0]
    assert kwargs["env"]["OPENMATES_STATE_DIR"] == "/private/fresh"
    assert "client.createApiKey" in command[3]
    assert "FIXTURE_CREDIT_LIMIT = 1000" in command[3] and "expiresAt:" in command[3]
    assert kwargs["capture_output"] is True
    assert "d.api_key_id === result.key.id && d.machine_identifier === deviceId" in command[3]
    assert "api.chats.list({limit: 1})" in command[3]
    assert "chats.send" not in command[3]
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(RuntimeError, match="no shared-key fallback"):
        runner.provision_api_key({"OPENMATES_STATE_DIR": "/private/fresh"})


def test_signup_pacing_respects_real_rate_limit(monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner
    monkeypatch.setattr(runner, "_last_signup_started", None)
    now = [100.0]
    sleeps = []
    monkeypatch.setattr(runner.time, "monotonic", lambda: now[0])
    def sleep(delay):
        sleeps.append(delay)
        now[0] += delay
    monkeypatch.setattr(runner.time, "sleep", sleep)
    for _ in range(6):
        runner.pace_signup()
    assert sleeps == [15] * 5
    assert now[0] - 100 >= 60


def test_later_harness_failure_preserves_completed_results(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setenv("CI_TEST_MODE", "e2e")
    monkeypatch.setenv("GITHUB_RUN_ID", "unit-fixture")
    monkeypatch.setenv("CI_SPECS_JSON", '["first.spec.ts","second.spec.ts"]')
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **k: "a" * 40)
    def fail(specs, *, artifact, results):
        results.append({"spec": specs[0], "exit_code": 0})
        raise RuntimeError("second account fixture failed")
    monkeypatch.setattr(runner, "run_e2e", fail)
    assert runner.main() == 1
    report = json.loads((tmp_path / "ci-results.json").read_text())
    assert report["results"] == [{"spec":"first.spec.ts", "exit_code":0}]
    assert report["success"] is False


def test_proof_dimensions_use_full_canonical_frame(monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    for profile, expected in (("web-phone", {"width": 390, "height": 844}),
                              ("web-laptop", {"width": 1440, "height": 900})):
        monkeypatch.setenv("PLAYWRIGHT_PROOF_VIDEO_PROFILE", profile)
        monkeypatch.setenv("PLAYWRIGHT_VIDEO_HEIGHT", "630")
        monkeypatch.setenv("PLAYWRIGHT_VIDEO_WIDTH", "390")
        assert runner.configure_proof_dimensions() == expected
        assert runner.os.environ["PLAYWRIGHT_VIDEO_HEIGHT"] == str(expected["height"])
        assert runner.os.environ["PLAYWRIGHT_VIDEO_WIDTH"] == str(expected["width"])


def test_proof_dimensions_reject_unknown_profile(monkeypatch):
    import pytest
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setenv("PLAYWRIGHT_PROOF_VIDEO_PROFILE", "unknown")
    with pytest.raises(ValueError, match="Unsupported"):
        runner.configure_proof_dimensions()


def test_fresh_credit_fixture_uses_real_gift_and_rejects_wrong_balance(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"credits": runner.FIXTURE_CREDITS}))
    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.accept_fixture_credits({"OPENMATES_STATE_DIR": "/private/fresh"}) == 1000
    command, kwargs = calls[0]
    assert "/v1/auth/accept-gift" in command[3]
    assert "client.getSession().cookies" in command[3]
    assert kwargs["env"]["OPENMATES_STATE_DIR"] == "/private/fresh"
    assert kwargs["capture_output"] is True
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"credits": 0}'))
    with pytest.raises(RuntimeError, match="balance mismatch"):
        runner.accept_fixture_credits({"OPENMATES_STATE_DIR": "/private/fresh"})
