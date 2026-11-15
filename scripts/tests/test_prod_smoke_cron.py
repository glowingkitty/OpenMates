"""The prod smoke cron entry must reach run_tests.main(), not the CI forwarder (TASK-832)."""

# contract-test-file: infrastructure

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import prod_email_health, prod_smoke_cron, run_tests

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("suite", "flag"),
    [("free-hourly", "--prod-free-hourly"), ("paid-chat", "--prod-paid-chat"), ("app-skill", "--prod-app-skill")],
)
def test_each_suite_calls_run_tests_main_with_its_prod_flag(monkeypatch, suite, flag):
    seen = {}

    def fake_main():
        seen["argv"] = list(sys.argv)
        return 7

    monkeypatch.setattr(run_tests, "main", fake_main)
    monkeypatch.setitem(sys.modules, "run_tests", run_tests)
    monkeypatch.setattr(prod_email_health, "run", lambda dry_run=False: 0)
    monkeypatch.setitem(sys.modules, "prod_email_health", prod_email_health)
    assert prod_smoke_cron.main([suite, "--dry-run"]) == 7
    assert seen["argv"] == ["run_tests.py", flag, "--dry-run"]


@pytest.mark.parametrize(("suite", "expected_calls"), [("free-hourly", [True]), ("paid-chat", []), ("app-skill", [])])
def test_only_the_hourly_smoke_runs_the_email_health_check(monkeypatch, suite, expected_calls):
    """TASK-427: the hourly prod smoke also proves transactional email works."""
    calls = []
    monkeypatch.setattr(run_tests, "main", lambda: 0)
    monkeypatch.setitem(sys.modules, "run_tests", run_tests)
    monkeypatch.setattr(prod_email_health, "run", lambda dry_run=False: calls.append(dry_run) or 1)
    monkeypatch.setitem(sys.modules, "prod_email_health", prod_email_health)
    rc = prod_smoke_cron.main([suite, "--dry-run"])
    assert calls == expected_calls
    # A failing email check fails the cron run even when the browser smoke is green.
    assert rc == (1 if expected_calls else 0)


def test_run_tests_cli_still_forwards_prod_flags_to_a_dispatcher_without_them():
    """Why the cron cannot call run_tests.py directly: the forwarder rejects --prod-*."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_tests.py"), "--prod-free-hourly", "--dry-run"],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 2
    assert "unrecognized arguments: --prod-free-hourly" in result.stderr


def test_unknown_suite_is_rejected():
    with pytest.raises(SystemExit):
        prod_smoke_cron.main(["everything"])
