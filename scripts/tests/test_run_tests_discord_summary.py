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


def test_discord_failure_embeds_group_files_by_suite_and_product_area():
    run_tests = load_run_tests_module()
    suites = {
        "pytest_unit": {
            "tests": [
                {
                    "name": "tests/test_settings_account_delete_force_logout.py::test_delete_account",
                    "status": "failed",
                    "error": "KeyError: private implementation detail",
                },
                {
                    "name": "tests/test_billing_routes.py::test_invoice",
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
                {
                    "file": "signup-flow-stripe-managed.spec.ts",
                    "status": "failed",
                    "error": "Expected page",
                },
            ]
        },
        "vitest": {"tests": [{"name": "green unit", "status": "passed"}]},
    }

    embeds = run_tests._build_discord_failure_embeds(suites, color=0xEF4444)

    assert [embed["title"] for embed in embeds] == [
        "Playwright · 3 failures · 3 files",
        "Pytest unit · 2 failures · 2 files",
    ]
    playwright = embeds[0]["description"]
    assert "🔴 Billing & payments: **1** failed file" in playwright
    assert "🔴 Signup & authentication: **1** failed file" in playwright
    assert "🔴 Core chat: **1** failed file" in playwright
    assert "**Signup & authentication · 1 failure · 1 file**" in playwright
    assert "• `signup-flow-stripe-managed.spec.ts`" in playwright
    assert "**Core chat · 1 failure · 1 file**" in playwright
    assert "• `chat-flow.spec.ts`" in playwright
    assert "**Settings & account · 1 failure · 1 file**" in playwright
    assert "• `settings.spec.ts`" in playwright

    pytest = embeds[1]["description"]
    assert "🔴 Billing & payments: **1** failed file" in pytest
    assert "🔴 Signup & authentication: **1** failed file" in pytest
    assert "🟢 Core chat: **0** failed files" in pytest
    assert "• `tests/test_billing_routes.py`" in pytest
    assert "• `tests/test_settings_account_delete_force_logout.py`" in pytest

    rendered = "\n".join(embed["description"] for embed in embeds)
    assert "KeyError" not in rendered
    assert "AssertionError" not in rendered
    assert "Expected page" not in rendered


def test_discord_summary_payload_uses_grouped_failure_embeds(monkeypatch):
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

    embeds = captured["payload"]["embeds"]
    assert len(embeds) == 2
    assert embeds[0]["title"] == "❌ development nightly — 2 failed"
    assert embeds[1]["title"] == "Pytest unit · 2 failures · 1 file"
    details = embeds[1]["description"]
    assert "🔴 Signup & authentication: **0** failed files" not in details
    assert "🟢 Signup & authentication: **0** failed files" in details
    assert "• `tests/test_apps_api.py` — 2 failures" in details
    assert "KeyError" not in details
    assert "AssertionError" not in details
    assert "```" not in details
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


def test_product_area_matching_avoids_generic_message_false_positive():
    run_tests = load_run_tests_module()

    assert run_tests._primary_product_area("tests/test_validation.py shows error message") == (
        run_tests.DEFAULT_PRODUCT_AREA
    )
    assert run_tests._primary_product_area("frontend/chat/composer.test.ts") == "Core chat"


def test_discord_failure_embeds_respect_message_embed_limit():
    run_tests = load_run_tests_module()
    embeds = [
        {"title": f"Suite {index}", "description": "failure", "color": 0xEF4444}
        for index in range(12)
    ]

    limited = run_tests._limit_discord_failure_embeds(embeds, color=0xEF4444)

    assert len(limited) == run_tests.DISCORD_MAX_EMBEDS - 1
    assert limited[-1]["title"] == "4 more failing suites"
    assert "• Suite 8" in limited[-1]["description"]
    assert "• Suite 11" in limited[-1]["description"]


def test_discord_failure_embeds_respect_aggregate_character_limit():
    run_tests = load_run_tests_module()
    critical = [
        "**Critical product areas**",
        "🔴 Billing & payments: **1** failed file",
        "🟢 Signup & authentication: **0** failed files",
        "🟢 Core chat: **0** failed files",
        "",
        "**Files by product area**",
    ]
    details = []
    for suite_index in range(4):
        lines = [*critical, "**Billing & payments · 100 failures · 100 files**"]
        lines.extend(
            f"• `suite-{suite_index}-very-long-failed-file-{file_index:03d}.spec.ts`"
            for file_index in range(100)
        )
        details.append({
            "title": f"Suite {suite_index} · 100 failures · 100 files",
            "description": run_tests._fit_discord_description(lines),
            "color": 0xEF4444,
        })
    summary = {"title": "Nightly summary", "description": "93 failed", "color": 0xEF4444}

    fitted = run_tests._fit_discord_embed_total([summary, *details])

    total_chars = sum(
        len(embed["title"]) + len(embed["description"])
        for embed in fitted
    )
    assert total_chars <= run_tests.DISCORD_EMBED_TOTAL_MAX_CHARS
    for embed in fitted[1:]:
        assert "**Critical product areas**" in embed["description"]
        assert "Billing & payments" in embed["description"]
