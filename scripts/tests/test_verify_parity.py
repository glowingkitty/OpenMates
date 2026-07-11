#!/usr/bin/env python3
"""Tests for cross-client parity verification orchestration.

Purpose: prevent parity checks from regressing into direct local test commands.
Architecture: imports scripts/verify_parity.py and inspects generated run plans.
Safety: no subprocesses are executed; tests cover command construction only.
Evidence: python3 -m pytest scripts/tests/test_verify_parity.py.
"""

from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "verify_parity.py"


def load_verify_parity():
    spec = importlib.util.spec_from_file_location("verify_parity", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["verify_parity"] = module
    spec.loader.exec_module(module)
    return module


def default_args(**overrides):
    values = {
        "web_spec": ["chat-flow.spec.ts"],
        "skip_web": None,
        "apple": "build",
        "apple_platform": "ios",
        "skip_apple": None,
        "simulator": "iPhone 17",
        "only_testing": None,
    }
    values.update(overrides)
    return Namespace(**values)


def test_run_plan_uses_repo_control_plane_for_cli_and_web() -> None:
    verify_parity = load_verify_parity()

    plan = verify_parity.build_run_plan(default_args())

    commands = {phase: command for phase, command, _reason in plan}
    assert commands["sdk-cli-static"] == [sys.executable, "scripts/audit_sdk_cli_parity.py"]
    assert commands["cli"] == [sys.executable, "scripts/tests.py", "run", "--suite", "cli"]
    assert commands["web:chat-flow.spec.ts"] == [
        sys.executable,
        "scripts/tests.py",
        "run",
        "--spec",
        "chat-flow.spec.ts",
    ]


def test_run_plan_never_uses_direct_playwright_or_vitest_commands() -> None:
    verify_parity = load_verify_parity()

    plan = verify_parity.build_run_plan(default_args())
    flattened = " ".join(" ".join(command or []) for _phase, command, _reason in plan)

    assert "playwright test" not in flattened
    assert "npm run test:unit" not in flattened
    assert "vitest" not in flattened


def test_web_and_apple_skips_require_explicit_reasons() -> None:
    verify_parity = load_verify_parity()

    plan = verify_parity.build_run_plan(
        default_args(
            web_spec=None,
            skip_web="browser-only verification covered by linked design review",
            apple="skip",
            skip_apple="Apple not affected",
        )
    )

    skips = {phase: reason for phase, command, reason in plan if command is None}
    assert skips["web"] == "browser-only verification covered by linked design review"
    assert skips["apple"] == "Apple not affected"


@pytest.mark.parametrize(
    ("apple_mode", "expected_command"),
    [
        ("build", [sys.executable, "scripts/apple_remote.py", "build-macos"]),
        (
            "test",
            [
                sys.executable,
                "scripts/apple_remote.py",
                "test-macos",
                "--only-testing",
                "OpenMatesMacUITests/SettingsMacShellParityUITests",
            ],
        ),
    ],
)
def test_run_plan_supports_first_class_macos_verification(apple_mode, expected_command) -> None:
    verify_parity = load_verify_parity()

    plan = verify_parity.build_run_plan(
        default_args(
            apple=apple_mode,
            apple_platform="macos",
            only_testing="OpenMatesMacUITests/SettingsMacShellParityUITests" if apple_mode == "test" else None,
        )
    )

    commands = {phase: command for phase, command, _reason in plan}
    assert commands["apple"] == expected_command


def test_cli_parser_requires_reason_for_apple_skip() -> None:
    verify_parity = load_verify_parity()

    with pytest.raises(SystemExit):
        verify_parity.main(["--run", "--apple", "skip", "--skip-web", "web not affected"])
