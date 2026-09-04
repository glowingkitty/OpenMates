"""Tests for OpenCode workflow guardrail audits.

Purpose: keep Apple release preflight, UI control visibility, and Figma visual
evidence checks deterministic, path-scoped, and importable from
`code_quality_guard.py`. Security: tests use in-memory examples only and do not
access credentials. Run: python3 -m pytest scripts/tests/test_workflow_guard_audits.py.
"""

# contract-test-file: infrastructure

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


def test_apple_release_preflight_requires_push_configuration() -> None:
    audit = load_module("audit_apple_release_preflight", ROOT / "scripts/audit_apple_release_preflight.py")

    issues = audit.audit_paths([ROOT / "apple/project.yml"])

    assert not any("aps-environment" in issue for issue in issues)
    assert not any("notification service" in issue.lower() for issue in issues)
    assert not any("push token logging" in issue.lower() for issue in issues)


def test_apple_release_preflight_rejects_notification_service_source_drift() -> None:
    audit = load_module("audit_apple_release_preflight", ROOT / "scripts/audit_apple_release_preflight.py")
    project_text = (ROOT / "apple/project.yml").read_text(encoding="utf-8")
    xcode_text = (ROOT / "apple/OpenMates.xcodeproj/project.pbxproj").read_text(encoding="utf-8")

    broken_project = project_text.replace(
        "      - path: OpenMates/Sources/Core/Networking/NotificationPreviewCrypto.swift",
        "",
    )
    broken_xcode = xcode_text.replace(
        "NotificationPreviewCrypto.swift in Sources",
        "NotificationPreviewCrypto.swift absent",
    )

    issues = audit.notification_service_membership_issues(broken_project, broken_xcode)
    assert any("NotificationPreviewCrypto.swift" in issue for issue in issues)


def test_apple_release_preflight_rejects_notification_embed_and_entitlement_drift() -> None:
    audit = load_module("audit_apple_release_preflight", ROOT / "scripts/audit_apple_release_preflight.py")
    project_text = (ROOT / "apple/project.yml").read_text(encoding="utf-8")
    xcode_text = (ROOT / "apple/OpenMates.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
    main_entitlements = (ROOT / "apple/OpenMates/Resources/OpenMatesPasskey.entitlements").read_text(encoding="utf-8")
    extension_entitlements = (ROOT / "apple/OpenMatesNotificationService/OpenMatesNotificationService.entitlements").read_text(encoding="utf-8")

    broken_xcode = xcode_text.replace(
        "OpenMatesNotificationService.appex in Embed Foundation Extensions",
        "OpenMatesNotificationService.appex absent",
    )
    membership_issues = audit.notification_service_membership_issues(project_text, broken_xcode)
    assert any("does not embed OpenMatesNotificationService" in issue for issue in membership_issues)

    main_issues = audit.missing_text_terms(
        "main entitlements",
        main_entitlements.replace("aps-environment", "removed-environment"),
        audit.REQUIRED_ENTITLEMENT_TERMS,
    )
    assert any("aps-environment" in issue for issue in main_issues)

    extension_issues = audit.missing_text_terms(
        "extension entitlements",
        extension_entitlements.replace("group.org.openmates.app.shared", "removed-app-group"),
        audit.REQUIRED_NOTIFICATION_ENTITLEMENT_TERMS,
    )
    assert any("shared App Group" in issue for issue in extension_issues)


def test_apple_release_preflight_rejects_push_print_logging() -> None:
    audit = load_module("audit_apple_release_preflight", ROOT / "scripts/audit_apple_release_preflight.py")

    issues = audit.push_logging_issues({
        ROOT / "apple/OpenMates/Sources/Core/Networking/PushNotificationManager.swift": 'print("[Push] Device token: \\(token)")',
    })

    assert any("forbidden full push token logging" in issue for issue in issues)


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


def test_figma_visual_evidence_warns_for_figma_claimed_ui_without_artifacts() -> None:
    audit = load_module("audit_figma_visual_evidence", ROOT / "scripts/audit_figma_visual_evidence.py")

    issues = audit.audit_paths(
        [ROOT / "frontend/packages/ui/src/components/tasks/TaskBoard.svelte"],
        added_lines=[("docs/plans/tasks/plan.yml", 10, "The UI should match the Figma task board.")],
        evidence_paths=[],
    )

    assert len(issues) == 1
    assert issues[0].blocking is True
    assert "reference PNGs" in issues[0].message


def test_figma_visual_evidence_ignores_unclaimed_ui_change() -> None:
    audit = load_module("audit_figma_visual_evidence", ROOT / "scripts/audit_figma_visual_evidence.py")

    issues = audit.audit_paths(
        [ROOT / "frontend/packages/ui/src/components/tasks/TaskBoard.svelte"],
        added_lines=[("frontend/packages/ui/src/components/tasks/TaskBoard.svelte", 10, "<div data-testid=\"task-board\">")],
        evidence_paths=[],
    )

    assert issues == []


def test_figma_visual_evidence_accepts_spec_artifact_review(tmp_path) -> None:
    audit = load_module("audit_figma_visual_evidence", ROOT / "scripts/audit_figma_visual_evidence.py")
    original_root = audit.REPO_ROOT
    audit.REPO_ROOT = tmp_path
    try:
        ui_path = tmp_path / "frontend/packages/ui/src/components/tasks/TaskBoard.svelte"
        spec_path = tmp_path / "docs/plans/tasks/plan.yml"
        ui_path.parent.mkdir(parents=True)
        spec_path.parent.mkdir(parents=True)
        ui_path.write_text("<div data-testid=\"task-board\"></div>\n", encoding="utf-8")
        spec_path.write_text(
            "verifications:\n  - id: V-FIGMA-ARTIFACT-REVIEW\n    kind: artifact_review\n    evidence: reference PNG, rendered screenshot, and accepted differences\n",
            encoding="utf-8",
        )
        artifact_path = tmp_path / "test-results/figma/tasks-review.md"
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_text("Reviewed reference PNG and rendered screenshot.\n", encoding="utf-8")

        issues = audit.audit_paths(
            [ui_path, spec_path],
            added_lines=[("docs/plans/tasks/plan.yml", 10, "The UI should match the Figma task board.")],
            evidence_paths=[artifact_path],
        )
    finally:
        audit.REPO_ROOT = original_root

    assert issues == []
