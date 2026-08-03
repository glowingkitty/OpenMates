#!/usr/bin/env python3
"""Regression coverage for Apple app-icon gradient references.

Reference-based web gradients are not emitted as standalone Swift symbols.
Apple app IDs using the primary gradient must therefore select `.primary`
instead of a nonexistent generated `LinearGradient.app*` property.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP_ICON_VIEW = ROOT / "apple" / "OpenMates" / "Sources" / "Shared" / "Components" / "AppIconView.swift"


def test_reference_based_task_gradients_use_primary_swift_token() -> None:
    source = APP_ICON_VIEW.read_text(encoding="utf-8")

    assert 'case "tasks": return .primary' in source
    assert 'case "workflows": return .primary' in source
    assert ".appTasks" not in source
    assert ".appWorkflows" not in source
