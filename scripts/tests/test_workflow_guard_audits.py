"""Tests for OpenCode workflow guardrail audits.

Purpose: keep Apple release preflight and UI control visibility checks
deterministic, path-scoped, and importable from `code_quality_guard.py`.
Security: tests use in-memory examples only and do not access credentials.
Run: python3 -m pytest scripts/tests/test_workflow_guard_audits.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_apple_release_preflight_passes_current_repo_contracts() -> None:
    audit = load_module("audit_apple_release_preflight", ROOT / "scripts/audit_apple_release_preflight.py")

    assert audit.audit_paths([ROOT / "apple/project.yml"]) == []


def test_apple_release_preflight_ignores_unrelated_paths() -> None:
    audit = load_module("audit_apple_release_preflight", ROOT / "scripts/audit_apple_release_preflight.py")

    assert audit.audit_paths([ROOT / "README.md"]) == []


def test_apple_release_preflight_ignores_non_release_swift_paths() -> None:
    audit = load_module("audit_apple_release_preflight", ROOT / "scripts/audit_apple_release_preflight.py")

    assert audit.audit_paths([ROOT / "apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift"]) == []


def test_apple_release_preflight_validates_watch_source_membership() -> None:
    audit = load_module("audit_apple_release_preflight", ROOT / "scripts/audit_apple_release_preflight.py")

    project_text = (ROOT / "apple/project.yml").read_text(encoding="utf-8")
    xcode_text = (ROOT / "apple/OpenMates.xcodeproj/project.pbxproj").read_text(encoding="utf-8")

    assert audit.target_source_membership_issues(project_text, xcode_text) == []


def test_apple_release_preflight_rejects_watch_source_missing_from_target() -> None:
    audit = load_module("audit_apple_release_preflight", ROOT / "scripts/audit_apple_release_preflight.py")

    project_text = (ROOT / "apple/project.yml").read_text(encoding="utf-8")
    xcode_text = (ROOT / "apple/OpenMates.xcodeproj/project.pbxproj").read_text(encoding="utf-8")

    broken_xcode = xcode_text.replace("OpenMatesWatchApp.swift in Sources", "OpenMatesWatchApp.swift absent")

    assert any(
        "OpenMatesWatch" in issue and "OpenMatesWatchApp.swift" in issue
        for issue in audit.target_source_membership_issues(project_text, broken_xcode)
    )


def test_ui_control_visibility_blocks_new_control_without_identifier() -> None:
    audit = load_module("audit_ui_control_visibility", ROOT / "scripts/audit_ui_control_visibility.py")

    issues = audit.audit_added_lines(
        [
            (
                "apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift",
                100,
                "Button(action: sendMessage) { Text(AppStrings.send) }",
            )
        ]
    )

    assert len(issues) == 1
    assert issues[0].blocking is True
    assert "stable data-testid/accessibilityIdentifier" in issues[0].message


def test_ui_control_visibility_allows_nearby_identifier() -> None:
    audit = load_module("audit_ui_control_visibility", ROOT / "scripts/audit_ui_control_visibility.py")

    issues = audit.audit_added_lines(
        [
            (
                "apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift",
                100,
                "Button(action: sendMessage) { Text(AppStrings.send) }",
            ),
            (
                "apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift",
                101,
                '.accessibilityIdentifier("send-button")',
            ),
        ]
    )

    assert issues == []


def test_ui_control_visibility_uses_existing_nearby_identifier_context(tmp_path) -> None:
    audit = load_module("audit_ui_control_visibility", ROOT / "scripts/audit_ui_control_visibility.py")
    original_root = audit.REPO_ROOT
    audit.REPO_ROOT = tmp_path
    try:
        path = tmp_path / "apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift"
        path.parent.mkdir(parents=True)
        path.write_text(
            'Button(action: sendMessage) { Text(AppStrings.send) }\n.accessibilityIdentifier("send-button")\n',
            encoding="utf-8",
        )

        issues = audit.audit_added_lines(
            [("apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift", 1, "Button(action: sendMessage) { Text(AppStrings.send) }")]
        )
    finally:
        audit.REPO_ROOT = original_root

    assert issues == []


def test_ui_control_visibility_hook_mode_warns_from_explicit_path() -> None:
    audit = load_module("audit_ui_control_visibility", ROOT / "scripts/audit_ui_control_visibility.py")

    issues = audit.audit_file_controls([ROOT / "apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift"], blocking=False)

    assert all(issue.blocking is False for issue in issues)


def test_ui_control_visibility_warns_without_evidence_path() -> None:
    audit = load_module("audit_ui_control_visibility", ROOT / "scripts/audit_ui_control_visibility.py")

    issues = audit.audit_paths([ROOT / "apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift"], evidence_paths=[])

    assert any(issue.blocking is False and "visibility/clickability proof" in issue.message for issue in issues)


def test_ui_control_visibility_accepts_test_evidence_path() -> None:
    audit = load_module("audit_ui_control_visibility", ROOT / "scripts/audit_ui_control_visibility.py")

    issues = audit.audit_paths(
        [ROOT / "apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift"],
        evidence_paths=[ROOT / "apple/OpenMatesUITests/MessageInputAttachmentUITests.swift"],
    )

    assert issues == []
