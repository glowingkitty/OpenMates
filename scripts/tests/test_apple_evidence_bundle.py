#!/usr/bin/env python3
"""Tests for Apple evidence bundle orchestration.

Purpose: keep Apple debugging/parity evidence deterministic and privacy-safe.
Architecture: imports scripts/apple_evidence_bundle.py and inspects run plans.
Safety: no SSH, Xcode, simulator, or real account credentials are required.
Evidence: python3 -m pytest scripts/tests/test_apple_evidence_bundle.py.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "apple_evidence_bundle.py"


def load_apple_evidence_bundle():
    spec = importlib.util.spec_from_file_location("apple_evidence_bundle", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["apple_evidence_bundle"] = module
    spec.loader.exec_module(module)
    return module


def default_args(**overrides):
    values = {
        "surface": "chat",
        "output_dir": ROOT / "test-results" / "apple-evidence-test",
        "dry_run": True,
        "stop_on_failure": True,
        "remote": "none",
        "sync_repo": False,
        "branch": "dev",
        "simulator": "iPhone 17",
        "only_testing": None,
        "duration": 60,
        "fresh_install": False,
        "compare_chat_rendering": False,
        "chat_artifact_dir": ROOT / "artifacts" / "chat-rendering-parity",
        "strict_order": False,
        "minimum_overlap": 5,
    }
    values.update(overrides)
    return Namespace(**values)


def commands_by_name(steps):
    return {step.name: step.command for step in steps}


def test_default_chat_plan_uses_static_linux_safe_checks() -> None:
    bundle = load_apple_evidence_bundle()

    commands = commands_by_name(bundle.build_steps(default_args()))

    assert commands["apple-parity-inventory"] == [
        sys.executable,
        "scripts/apple_parity_audit.py",
        "--output",
        "test-results/apple-parity-inventory.json",
    ]
    assert commands["apple-parity-inventory-check"] == [
        sys.executable,
        "scripts/apple_parity_audit.py",
        "--check",
        "--output",
        "test-results/apple-parity-inventory.json",
    ]
    assert commands["apple-chat-parity-audit"] == [sys.executable, "scripts/apple_chat_parity_audit.py"]
    assert commands["apple-ui-contracts:message-input"] == [
        sys.executable,
        "scripts/apple_ui_contracts.py",
        "audit",
        "--surface",
        "message-input",
    ]
    assert not any(command[1:2] == ["scripts/apple_remote.py"] for command in commands.values())


def test_all_surface_plan_includes_all_ui_contract_audits() -> None:
    bundle = load_apple_evidence_bundle()

    commands = commands_by_name(bundle.build_steps(default_args(surface="all")))

    assert "apple-ui-contracts:message-input" in commands
    assert "apple-ui-contracts:settings" in commands
    assert "apple-ui-contracts:embeds" in commands
    assert "apple-chat-parity-audit" in commands


def test_remote_test_plan_is_explicit_and_runs_readiness_first() -> None:
    bundle = load_apple_evidence_bundle()

    steps = bundle.build_steps(
        default_args(
            remote="test-ios",
            sync_repo=True,
            only_testing="OpenMatesUITests/ChatFlowRealAccountUITests/testPasswordOtpLoginLoadsRecentChatsForWebParityManifest",
        )
    )
    commands = commands_by_name(steps)
    names = [step.name for step in steps]

    assert names.index("apple-remote-status") < names.index("apple-remote-doctor")
    assert names.index("apple-remote-doctor") < names.index("apple-remote-sync-repo")
    assert names.index("apple-remote-sync-repo") < names.index("apple-remote-test-ios")
    assert commands["apple-remote-test-ios"] == [
        sys.executable,
        "scripts/apple_remote.py",
        "test-ios",
        "--simulator",
        "iPhone 17",
        "--only-testing",
        "OpenMatesUITests/ChatFlowRealAccountUITests/testPasswordOtpLoginLoadsRecentChatsForWebParityManifest",
    ]


def test_remote_startup_plan_supports_fresh_install() -> None:
    bundle = load_apple_evidence_bundle()

    commands = commands_by_name(bundle.build_steps(default_args(remote="startup-ios", fresh_install=True, duration=45)))

    assert commands["apple-remote-verify-ios-startup"] == [
        sys.executable,
        "scripts/apple_remote.py",
        "verify-ios-startup",
        "--simulator",
        "iPhone 17",
        "--duration",
        "45",
        "--fresh-install",
    ]


def test_chat_rendering_comparison_steps_use_sanitized_manifest_paths() -> None:
    bundle = load_apple_evidence_bundle()

    commands = commands_by_name(bundle.build_steps(default_args(compare_chat_rendering=True, minimum_overlap=10)))

    assert commands["chat-rendering-compare:loaded-chats"] == [
        sys.executable,
        "scripts/compare_chat_render_parity.py",
        "--web",
        "artifacts/chat-rendering-parity/web-loaded-chats-manifest.json",
        "--apple",
        "artifacts/chat-rendering-parity/apple-loaded-chats-manifest.json",
        "--minimum-overlap",
        "10",
    ]
    assert commands["chat-rendering-compare:opened-chats"][-1] == "--strict-order"


def test_output_redaction_removes_private_values() -> None:
    bundle = load_apple_evidence_bundle()

    redacted = bundle.sanitize_output(
        "OPENMATES_TEST_ACCOUNT_EMAIL=alice@example.com path=/Users/alice/OpenMates "
        "ip=192.168.1.10 url=https://app/#key=secret 0123456789abcdef0123456789abcdef"
    )

    assert "alice@example.com" not in redacted
    assert "OPENMATES_TEST_ACCOUNT_EMAIL=<redacted>" in redacted
    assert "/Users/alice" not in redacted
    assert "192.168.1.10" not in redacted
    assert "#key=secret" not in redacted
    assert "0123456789abcdef0123456789abcdef" not in redacted
    assert "<email>" in redacted or "<redacted>" in redacted


def test_persisted_command_redacts_private_paths() -> None:
    bundle = load_apple_evidence_bundle()

    result = bundle.StepResult(
        name="private-command",
        status="planned",
        command=["python3", "/Users/alice/OpenMates/script.py", "--email=alice@example.com"],
        required=True,
        started_at="2026-07-19T00:00:00Z",
        completed_at="2026-07-19T00:00:00Z",
    ).as_dict()

    assert "/Users/alice" not in " ".join(result["command"])
    assert "alice@example.com" not in " ".join(result["command"])
    assert "/<private-path>" in " ".join(result["command"])


def test_dry_run_writes_machine_readable_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = load_apple_evidence_bundle()
    monkeypatch.setattr(bundle, "git_subject_commit", lambda: "abc123")

    exit_code = bundle.run_bundle(default_args(output_dir=tmp_path, remote="none"))

    latest = tmp_path / "latest-summary.json"
    summary = json.loads(latest.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert summary["schema_version"] == 1
    assert summary["subject_commit"] == "abc123"
    assert summary["surface"] == "chat"
    assert summary["remote"] == "none"
    assert summary["overall_status"] == "planned"
    assert summary["privacy"]["sanitized"] is True
    assert summary["steps"][0]["name"] == "apple-remote"
    assert summary["steps"][0]["status"] == "skipped_with_reason"
    assert {step["status"] for step in summary["steps"][1:]} == {"planned"}


def test_summary_redacts_private_output_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = load_apple_evidence_bundle()
    monkeypatch.setattr(bundle, "git_subject_commit", lambda: "abc123")

    private_dir = Path("/home/alice/OpenMates/private-evidence")
    monkeypatch.setattr(Path, "mkdir", lambda self, parents=False, exist_ok=False: None)
    writes: dict[str, str] = {}
    monkeypatch.setattr(Path, "write_text", lambda self, text, encoding=None: writes.setdefault(str(self), text) or len(text))

    exit_code = bundle.run_bundle(default_args(output_dir=private_dir, remote="none"))
    summary = json.loads(next(iter(writes.values())))

    assert exit_code == 0
    assert "/home/alice" not in summary["artifact_dir"]
    assert summary["artifact_dir"] == "/<private-path>"


def test_parser_rejects_remote_test_without_target() -> None:
    bundle = load_apple_evidence_bundle()

    with pytest.raises(SystemExit):
        bundle.main(["--dry-run", "--remote", "test-ios"])
