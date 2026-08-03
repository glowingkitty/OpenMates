#!/usr/bin/env python3
"""
Regression tests for nightly Discord test summaries.

The summary must show where failures are concentrated before listing the
affected test files. Error causes and stack traces remain in the full reports
rather than being posted in the channel.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_TESTS_PATH = PROJECT_ROOT / "scripts" / "run_tests.py"


def load_run_tests_module():
    spec = importlib.util.spec_from_file_location("openmates_run_tests_discord", RUN_TESTS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_discord_failure_sections_show_distribution_and_files_without_causes():
    run_tests = load_run_tests_module()
    suites = {
        "pytest_unit": {
            "tests": [
                {
                    "name": "tests/test_apps_api.py::test_first_case",
                    "status": "failed",
                    "error": "KeyError: private implementation detail",
                },
                {
                    "name": "tests/test_apps_api.py::test_second_case",
                    "status": "failed",
                    "error": "AssertionError: another cause",
                },
                {
                    "name": "tests/test_other.py::test_green",
                    "status": "passed",
                },
            ]
        },
        "playwright": {
            "tests": [
                {"file": "chat-flow.spec.ts", "status": "failed", "error": "Timeout"},
                {"file": "settings.spec.ts", "status": "timeout", "error": "Timeout"},
                {"file": "auth.spec.ts", "status": "failed", "error": "Expected page"},
            ]
        },
        "vitest": {"tests": [{"name": "green unit", "status": "passed"}]},
    }

    sections = run_tests._build_discord_failure_sections(suites)

    assert sections == [
        "**Failure distribution:**",
        "• **Playwright:** 3 (60%) across **3** files",
        "• **Pytest unit:** 2 (40%) across **1** file",
        "",
        "**Failed test files:**",
        "**Playwright**",
        "• `auth.spec.ts`",
        "• `chat-flow.spec.ts`",
        "• `settings.spec.ts`",
        "**Pytest unit**",
        "• `tests/test_apps_api.py` — 2 failures",
    ]
    rendered = "\n".join(sections)
    assert "KeyError" not in rendered
    assert "AssertionError" not in rendered
    assert "Expected page" not in rendered


def test_discord_summary_payload_uses_failure_sections(monkeypatch):
    run_tests = load_run_tests_module()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b""

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(run_tests.urllib.request, "urlopen", fake_urlopen)
    result = run_tests.RunResult(
        run_id="2026-08-03T03:00:02Z",
        git_sha="79b5ef7b5",
        git_branch="dev",
        environment="development",
        duration_seconds=15438.5,
        summary={
            "total": 3,
            "passed": 1,
            "failed": 2,
            "dispatch_error": 0,
            "timeout": 0,
            "result_unknown": 0,
            "skipped": 0,
            "not_started": 0,
        },
        suites={
            "pytest_unit": {
                "tests": [
                    {
                        "name": "tests/test_apps_api.py::test_first_case",
                        "status": "failed",
                        "error": "KeyError: must not be sent",
                    },
                    {
                        "name": "tests/test_apps_api.py::test_second_case",
                        "status": "failed",
                        "error": "AssertionError: must not be sent",
                    },
                    {"name": "tests/test_other.py::test_green", "status": "passed"},
                ]
            }
        },
    )

    service = run_tests.NotificationService.__new__(run_tests.NotificationService)
    service._send_summary_to_discord(result, webhook_url="https://example.invalid/webhook")

    description = captured["payload"]["embeds"][0]["description"]
    assert "**Failure distribution:**" in description
    assert "**Pytest unit:** 2 (100%) across **1** file" in description
    assert "• `tests/test_apps_api.py` — 2 failures" in description
    assert "KeyError" not in description
    assert "AssertionError" not in description
    assert "```" not in description
    assert captured["timeout"] == 30


def test_vitest_artifact_records_the_failed_test_file(tmp_path):
    run_tests = load_run_tests_module()
    artifact = tmp_path / "vitest-results.json"
    artifact.write_text(
        json.dumps(
            {
                "testResults": [
                    {
                        "name": "frontend/packages/ui/src/chat/chat.test.ts",
                        "assertionResults": [
                            {
                                "fullName": "chat renders a message",
                                "status": "failed",
                                "duration": 12,
                                "failureMessages": ["cause omitted from Discord"],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    tests = run_tests.TestOrchestrator._parse_unit_test_artifact(tmp_path, "vitest")

    assert tests[0]["file"] == "frontend/packages/ui/src/chat/chat.test.ts"


def test_discord_description_truncates_at_file_boundaries_with_omission_count():
    run_tests = load_run_tests_module()
    lines = ["Summary", "", "**Failed test files:**", "**Playwright**"]
    lines.extend(f"• `very-long-test-file-{index:03d}.spec.ts`" for index in range(200))

    description = run_tests._fit_discord_description(lines)

    assert len(description) <= run_tests.DISCORD_DESCRIPTION_MAX_CHARS
    assert "more failed files; see the full test report." in description
    assert not description.splitlines()[-2].endswith("...")
