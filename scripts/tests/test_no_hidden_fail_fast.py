# contract-test-file: tooling
"""Dev test and build runs report every failure: no fail-fast flag hides later results."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ci_apple  # noqa: E402
import ci_rust_check  # noqa: E402

FAIL_FAST = re.compile(r"""["'](?:--maxfail(?:=\d+)?|--exitfirst|--bail(?:=\d+)?|--max-failures(?:=\d+)?)["']""")
RUNNERS = [
    "scripts/ci_run_tests.py",
    "scripts/ci_rust_check.py",
    "scripts/ci_apple.py",
    "scripts/ci_sdk_conformance.py",
    "scripts/run_tests.py",
    ".github/workflows/isolated-tests.yml",
]


def test_ci_runners_never_pass_fail_fast_flags():
    offenders = [path for path in RUNNERS if FAIL_FAST.search((ROOT / path).read_text())]
    assert offenders == []


def test_pytest_invocations_never_use_x():
    text = (ROOT / "scripts/ci_run_tests.py").read_text()
    for call in re.finditer(r'"pytest",(.*?)\]', text, re.S):
        assert '"-x"' not in call.group(1)


def test_cargo_test_runs_every_test_binary():
    assert "--no-fail-fast" in ci_rust_check.TEST_FLAGS
    for _name, command in ci_rust_check.plan("all") + ci_rust_check.plan("openmates-sdk"):
        if command[:2] == ["cargo", "test"]:
            assert "--no-fail-fast" in command
    for _name, command, _env, _skip in ci_apple.core_plan(ROOT, ROOT / "test-results"):
        if command[:2] == ["cargo", "test"]:
            assert "--no-fail-fast" in command


def test_playwright_ci_forbids_only_and_never_caps_failures():
    config = (ROOT / "frontend/apps/web_app/playwright.config.ts").read_text()
    assert "forbidOnly: Boolean(process.env.CI)" in config
    assert "maxFailures" not in config


def test_scripts_tests_run_every_spec_by_default():
    # The parser lives inside run_tests.main(); fail-fast is an explicit opt-in there.
    source = (ROOT / "scripts/run_tests.py").read_text()
    assert 'parser.add_argument("--fail-fast", action="store_true"' in source
    assert 'self.fail_fast = bool(getattr(args, "fail_fast", False)) and not args.no_fail_fast' in source
