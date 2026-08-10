# backend/tests/test_test_run_summary_email_task.py
#
# Regression coverage for daily test-run summary email rendering inputs.
# The summary email includes raw Playwright/CLI stderr snippets, so terminal
# control bytes must be removed before MJML conversion. Otherwise a single
# noisy failure can prevent the whole nightly notification from rendering.

from pathlib import Path

from backend.core.api.app.tasks.email_tasks.test_run_summary_email_task import (
    _group_failed_tests_by_type,
    _sanitize_failure_groups,
    _sanitize_email_text,
)


def test_sanitize_email_text_removes_terminal_control_sequences() -> None:
    raw = "\x1b[31merror\x1b[0m\x08\r\x1b[JUsername: openmates@example.test"

    sanitized = _sanitize_email_text(raw)

    assert sanitized == "errorUsername: openmates@example.test"
    assert "\x1b" not in sanitized
    assert "\x08" not in sanitized
    assert "\r" not in sanitized


def test_group_failed_tests_by_type_keeps_core_suites_separate() -> None:
    groups = _group_failed_tests_by_type([
        {"suite": "pytest_unit", "name": "backend/tests/test_api.py::test_api"},
        {"suite": "playwright", "file": "chat-flow.spec.ts", "name": "chat flow"},
        {"suite": "apple_remote", "name": "test-ios"},
        {"suite": "cli", "name": "openmates chat smoke"},
        {"suite": "custom", "name": "unknown failure"},
    ])

    assert [(group["label"], group["count"]) for group in groups] == [
        ("pytest", 1),
        ("*.spec.ts", 1),
        ("Apple Remote", 1),
        ("CLI", 1),
        ("Other", 1),
    ]


def test_sanitize_failure_groups_preserves_structure_without_html() -> None:
    groups = _sanitize_failure_groups([
        {
            "title": "Playwright <2>",
            "description": "FAIL Core chat: 2 files\n- <chat-flow.spec.ts>",
        }
    ])

    assert groups == [{
        "title": "Playwright &lt;2&gt;",
        "description": "FAIL Core chat: 2 files\n- &lt;chat-flow.spec.ts&gt;",
    }]


def test_sanitize_failure_groups_bounds_internal_callers() -> None:
    groups = _sanitize_failure_groups([
        {"title": f"Group {index}", "description": "x" * 5000}
        for index in range(20)
    ])

    assert len(groups) == 10
    assert all(len(group["description"]) <= 4020 for group in groups)


def test_template_preserves_grouped_and_legacy_contracts() -> None:
    project_root = Path(__file__).resolve().parents[2]
    template = (project_root / "backend/core/api/templates/email/test_run_summary.mjml").read_text()

    assert "{% if failure_groups %}" in template
    assert "{% elif failed_tests %}" in template
