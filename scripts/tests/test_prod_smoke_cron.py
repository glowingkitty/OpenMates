"""The prod smoke cron entry must reach run_tests.main(), not the CI forwarder (TASK-832)."""

# contract-test-file: infrastructure

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import prod_smoke_cron, run_tests

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
    assert prod_smoke_cron.main([suite, "--dry-run"]) == 7
    assert seen["argv"] == ["run_tests.py", flag, "--dry-run"]


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
