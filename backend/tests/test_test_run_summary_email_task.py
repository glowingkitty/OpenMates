# backend/tests/test_test_run_summary_email_task.py
#
# Regression coverage for daily test-run summary email rendering inputs.
# The summary email includes raw Playwright/CLI stderr snippets, so terminal
# control bytes must be removed before MJML conversion. Otherwise a single
# noisy failure can prevent the whole nightly notification from rendering.

from backend.core.api.app.tasks.email_tasks.test_run_summary_email_task import (
    _group_failed_tests_by_type,
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
