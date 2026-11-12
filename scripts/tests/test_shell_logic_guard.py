"""Tests for scripts/shell_logic_guard.py (client-core plan TASK-11)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import shell_logic_guard  # noqa: E402  (scripts/ is on sys.path only after the insert above)
from shell_logic_guard import check, load_capabilities  # noqa: E402

CAPS = {
    "embeds": {"web": {"status": "rust-default"}, "apple": {"status": "swift-only"}},
    "old": {"web": {"status": "ts-only"}, "apple": {"status": "swift-only"}},
}
SVC = ("M", "frontend/packages/ui/src/services/foo.ts")
SWIFT = ("M", "apple/OpenMatesShared/Foo.swift")


# contract-test: tooling
def test_guarded_edit_without_justification_refused():
    for change in (SVC, SWIFT, ("M", "apple/OpenMates/Sources/Core/X.swift")):
        errors, _ = check([change], "feat: x", CAPS)
        assert errors


# contract-test: tooling
def test_valid_shell_only_line_ok():
    assert check([SVC], "t\n\nshell-only: ui button state", CAPS) == ([], [])


# contract-test: tooling
def test_rust_change_in_diff_ok():
    for core in ("packages/openmates-rust/src/a.rs", "packages/openmates-session-bindings/x.rs"):
        assert check([SVC, ("M", core)], "x", CAPS) == ([], [])


# contract-test: tooling
def test_pure_deletion_ok():
    assert check([("D", SVC[1])], "x", CAPS) == ([], [])


# contract-test: tooling
def test_exempt_paths_not_guarded():
    changes = [
        ("M", "frontend/packages/ui/src/services/rustCore/units/a.ts"),
        ("M", "frontend/packages/ui/src/services/__tests__/a.test.ts"),
        ("M", "frontend/packages/ui/src/services/sub/__tests__/a.test.ts"),
        ("M", "frontend/apps/web_app/src/x.ts"),
    ]
    assert check(changes, "x", CAPS) == ([], [])


# contract-test: tooling
def test_bad_reason_refused():
    errors, _ = check([SVC], "shell-only: because", CAPS)
    assert errors and "not allowed" in errors[0]


# contract-test: tooling
def test_bugfix_requires_known_capability():
    assert check([SVC], "shell-only: bugfix-in-frozen-code", CAPS)[0]
    errors, _ = check([SVC], "shell-only: bugfix-in-frozen-code nope", CAPS)
    assert errors and "Unknown capability" in errors[0]


# contract-test: tooling
def test_bugfix_reminder_for_rust_twin_or_later():
    errors, warnings = check([SVC], "shell-only: bugfix-in-frozen-code embeds", CAPS)
    assert not errors and len(warnings) == 1 and "web" in warnings[0]
    assert check([SVC], "shell-only: bugfix-in-frozen-code old", CAPS) == ([], [])


# contract-test: tooling
def test_real_capabilities_include_recent_ids():
    caps = load_capabilities()
    assert {"embeds", "drafts"} <= set(caps)


# contract-test: tooling
def test_guard_is_warn_only_during_rollout_window():
    from datetime import date
    assert not shell_logic_guard.is_blocking(date(2026, 11, 25))
    assert shell_logic_guard.is_blocking(shell_logic_guard.BLOCKING_FROM)
