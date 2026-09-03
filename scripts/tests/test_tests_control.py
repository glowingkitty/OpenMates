#!/usr/bin/env python3
"""
Regression tests for the unified test control plane.

These tests exercise pure filesystem/state behavior only. They do not dispatch
GitHub Actions and do not run Playwright or Vitest locally; the control script
is responsible for wrapping those remote workflows in production use.
"""

from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from pathlib import Path

import pytest

# contract-test-file: tooling


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_CONTROL_PATH = PROJECT_ROOT / "scripts" / "tests.py"


def load_tests_control(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("openmates_tests_control", TESTS_CONTROL_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    results_dir = tmp_path / "test-results"
    monkeypatch.setattr(module, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(module, "PROOF_SOURCE_DIR", results_dir / "proof-video-sources")
    monkeypatch.setattr(module, "PROOF_SOURCE_ARTIFACTS_DIR", results_dir / "proof-video-source-artifacts")
    monkeypatch.setattr(module, "STATE_FILE", results_dir / "tests-state.json")
    monkeypatch.setattr(module, "HISTORY_FILE", results_dir / "tests-history.jsonl")
    monkeypatch.setattr(module, "LEASES_FILE", results_dir / "failed-test-leases.json")
    monkeypatch.setattr(module, "TRIAGE_FILE", results_dir / "test-failure-triage.json")
    monkeypatch.setattr(module, "TEST_FILE_INDEX_FILE", results_dir / "test-file-index.json")
    monkeypatch.setattr(module, "RESPONSE_MEDIA_LATEST_FILE", results_dir / "response-media-latest.json")
    monkeypatch.setattr(module, "RUNS_DIR", results_dir / "runs")
    monkeypatch.setattr(module, "LEASE_LOCK_FILE", tmp_path / "leases.lock")
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "SPEC_DIR", tmp_path / "frontend" / "apps" / "web_app" / "tests")
    monkeypatch.setattr(module, "TEST_STORE", module.InMemoryTestControlStore())
    return module


def sample_run() -> dict:
    return {
        "run_id": "2026-06-19T03:00:02Z",
        "git_sha": "abc123def",
        "git_branch": "dev",
        "environment": "development",
        "duration_seconds": 42.0,
        "flags": {"suite": "all"},
        "summary": {"total": 3, "passed": 1, "failed": 2, "skipped": 0},
        "suites": {
            "playwright": {
                "status": "failed",
                "duration_seconds": 40,
                "tests": [
                    {
                        "name": "chat-flow.spec.ts",
                        "file": "chat-flow.spec.ts",
                        "status": "failed",
                        "error": "Locator: locator('[data-action=\"send-message\"]') Expected: visible Error: element(s) not found",
                        "run_id": 123,
                    },
                    {
                        "name": "account-recovery-flow.spec.ts",
                        "file": "account-recovery-flow.spec.ts",
                        "status": "failed",
                        "error": "Reserved Playwright account slot 14 failed or was not configured in preflight",
                        "run_id": 124,
                    },
                    {
                        "name": "settings-flow.spec.ts",
                        "file": "settings-flow.spec.ts",
                        "status": "passed",
                    },
                ],
            }
        },
    }


def test_record_run_updates_state_history_and_run_archive(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    tests_control.record_run_result(sample_run())

    state = tests_control.load_state()
    assert state["latest_run_id"] == "2026-06-19T03:00:02Z"
    assert state["summary"]["failed"] == 2
    assert state["tests"]["playwright::chat-flow.spec.ts"]["status"] == "failed"
    assert state["tests"]["playwright::settings-flow.spec.ts"]["status"] == "passed"

    history = tests_control.load_history_events()
    assert len(history) == 3
    assert any(event["event"] == "failed" and event["test"] == "chat-flow.spec.ts" for event in history)
    assert not tests_control.STATE_FILE.exists()
    assert not (tests_control.RUNS_DIR / "20260619T030002Z.json").is_file()

    store = tests_control.get_store()
    assert "playwright::chat-flow.spec.ts" in store.test_catalog
    assert "2026-06-19T03:00:02Z" in store.test_runs
    assert any(result["test_key"] == "playwright::chat-flow.spec.ts" for result in store.test_results.values())


def test_record_run_preserves_passing_flake_metadata(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    run = sample_run()
    run["summary"] = {"total": 1, "passed": 1, "failed": 0, "skipped": 0}
    run["suites"] = {"playwright": {"status": "passed", "tests": [{
        "name": "chat-flow.spec.ts", "file": "chat-flow.spec.ts", "status": "passed",
        "flaky": True, "retries": 1, "attempt_statuses": ["failed", "passed"],
    }]}}

    tests_control.record_run_result(run)

    record = tests_control.load_state()["tests"]["playwright::chat-flow.spec.ts"]
    assert record["status"] == "passed"
    assert record["flaky"] is True
    assert record["retries"] == 1
    assert record["attempt_statuses"] == ["failed", "passed"]


def test_record_run_redacts_sensitive_failure_text_before_persistence(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result({
        "run_id": "run-sensitive",
        "suites": {"playwright": {"status": "failed", "tests": [{
            "name": "private-flow.spec.ts",
            "file": "private-flow.spec.ts",
            "status": "failed",
            "error": "user@example.com Bearer secret-token cookie=session-secret https://example.test/share#key=private-key",
        }]}},
    })

    state_text = json.dumps(tests_control.load_state())
    run_text = json.dumps(tests_control.get_store().get_test_run("run-sensitive"))

    for secret in ("user@example.com", "secret-token", "session-secret", "private-key"):
        assert secret not in state_text
        assert secret not in run_text


def test_failed_prerequisite_records_one_parent_and_visible_blocked_dependants(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    run = {
        "run_id": "run-worker-down",
        "summary": {"total": 2, "passed": 0, "failed": 0, "skipped": 2},
        "prerequisites": [{
            "id": "task_worker",
            "status": "failed",
            "lane": "live_probe",
            "error": "Task worker health check failed",
            "dependant_test_keys": [
                "playwright::reminder-email.spec.ts",
                "playwright::notifications-flow.spec.ts",
            ],
        }],
        "suites": {"playwright": {"status": "skipped", "tests": [
            {"name": "reminder-email.spec.ts", "file": "reminder-email.spec.ts", "status": "skipped"},
            {"name": "notifications-flow.spec.ts", "file": "notifications-flow.spec.ts", "status": "skipped"},
        ]}},
    }

    state = tests_control.record_run_result(run)
    triage = tests_control.build_triage()

    parent = state["tests"]["prerequisite::task_worker"]
    assert parent["status"] == "failed"
    assert parent["lane"] == "live_probe"
    for key in run["prerequisites"][0]["dependant_test_keys"]:
        assert state["tests"][key]["status"] == "blocked_by_parent"
        assert state["tests"][key]["parent_incident_key"] == parent["key"]
    assert state["summary"]["failed"] == 1
    assert state["summary"]["blocked_by_parent"] == 2
    assert [entry["key"] for entry in triage["entries"]] == ["prerequisite::task_worker"]


def test_status_summary_separates_deterministic_and_live_probe_health(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result({
        "run_id": "run-lanes",
        "suites": {
            "pytest_unit": {"status": "passed", "lane": "deterministic", "tests": [
                {"name": "tests/test_math.py::test_add", "status": "passed"},
            ]},
            "api_live": {"status": "failed", "lane": "live_probe", "tests": [
                {"name": "gmail_delivery", "status": "failed", "error": "Gmail probe failed"},
            ]},
        },
    })

    summary = tests_control.load_state()["summary"]

    assert summary["lanes"]["deterministic"]["passed"] == 1
    assert summary["lanes"]["deterministic"]["failed"] == 0
    assert summary["lanes"]["live_probe"]["failed"] == 1
    assert summary["global_zero_complete"] is False


# contract-test: infrastructure
def test_import_normalizes_raw_playwright_json_report(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    raw_report = {
        "config": {
            "metadata": {
                "gitCommit": {"hash": "abc123", "branch": "HEAD"},
            },
        },
        "suites": [
            {
                "title": "file-attachment-flow.spec.ts",
                "file": "file-attachment-flow.spec.ts",
                "specs": [
                    {
                        "title": "passes first",
                        "file": "file-attachment-flow.spec.ts",
                        "tests": [{"results": [{"status": "passed", "duration": 1200, "startTime": "2026-07-28T21:16:13.746Z"}]}],
                    },
                    {
                        "title": "fails after retry",
                        "file": "file-attachment-flow.spec.ts",
                        "tests": [{
                            "results": [
                                {"status": "failed", "duration": 2000, "retry": 0},
                                {
                                    "status": "failed",
                                    "duration": 3000,
                                    "retry": 1,
                                    "error": {"message": "Error: Login email lookup did not store the email salt."},
                                },
                            ],
                        }],
                    },
                ],
            },
        ],
        "errors": [],
    }

    normalized = tests_control.normalize_import_run_data(
        raw_report,
        tmp_path / "playwright.json",
        external_run_id="30399876387",
        workflow="Playwright: Single Spec",
    )

    test = normalized["suites"]["playwright"]["tests"][0]
    assert normalized["run_id"] == "30399876387"
    assert normalized["summary"] == {
        "total": 1,
        "passed": 0,
        "failed": 1,
        "dispatch_error": 0,
        "timeout": 0,
        "result_unknown": 0,
        "infrastructure_incident": 0,
        "skipped": 0,
        "not_started": 0,
    }
    assert test["file"] == "file-attachment-flow.spec.ts"
    assert test["status"] == "failed"
    assert test["retries"] == 1
    assert test["attempt_statuses"] == ["passed", "failed", "failed"]
    assert test["github_run_url"] == "https://github.com/glowingkitty/OpenMates/actions/runs/30399876387"
    assert "Login email lookup" in test["error"]


def test_triage_ranks_account_and_chat_failures_with_linked_files(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    spec_dir = tests_control.SPEC_DIR
    spec_dir.mkdir(parents=True)
    (spec_dir / "chat-flow.spec.ts").write_text("import { test } from '@playwright/test';\n", encoding="utf-8")

    component = tmp_path / "frontend" / "packages" / "ui" / "src" / "components" / "enter_message" / "MessageInput.svelte"
    component.parent.mkdir(parents=True)
    component.write_text('<button data-action="send-message">Send</button>\n', encoding="utf-8")

    tests_control.record_run_result(sample_run())
    triage = tests_control.build_triage()

    assert triage["summary"]["failed"] == 2
    entries = triage["entries"]
    assert entries[0]["category"] == "account_preflight"
    assert entries[1]["category"] == "chat_send_receive"
    assert "frontend/apps/web_app/tests/chat-flow.spec.ts" in entries[1]["linked_files"]
    assert "frontend/packages/ui/src/components/enter_message/MessageInput.svelte" in entries[1]["linked_files"]


def test_triage_groups_correlated_dependency_failures_before_error_signatures(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    run = {
        "run_id": "run-embed-delivery",
        "correlations": [{
            "id": "embed-delivery",
            "category": "embed_delivery",
            "test_keys": [
                "playwright::skill-music.spec.ts",
                "playwright::skill-images.spec.ts",
            ],
            "evidence": ["websocket_disconnect", "embed_persistence_failed"],
        }],
        "suites": {"playwright": {"status": "failed", "tests": [
            {
                "name": "skill-music.spec.ts",
                "file": "skill-music.spec.ts",
                "status": "failed",
                "error": "Locator: getByTestId('music-player') Expected: visible",
            },
            {
                "name": "skill-images.spec.ts",
                "file": "skill-images.spec.ts",
                "status": "failed",
                "error": "WebSocket disconnected before the parent embed persisted",
            },
        ]}},
    }

    tests_control.record_run_result(run)
    triage = tests_control.build_triage()

    assert {entry["category"] for entry in triage["entries"]} == {"embed_delivery"}
    assert {entry["group_id"] for entry in triage["entries"]} == {"dependency-embed-delivery"}
    assert triage["groups"][0]["count"] == 2
    assert triage["groups"][0]["correlation_evidence"] == [
        "embed_persistence_failed",
        "websocket_disconnect",
    ]


def test_classification_avoids_authenticity_false_positive(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    assert tests_control.classify_failure({
        "suite": "playwright",
        "test": "demo-chat-embeds.spec.ts",
        "error": "image-authenticity-badge still contains {percentage}",
    }) == "embed_rendering"
    assert tests_control.classify_failure({
        "suite": "cli",
        "test": "cli-integration/code-docs/apps-code-get-docs",
        "error": "Skill execution failed: Not authenticated: provide a session cookie or API key",
    }) == "cli_auth"


def test_api_key_device_approval_is_environment_blocked(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    assert tests_control.classify_failure({
        "suite": "playwright",
        "test": "cli-skills-pdf.spec.ts",
        "error": "Locator: getByTestId('message-assistant')",
        "debug_output_summary": "A new device attempted to use your API key. Please review and approve it in Developer Settings.",
    }) == "environment_blocked"


def test_run_args_consume_expected_commit_before_forwarding(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    forwarded, expected = tests_control.parse_control_run_args([
        "--spec",
        "cli-skills-pdf.spec.ts",
        "--expected-commit",
        "abc123",
        "--no-fail-fast",
    ])

    assert forwarded == ["--spec", "cli-skills-pdf.spec.ts", "--no-fail-fast"]
    assert expected == "abc123"


def test_run_options_consume_gate_and_lease_flags(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    options = tests_control.parse_control_run_options([
        "--spec",
        "chat-flow.spec.ts",
        "--gate-deploy",
        "--require-exact-commit",
        "--lease-required",
        "--lease-id",
        "lease-chat-123",
        "--expected-commit=abc123",
    ])

    assert options.forwarded_args == ["--spec", "chat-flow.spec.ts"]
    assert options.gate_deploy is True
    assert options.require_exact_commit is True
    assert options.lease_required is True
    assert options.lease_id == "lease-chat-123"
    assert options.expected_commit == "abc123"


def test_run_options_forward_proof_video_profile(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    options = tests_control.parse_control_run_options([
        "--spec",
        "audio-recording.spec.ts",
        "--proof-video-profile",
        "web-laptop",
        "--expected-commit=abc123",
    ])

    assert options.forwarded_args == ["--spec", "audio-recording.spec.ts", "--proof-video-profile", "web-laptop"]
    assert options.proof_video_profile == "web-laptop"
    assert options.expected_commit == "abc123"
    assert tests_control.playwright_response_media_run_type(options) == "spec-ts-web-laptop"


def test_proof_video_profile_is_part_of_dispatch_identity(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    seen = []

    class FakeDispatchStore(tests_control.ControlPlaneTestControlStore):
        def __init__(self):
            pass

        def request_dispatch(self, **kwargs):
            seen.append(kwargs)
            return {"dispatch_key": f"dispatch-{len(seen)}", "status": "queued"}, False

        def record_dispatch_canary(self, dispatch_key, service, *, healthy):
            return {"dispatch_key": dispatch_key}

        def update_dispatch(self, dispatch_key, status, reason=None):
            return {"dispatch_key": dispatch_key, "status": status}

    monkeypatch.setattr(tests_control, "TEST_STORE", FakeDispatchStore())
    laptop = tests_control.parse_control_run_options([
        "--spec", "embeds-map-view.spec.ts", "--proof-video-profile", "web-laptop",
    ])
    phone = tests_control.parse_control_run_options([
        "--spec", "embeds-map-view.spec.ts", "--proof-video-profile", "web-phone",
    ])

    tests_control.begin_control_plane_dispatch(laptop, subject_commit="abc123", selected_test_keys=[], resources=set())
    tests_control.begin_control_plane_dispatch(phone, subject_commit="abc123", selected_test_keys=[], resources=set())

    assert [call["profile"] for call in seen] == ["playwright:web-laptop", "playwright:web-phone"]


def test_account_provisioning_slot_is_part_of_dispatch_identity(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    seen = []

    class FakeDispatchStore(tests_control.ControlPlaneTestControlStore):
        def __init__(self):
            pass

        def request_dispatch(self, **kwargs):
            seen.append(kwargs)
            return {"dispatch_key": f"dispatch-{len(seen)}", "status": "queued"}, False

        def update_dispatch(self, dispatch_key, status, reason=None):
            return {"dispatch_key": dispatch_key, "status": status}

    monkeypatch.setattr(tests_control, "TEST_STORE", FakeDispatchStore())
    slot_15 = tests_control.parse_control_run_options([
        "--spec", "cli-provision-auth-accounts.spec.ts", "--create-account-slot", "15",
    ])
    slot_19 = tests_control.parse_control_run_options([
        "--spec", "cli-provision-auth-accounts.spec.ts", "--create-account-slot", "19",
    ])

    tests_control.begin_control_plane_dispatch(
        slot_15,
        subject_commit="abc123",
        selected_test_keys=[],
        resources=set(),
        selected_account=2,
    )
    tests_control.begin_control_plane_dispatch(
        slot_19,
        subject_commit="abc123",
        selected_test_keys=[],
        resources=set(),
        selected_account=3,
    )

    assert [call["profile"] for call in seen] == [
        "playwright:create-account-slot-15",
        "playwright:create-account-slot-19",
    ]
    assert [call["account"] for call in seen] == ["2", "3"]


def test_force_reopens_only_reused_proof_video_dispatch(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    updates = []

    class FakeDispatchStore(tests_control.ControlPlaneTestControlStore):
        def __init__(self):
            pass

        def request_dispatch(self, **kwargs):
            return {"dispatch_key": "dispatch-proof", "status": "succeeded"}, True

        def record_dispatch_canary(self, dispatch_key, service, *, healthy):
            return {"dispatch_key": dispatch_key}

        def update_dispatch(self, dispatch_key, status, reason=None):
            updates.append((dispatch_key, status))
            return {"dispatch_key": dispatch_key, "status": status}

    monkeypatch.setattr(tests_control, "TEST_STORE", FakeDispatchStore())
    options = tests_control.parse_control_run_options([
        "--spec", "embeds-map-view.spec.ts", "--proof-video-profile", "web-phone", "--force",
    ])

    _, dispatch_key, reused = tests_control.begin_control_plane_dispatch(
        options,
        subject_commit="abc123",
        selected_test_keys=[],
        resources=set(),
    )

    assert dispatch_key == "dispatch-proof"
    assert reused is False
    assert updates == [("dispatch-proof", "running")]


def test_playwright_proof_video_size_also_sets_viewport() -> None:
    config = (PROJECT_ROOT / "frontend" / "apps" / "web_app" / "playwright.config.ts").read_text(encoding="utf-8")

    assert "const videoSize" in config
    assert "viewport: videoSize" in config


def test_run_options_consume_detach_before_forwarding(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    options = tests_control.parse_control_run_options([
        "--spec",
        "chat-flow.spec.ts",
        "--detach",
        "--expected-commit",
        "abc123",
    ])

    assert options.forwarded_args == ["--spec", "chat-flow.spec.ts"]
    assert options.detach is True
    assert options.expected_commit == "abc123"


def test_detached_run_reinvokes_control_wrapper_without_detach(tmp_path, monkeypatch, capsys):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    popen_calls = []

    class FakeProcess:
        pid = 4242

    def fake_popen(command, **kwargs):
        popen_calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tests_control.subprocess, "Popen", fake_popen)

    result = tests_control.command_run_detached([
        "--spec",
        "chat-flow.spec.ts",
        "--detach",
        "--expected-commit",
        "abc123",
    ])

    assert result == 0
    command, kwargs = popen_calls[0]
    assert command[:3] == [sys.executable, str(TESTS_CONTROL_PATH), "run"]
    assert "--detach" not in command
    assert "--expected-commit" in command
    assert kwargs["cwd"] == tmp_path
    assert kwargs["start_new_session"] is True
    assert (tmp_path / "test-results" / "runs").is_dir()
    assert "Detached test run started" in capsys.readouterr().out


def test_subject_commit_accepts_current_integrated_dev_after_session_deploy(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    monkeypatch.setattr(tests_control, "current_git_sha", lambda: "old-worktree-commit")
    monkeypatch.setattr(tests_control, "integrated_dev_sha", lambda: "deployed-commit-123")

    assert tests_control.resolve_test_subject_commit("deployed-commit") == "deployed-commit-123"


def test_subject_commit_accepts_ancestor_when_requested_spec_inputs_unchanged(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    expected = "a" * 40
    current_dev = "b" * 40
    spec_dir = tests_control.SPEC_DIR
    spec_dir.mkdir(parents=True)
    (spec_dir / "shared-chat-embed-assets.spec.ts").write_text(
        "const helper = require('./helpers/chat-test-helpers');\n"
        "await page.getByTestId('shared-chat-badge');\n",
        encoding="utf-8",
    )
    (spec_dir / "helpers").mkdir()
    (spec_dir / "helpers" / "chat-test-helpers.ts").write_text("export {};\n", encoding="utf-8")
    monkeypatch.setattr(tests_control, "current_git_sha", lambda: "c" * 40)
    monkeypatch.setattr(tests_control, "integrated_dev_sha", lambda: current_dev)
    monkeypatch.setattr(
        tests_control,
        "git_is_ancestor",
        lambda ancestor, descendant: (ancestor, descendant) == (expected, current_dev),
    )
    monkeypatch.setattr(
        tests_control,
        "git_changed_files_between",
        lambda _base, _head: [
            "scripts/tests.py",
            "docs/releases/daily/2026-08-15.md",
            "frontend/packages/ui/src/stores/activeChatStore.ts",
        ],
    )

    assert tests_control.resolve_test_subject_commit(
        expected,
        ["--spec", "shared-chat-embed-assets.spec.ts"],
    ) == current_dev


def test_subject_commit_exact_mode_rejects_newer_integrated_dev(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    expected = "a" * 40
    current_dev = "b" * 40
    monkeypatch.setattr(tests_control, "current_git_sha", lambda: "c" * 40)
    monkeypatch.setattr(tests_control, "integrated_dev_sha", lambda: current_dev)

    with pytest.raises(RuntimeError, match="exact-commit verification"):
        tests_control.resolve_test_subject_commit(
            expected,
            ["--spec", "chat-flow.spec.ts"],
            require_exact=True,
        )


def test_subject_commit_rejects_ancestor_when_requested_spec_changed(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    expected = "a" * 40
    current_dev = "b" * 40
    monkeypatch.setattr(tests_control, "current_git_sha", lambda: "c" * 40)
    monkeypatch.setattr(tests_control, "integrated_dev_sha", lambda: current_dev)
    monkeypatch.setattr(
        tests_control,
        "git_is_ancestor",
        lambda ancestor, descendant: (ancestor, descendant) == (expected, current_dev),
    )
    monkeypatch.setattr(
        tests_control,
        "git_changed_files_between",
        lambda _base, _head: ["frontend/apps/web_app/tests/shared-chat-embed-assets.spec.ts"],
    )

    with pytest.raises(RuntimeError, match="relevant files changed"):
        tests_control.resolve_test_subject_commit(expected, ["--spec", "shared-chat-embed-assets.spec.ts"])


def test_subject_commit_rejects_ancestor_when_token_linked_source_changed(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    expected = "a" * 40
    current_dev = "b" * 40
    spec_dir = tests_control.SPEC_DIR
    component_path = tmp_path / "frontend" / "packages" / "ui" / "src" / "components" / "ChatHeader.svelte"
    spec_dir.mkdir(parents=True)
    component_path.parent.mkdir(parents=True)
    (spec_dir / "shared-chat-embed-assets.spec.ts").write_text(
        "await page.getByTestId('shared-chat-badge');\n",
        encoding="utf-8",
    )
    component_path.write_text('<span data-testid="shared-chat-badge"></span>\n', encoding="utf-8")
    monkeypatch.setattr(tests_control, "current_git_sha", lambda: "c" * 40)
    monkeypatch.setattr(tests_control, "integrated_dev_sha", lambda: current_dev)
    monkeypatch.setattr(
        tests_control,
        "git_is_ancestor",
        lambda ancestor, descendant: (ancestor, descendant) == (expected, current_dev),
    )
    monkeypatch.setattr(
        tests_control,
        "git_changed_files_between",
        lambda _base, _head: ["frontend/packages/ui/src/components/ChatHeader.svelte"],
    )

    with pytest.raises(RuntimeError, match="relevant files changed"):
        tests_control.resolve_test_subject_commit(expected, ["--spec", "shared-chat-embed-assets.spec.ts"])


def test_subject_commit_accepts_peer_spec_change_with_shared_harness_token(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    expected = "a" * 40
    current_dev = "b" * 40
    spec_dir = tests_control.SPEC_DIR
    spec_dir.mkdir(parents=True)
    (spec_dir / "task-detail-fullscreen.spec.ts").write_text(
        "await page.getByTestId('component-preview-canvas');\n",
        encoding="utf-8",
    )
    (spec_dir / "component-message-input.spec.ts").write_text(
        "await page.getByTestId('component-preview-canvas');\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tests_control, "current_git_sha", lambda: "c" * 40)
    monkeypatch.setattr(tests_control, "integrated_dev_sha", lambda: current_dev)
    monkeypatch.setattr(
        tests_control,
        "git_is_ancestor",
        lambda ancestor, descendant: (ancestor, descendant) == (expected, current_dev),
    )
    monkeypatch.setattr(
        tests_control,
        "git_changed_files_between",
        lambda _base, _head: ["frontend/apps/web_app/tests/component-message-input.spec.ts"],
    )

    assert tests_control.resolve_test_subject_commit(
        expected,
        ["--spec", "task-detail-fullscreen.spec.ts"],
    ) == current_dev


def test_subject_commit_rejects_sha_outside_checkout_and_integrated_dev(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    monkeypatch.setattr(tests_control, "current_git_sha", lambda: "old-worktree-commit")
    monkeypatch.setattr(tests_control, "integrated_dev_sha", lambda: "deployed-commit-123")
    monkeypatch.setattr(tests_control, "git_is_ancestor", lambda _ancestor, _descendant: False)

    with pytest.raises(RuntimeError, match="moving target"):
        tests_control.resolve_test_subject_commit("unrelated-commit")


def test_post_run_subject_guard_rejects_relevant_daily_change(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    subject = "a" * 40
    current_dev = "b" * 40
    monkeypatch.setattr(tests_control, "integrated_dev_sha", lambda: current_dev)
    monkeypatch.setattr(tests_control, "git_is_ancestor", lambda base, head: (base, head) == (subject, current_dev))
    monkeypatch.setattr(
        tests_control,
        "git_changed_files_between",
        lambda _base, _head: ["frontend/packages/ui/src/components/ChatHeader.svelte"],
    )

    with pytest.raises(RuntimeError, match="relevant files changed during the run"):
        tests_control.validate_test_subject_commit_after_run(subject, ["--daily"])


def test_post_run_subject_guard_accepts_irrelevant_focused_spec_change(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    subject = "a" * 40
    current_dev = "b" * 40
    monkeypatch.setattr(tests_control, "integrated_dev_sha", lambda: current_dev)
    monkeypatch.setattr(tests_control, "git_is_ancestor", lambda base, head: (base, head) == (subject, current_dev))
    monkeypatch.setattr(
        tests_control,
        "git_changed_files_between",
        lambda _base, _head: ["docs/releases/daily/2026-08-27.md"],
    )

    assert tests_control.validate_test_subject_commit_after_run(
        subject,
        ["--spec", "shared-chat-embed-assets.spec.ts"],
    ) == current_dev


def test_post_run_subject_guard_exact_mode_preserves_pinned_evidence(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    subject = "a" * 40
    monkeypatch.setattr(
        tests_control,
        "integrated_dev_sha",
        lambda: (_ for _ in ()).throw(AssertionError("exact pinned evidence must not consult moving dev")),
    )

    assert tests_control.validate_test_subject_commit_after_run(
        subject,
        ["--spec", "chat-flow.spec.ts"],
        require_exact=True,
    ) == subject


def test_seeded_only_failed_files_from_non_spec_lease(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    lease = {
        "entry": {
            "test": "scripts/run_tests.py",
            "key": "playwright::scripts/run_tests.py",
        }
    }

    assert tests_control.seeded_only_failed_files_from_lease(lease, ["--only-failed"]) == [
        "scripts/run_tests.py"
    ]
    assert tests_control.seeded_only_failed_files_from_lease(lease, ["--spec", "chat-flow.spec.ts"]) == []


def test_seeded_only_failed_files_ignores_real_specs(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    lease = {"entry": {"test": "chat-flow.spec.ts"}}

    assert tests_control.seeded_only_failed_files_from_lease(lease, ["--only-failed"]) == []


def test_main_strips_run_passthrough_sentinel(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    seen_args = []

    def fake_command_run(args):
        seen_args.append(args)
        return 0

    monkeypatch.setattr(tests_control, "command_run", fake_command_run)

    assert tests_control.main(["run", "--", "--suite", "vitest"]) == 0
    assert seen_args == [["--suite", "vitest"]]


def test_main_delegates_run_help_without_recording_started_run(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    seen_commands = []

    def fail_command_run(_args):
        raise AssertionError("run --help must not enter command_run")

    def fake_subprocess_run(command, cwd=None):
        seen_commands.append((command, cwd))
        return tests_control.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(tests_control, "command_run", fail_command_run)
    monkeypatch.setattr(tests_control.subprocess, "run", fake_subprocess_run)

    assert tests_control.main(["run", "--help"]) == 0
    assert seen_commands == [
        (
            [sys.executable, str(tests_control.RUN_TESTS_SCRIPT), "--help"],
            tests_control.PROJECT_ROOT,
        )
    ]


def test_commit_prefix_matching_accepts_short_or_long_sha(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    assert tests_control._matches_commit_prefix("abcdef123456", "abcdef1") is True
    assert tests_control._matches_commit_prefix("abcdef1", "abcdef123456") is True
    assert tests_control._matches_commit_prefix("abcdef123456", "1234567") is False


def test_next_lease_claims_different_groups_for_parallel_workers(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())

    first = tests_control.claim_next(session_id="s1")
    second = tests_control.claim_next(session_id="s2")

    assert first is not None
    assert second is not None
    assert first["lease_id"] != second["lease_id"]
    assert first["group_id"] != second["group_id"]
    assert first["entry"]["test"] == "account-recovery-flow.spec.ts"
    assert second["entry"]["test"] == "chat-flow.spec.ts"

    leases = tests_control.get_store().list_claims()
    assert [lease["status"] for lease in leases] == ["active", "active"]
    assert not tests_control.LEASES_FILE.exists()


def test_complete_and_release_update_lease_status(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())
    first = tests_control.claim_next(session_id="s1")
    second = tests_control.claim_next(session_id="s2")

    tests_control.complete_lease(first["lease_id"], commit="abc123d")
    tests_control.release_lease(second["lease_id"], reason="blocked infra")

    claims = tests_control.get_store().list_claims()
    by_id = {lease["lease_id"]: lease for lease in claims}
    assert by_id[first["lease_id"]]["status"] == "completed"
    assert by_id[first["lease_id"]]["commit"] == "abc123d"
    assert by_id[second["lease_id"]]["status"] == "released"
    assert by_id[second["lease_id"]]["release_reason"] == "blocked infra"


def test_completed_lease_blocks_same_stale_run_but_not_new_failure(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    run = sample_run()
    run["summary"] = {"total": 1, "passed": 0, "failed": 1, "skipped": 0}
    run["suites"]["playwright"]["tests"] = [run["suites"]["playwright"]["tests"][1]]
    tests_control.record_run_result(run)

    first = tests_control.claim_next(session_id="s1")
    assert first is not None
    tests_control.complete_lease(first["lease_id"], commit="abc123d")

    assert tests_control.claim_next(session_id="s2") is None

    rerun = sample_run()
    rerun["run_id"] = "2026-06-19T04:00:02Z"
    rerun["summary"] = {"total": 1, "passed": 0, "failed": 1, "skipped": 0}
    rerun["suites"]["playwright"]["tests"] = [rerun["suites"]["playwright"]["tests"][1]]
    tests_control.record_run_result(rerun)

    second = tests_control.claim_next(session_id="s3")
    assert second is not None
    assert second["entry"]["test"] == "account-recovery-flow.spec.ts"


def test_completed_lease_blocks_same_run_sibling_group_entries(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    lease = {
        "status": "completed",
        "group_id": "auth_signup-same",
        "entry": {"key": "playwright::first.spec.ts", "run_id": "run-1"},
    }

    assert tests_control.lease_blocks_entry(
        lease,
        {"group_id": "auth_signup-same", "key": "playwright::second.spec.ts", "run_id": "run-1"},
    )
    assert not tests_control.lease_blocks_entry(
        lease,
        {"group_id": "auth_signup-same", "key": "playwright::second.spec.ts", "run_id": "run-2"},
    )


def test_released_lease_blocks_same_test_until_expiry(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    run = sample_run()
    run["summary"] = {"total": 1, "passed": 0, "failed": 1, "skipped": 0}
    run["suites"]["playwright"]["tests"] = [run["suites"]["playwright"]["tests"][1]]
    tests_control.record_run_result(run)

    first = tests_control.claim_next(session_id="s1")
    assert first is not None
    tests_control.release_lease(first["lease_id"], reason="ignored elsewhere")

    assert tests_control.claim_next(session_id="s2") is None

    rerun = sample_run()
    rerun["run_id"] = "2026-06-19T04:00:02Z"
    rerun["summary"] = {"total": 1, "passed": 0, "failed": 1, "skipped": 0}
    rerun["suites"]["playwright"]["tests"] = [rerun["suites"]["playwright"]["tests"][1]]
    tests_control.record_run_result(rerun)

    assert tests_control.claim_next(session_id="s3") is None


def test_mark_running_adds_started_history_event(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    tests_control.mark_running(
        suite="playwright",
        tests=["chat-flow.spec.ts"],
        command=["python3", "scripts/tests.py", "run", "--spec", "chat-flow.spec.ts"],
    )

    state = tests_control.load_state()
    assert state["tests"]["playwright::chat-flow.spec.ts"]["status"] == "running"
    history = tests_control.load_history_events()
    assert any(event["event"] == "started" and event["test"] == "chat-flow.spec.ts" for event in history)


def test_mark_running_preserves_previous_stable_failure(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())

    tests_control.mark_running(
        suite="playwright",
        tests=["chat-flow.spec.ts"],
        command=["python3", "scripts/tests.py", "run", "--spec", "chat-flow.spec.ts"],
    )

    record = tests_control.load_state()["tests"]["playwright::chat-flow.spec.ts"]
    assert record["status"] == "failed"
    assert record["stable_status"] == "failed"
    assert record["active_status"] == "running"
    assert record["stable_run_id"] == "2026-06-19T03:00:02Z"
    assert record["active_run_id"].startswith("manual-")
    assert tests_control.get_store().test_runs[record["active_run_id"]]["status"] == "running"
    assert tests_control.load_state()["summary"]["failed"] == 2
    assert tests_control.load_state()["summary"]["running"] == 1


def test_record_run_clears_suite_running_marker_after_results(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.mark_running(
        suite="pytest_unit",
        tests=[],
        command=["python3", "scripts/tests.py", "run", "--suite", "pytest"],
    )

    tests_control.record_run_result({
        "run_id": "2026-06-19T04:30:02Z",
        "git_sha": "def456abc",
        "git_branch": "dev",
        "environment": "development",
        "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
        "suites": {"pytest_unit": {"status": "passed", "tests": [{"name": "tests/test_ok.py::test_ok", "status": "passed"}]}},
    })

    state = tests_control.load_state()
    assert state["tests"]["pytest_unit::pytest_unit"]["status"] == "passed"
    assert state["tests"]["pytest_unit::pytest_unit"]["active_status"] is None
    assert state["summary"]["running"] == 0


def test_passed_suite_without_rows_clears_stale_suite_failures(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result({
        "run_id": "2026-06-19T03:00:02Z",
        "git_sha": "abc123def",
        "git_branch": "dev",
        "environment": "development",
        "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0},
        "suites": {"pytest_unit": {"status": "failed", "tests": [{"name": "tests/test_old.py::test_old", "status": "failed", "error": "old failure"}]}},
    })

    tests_control.record_run_result({
        "run_id": "2026-06-19T04:00:02Z",
        "git_sha": "def456abc",
        "git_branch": "dev",
        "environment": "development",
        "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "suites": {"pytest_unit": {"status": "passed", "tests": []}},
    })

    state = tests_control.load_state()
    record = state["tests"]["pytest_unit::tests/test_old.py::test_old"]
    assert record["status"] == "passed"
    assert record["error"] is None
    assert state["summary"]["failed"] == 0


def test_import_run_accepts_raw_pytest_json_report(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    report_path = tmp_path / "pytest-results.json"
    report_path.write_text(json.dumps({
        "created": 1784322951.0,
        "duration": 1.25,
        "summary": {"total": 2, "passed": 1, "failed": 1, "skipped": 0},
        "tests": [
            {"nodeid": "tests/test_ok.py::test_ok", "outcome": "passed", "duration": 0.1},
            {"nodeid": "tests/test_bad.py::test_bad", "outcome": "failed", "duration": 0.2, "call": {"longrepr": "assert False"}},
        ],
    }), encoding="utf-8")

    tests_control.import_run_artifact(report_path, source="github_actions", external_run_id="29613991033", workflow="pytest-unit.yml")

    state = tests_control.load_state()
    assert state["tests"]["pytest_unit::tests/test_ok.py::test_ok"]["status"] == "passed"
    failed = state["tests"]["pytest_unit::tests/test_bad.py::test_bad"]
    assert failed["status"] == "failed"
    assert failed["error"] == "assert False"
    assert tests_control.get_store().test_runs["29613991033"]["workflow"] == "pytest-unit.yml"


def test_normalize_playwright_report_retains_one_terminal_video_artifact(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    video = tmp_path / "video.webm"
    report = {
        "config": {},
        "metadata": {"gitCommit": {"hash": "abc1234", "branch": "dev"}},
        "suites": [
            {
                "file": "example.spec.ts",
                "specs": [
                    {
                        "file": "example.spec.ts",
                        "tests": [
                            {
                                "results": [
                                    {
                                        "status": "passed",
                                        "duration": 1000,
                                        "attachments": [{"name": "video", "contentType": "video/webm", "path": str(video)}],
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ],
    }

    normalized = tests_control.normalize_playwright_json_report(report, tmp_path / "playwright.json", external_run_id="run-one")

    test = normalized["suites"]["playwright"]["tests"][0]
    assert test["artifact_path"] == str(video)


def test_record_latest_run_artifact_persists_deploy_gate_metadata(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    artifact = tests_control.RESULTS_DIR / "last-run.json"
    artifact.parent.mkdir(parents=True)
    commit = "a" * 40
    video = tmp_path / "video.webm"
    video.write_bytes(b"verified-video")
    artifact.write_text(json.dumps({
        "run_id": "run-one",
        "git_sha": commit,
        "environment": "https://app.dev.openmates.org",
        "suites": {"playwright": {"status": "passed", "tests": [{
            "file": "example.spec.ts", "status": "passed", "artifact_path": str(video),
        }]}},
    }), encoding="utf-8")

    recorded = tests_control.record_latest_run_artifact(expected_commit=commit, deployment_verified=True)

    persisted = json.loads(artifact.read_text(encoding="utf-8"))
    assert recorded == commit
    assert persisted["deployment_verified"] is True
    assert persisted["deployment_reference"] == commit
    attestations = list(tests_control.PROOF_SOURCE_DIR.glob("*.json"))
    assert len(attestations) == 1
    attestation = json.loads(attestations[0].read_text(encoding="utf-8"))
    assert attestation["artifact_sha256"].startswith("sha256:")
    assert Path(attestation["artifact_path"]).is_relative_to(tests_control.PROOF_SOURCE_ARTIFACTS_DIR)
    assert Path(attestation["artifact_path"]).read_bytes() == b"verified-video"


def test_record_latest_run_artifact_expands_short_sha_for_proof_source(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    artifact = tests_control.RESULTS_DIR / "last-run.json"
    artifact.parent.mkdir(parents=True)
    commit = "a" * 40
    video = tmp_path / "video.webm"
    video.write_bytes(b"verified-video")
    artifact.write_text(json.dumps({
        "run_id": "run-one",
        "git_sha": commit[:9],
        "environment": "https://app.dev.openmates.org",
        "suites": {"playwright": {"status": "passed", "tests": [{
            "file": "example.spec.ts", "status": "passed", "artifact_path": str(video),
        }]}},
    }), encoding="utf-8")

    recorded = tests_control.record_latest_run_artifact(expected_commit=commit, deployment_verified=True)

    persisted = json.loads(artifact.read_text(encoding="utf-8"))
    assert recorded == commit
    assert persisted["git_sha"] == commit
    assert persisted["deployment_reference"] == commit
    attestations = list(tests_control.PROOF_SOURCE_DIR.glob("*.json"))
    assert len(attestations) == 1
    attestation = json.loads(attestations[0].read_text(encoding="utf-8"))
    assert attestation["git_sha"] == commit


def test_record_latest_run_artifact_attests_downloaded_recording_bundle(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    artifact = tests_control.RESULTS_DIR / "last-run.json"
    artifact.parent.mkdir(parents=True)
    commit = "a" * 40
    recording_dir = tests_control.RESULTS_DIR / "recordings" / "latest" / "example"
    video = recording_dir / "videos" / "example.webm"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"verified-video")
    (recording_dir / "manifest.json").write_text(json.dumps({
        "spec": "example.spec.ts",
        "run_id": "parent-run",
        "git_sha": commit[:9],
        "github_run_url": "https://github.com/glowingkitty/OpenMates/actions/runs/12345",
        "assets": {"video_key": "latest/example/videos/example.webm"},
    }), encoding="utf-8")
    artifact.write_text(json.dumps({
        "run_id": "parent-run",
        "git_sha": commit[:9],
        "environment": "https://app.dev.openmates.org",
        "suites": {"playwright": {"status": "passed", "tests": [{
            "file": "example.spec.ts",
            "status": "passed",
            "run_id": 12345,
            "video_paths": ["frontend/test-results/example/video.webm"],
        }]}},
    }), encoding="utf-8")

    recorded = tests_control.record_latest_run_artifact(expected_commit=commit, deployment_verified=True)

    assert recorded == commit
    attestations = list(tests_control.PROOF_SOURCE_DIR.glob("*.json"))
    assert len(attestations) == 1
    attestation = json.loads(attestations[0].read_text(encoding="utf-8"))
    assert Path(attestation["artifact_path"]).is_relative_to(tests_control.PROOF_SOURCE_ARTIFACTS_DIR)
    assert Path(attestation["artifact_path"]).read_bytes() == b"verified-video"


def test_record_latest_run_artifact_keeps_cropped_thumbnail_out_of_video_player(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    artifact = tests_control.RESULTS_DIR / "last-run.json"
    artifact.parent.mkdir(parents=True)
    commit = "a" * 40
    recording_dir = tests_control.RESULTS_DIR / "recordings" / "latest" / "example"
    video = recording_dir / "videos" / "example.webm"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"verified-video")
    thumbnail = recording_dir / "thumbnail.png"
    thumbnail.write_bytes(b"verified-thumbnail")
    (recording_dir / "manifest.json").write_text(json.dumps({
        "spec": "example.spec.ts",
        "run_id": "parent-run",
        "git_sha": commit[:9],
        "github_run_url": "https://github.com/glowingkitty/OpenMates/actions/runs/12345",
        "assets": {"video_key": "latest/example/videos/example.webm"},
    }), encoding="utf-8")
    artifact.write_text(json.dumps({
        "run_id": "parent-run",
        "git_sha": commit[:9],
        "environment": "https://app.dev.openmates.org",
        "suites": {"playwright": {"status": "passed", "tests": [{
            "file": "example.spec.ts",
            "status": "passed",
            "run_id": 12345,
        }]}},
    }), encoding="utf-8")
    uploads = []

    def fake_uploader(**kwargs):
        uploads.append(kwargs)
        return {
            "key": "opencode-responses/latest/spec-ts-web-laptop/video.webm",
            "snippets": {"html": "<video></video>", "markdown": "[video](https://example.invalid/video.webm)"},
        }

    recorded = tests_control.record_latest_run_artifact(
        expected_commit=commit,
        response_media_run_type="spec-ts-web-laptop",
        response_media_uploader=fake_uploader,
    )

    assert recorded == commit[:9]
    assert uploads == [{
        "path": video.resolve(),
        "poster_path": None,
        "run_type": "spec-ts-web-laptop",
        "alt": "Playwright example.spec.ts latest run video",
    }]
    run_data = json.loads(artifact.read_text(encoding="utf-8"))
    assert run_data["response_media_video"]["response_media_html"] == "<video></video>"
    latest = json.loads(tests_control.RESPONSE_MEDIA_LATEST_FILE.read_text(encoding="utf-8"))
    assert latest["playwright_spec"]["response_media_key"] == "opencode-responses/latest/spec-ts-web-laptop/video.webm"


def test_record_latest_run_artifact_rejects_stale_downloaded_recording(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    artifact = tests_control.RESULTS_DIR / "last-run.json"
    artifact.parent.mkdir(parents=True)
    commit = "a" * 40
    recording_dir = tests_control.RESULTS_DIR / "recordings" / "latest" / "example"
    video = recording_dir / "videos" / "example.webm"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"stale-video")
    (recording_dir / "manifest.json").write_text(json.dumps({
        "spec": "example.spec.ts", "run_id": "parent-run", "git_sha": "b" * 9,
        "assets": {"video_key": "latest/example/videos/example.webm"},
    }), encoding="utf-8")
    artifact.write_text(json.dumps({
        "run_id": "parent-run", "git_sha": commit[:9], "environment": "development",
        "suites": {"playwright": {"tests": [{"file": "example.spec.ts", "status": "passed"}]}},
    }), encoding="utf-8")

    tests_control.record_latest_run_artifact(expected_commit=commit, deployment_verified=True)

    assert not tests_control.PROOF_SOURCE_DIR.exists()


def test_downloaded_recording_paths_do_not_collide_on_spec_basename(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    commit = "a" * 40
    recording_dir = tests_control.RESULTS_DIR / "recordings" / "latest" / "other-example"
    video = recording_dir / "videos" / "example.webm"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"wrong-spec-video")
    (recording_dir / "manifest.json").write_text(json.dumps({
        "spec": "other/example.spec.ts", "run_id": "run-one", "git_sha": commit[:9],
        "assets": {"video_key": "latest/other-example/videos/example.webm"},
    }), encoding="utf-8")

    matches = tests_control._downloaded_recording_paths("target/example.spec.ts", {"run-one"}, commit)

    assert matches == []


def test_skipped_deploy_gate_is_not_verified(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    options = tests_control.ControlRunOptions(
        forwarded_args=["--spec", "example.spec.ts"],
        expected_commit="abc1234",
        gate_deploy=True,
    )
    monkeypatch.setenv("OPENMATES_SKIP_E2E_DEPLOY_GATE", "true")
    monkeypatch.setattr(tests_control, "current_git_sha", lambda: "abc1234")

    assert tests_control.run_e2e_deploy_gate(options) is False
    assert not tests_control.PROOF_SOURCE_DIR.exists()


def test_exact_commit_verification_cannot_skip_deploy_gate(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    commit = "a" * 40
    options = tests_control.ControlRunOptions(
        forwarded_args=["--spec", "example.spec.ts"],
        expected_commit=commit,
        require_exact_commit=True,
        gate_deploy=True,
    )
    monkeypatch.setenv("OPENMATES_SKIP_E2E_DEPLOY_GATE", "true")
    monkeypatch.setattr(tests_control, "current_git_sha", lambda: commit)

    with pytest.raises(RuntimeError, match="cannot skip"):
        tests_control.run_e2e_deploy_gate(options)


def test_normalize_playwright_report_preserves_duplicate_video_attachments(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    video = str(tmp_path / "video.webm")
    result = {
        "status": "passed",
        "duration": 1000,
        "attachments": [
            {"contentType": "video/webm", "path": video},
            {"contentType": "video/webm", "path": video},
        ],
    }
    report = {
        "config": {},
        "suites": [{"file": "example.spec.ts", "specs": [{"tests": [{"results": [result]}]}]}],
    }

    normalized = tests_control.normalize_playwright_json_report(report, tmp_path / "playwright.json", external_run_id="run-one")

    assert normalized["suites"]["playwright"]["tests"][0]["artifact_paths"] == [video, video]


def test_normalize_playwright_report_preserves_terminal_proof_timeline_attachment(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    video = str(tmp_path / "video.webm")
    timeline = str(tmp_path / "proof-timeline.json")
    report = {
        "config": {},
        "suites": [{"file": "example.spec.ts", "specs": [{"tests": [{"results": [{
            "status": "passed",
            "duration": 1000,
            "attachments": [
                {"name": "video", "contentType": "video/webm", "path": video},
                {
                    "name": "openmates-proof-timeline",
                    "contentType": "application/vnd.openmates.proof-timeline+json",
                    "path": timeline,
                },
            ],
        }]}]}]}],
    }

    normalized = tests_control.normalize_playwright_json_report(report, tmp_path / "playwright.json", external_run_id="run-one")

    test_result = normalized["suites"]["playwright"]["tests"][0]
    assert test_result["artifact_path"] == video
    assert test_result["proof_timeline_path"] == timeline


def test_duplicate_video_attachments_create_one_proof_source_attestation(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    commit = "a" * 40
    video = tmp_path / "video.webm"
    video.write_bytes(b"video")
    timeline = tmp_path / "proof-timeline.json"
    timeline.write_text('{"device":"web-laptop"}', encoding="utf-8")
    run_data = {
        "run_id": "run-one",
        "git_sha": commit,
        "deployment_reference": commit,
        "deployment_verified": True,
        "gate_deploy": True,
        "suites": {"playwright": {"tests": [{
            "file": "example.spec.ts",
            "status": "passed",
            "artifact_paths": [str(video), str(video)],
            "proof_timeline_path": str(timeline),
        }]}},
    }

    records = tests_control.record_proof_source_attestations(run_data)

    assert len(records) == 1
    attestation = json.loads(records[0].read_text(encoding="utf-8"))
    assert attestation["run_id"] == "run-one"
    assert attestation["source_run_id"] == "run-one"
    assert Path(attestation["artifact_path"]).read_bytes() == b"video"
    assert Path(attestation["proof_timeline_path"]).read_text(encoding="utf-8") == '{"device":"web-laptop"}'
    assert Path(attestation["artifact_path"]).is_relative_to(tests_control.PROOF_SOURCE_ARTIFACTS_DIR)
    assert Path(attestation["proof_timeline_path"]).is_relative_to(tests_control.PROOF_SOURCE_ARTIFACTS_DIR)


def test_auto_finalize_web_proof_source_renders_reviews_and_publishes(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    commit = "a" * 40
    video = tmp_path / "source.webm"
    video.write_bytes(b"video")
    frame = tmp_path / "checkpoint.png"
    frame.write_bytes(b"frame")
    timeline = tmp_path / "proof-timeline.json"
    timeline.write_text(json.dumps({
        "schema_version": 1,
        "device": "web-laptop",
        "contract": {
            "id": "proof-video-web",
            "title": "Proof web",
            "surface": "web",
                "devices": ["web-laptop"],
                "domain": "app.dev.openmates.org",
                "tutorial": {"readingWordsPerSecond": 2.5, "minimumHoldMs": 1800, "maximumHoldMs": 5000},
            "transcript": [{"id": "welcome", "text": "Welcome is visible.", "checkpoint": "ready", "devices": ["web-laptop"]}],
            "assertions": [
                {"id": "welcome.visible", "visual": "The welcome screen is visible inside browser chrome.", "checkpoint": "ready", "devices": ["web-laptop"]},
                {"id": "phone.visible", "visual": "The phone-only state is visible.", "checkpoint": "phone-ready", "devices": ["web-phone"]},
            ],
        },
        "events": [
            {"kind": "checkpoint", "id": "setup", "at_ms": 20},
            {"kind": "checkpoint", "id": "ready", "at_ms": 100},
            {"kind": "action", "id": "reload-page", "start_ms": 50, "end_ms": 4100},
        ],
        "assertion_results": [{"id": "welcome.visible", "status": "passed", "at_ms": 80}],
        "checkpoint_frames": [{"checkpoint": "ready", "path": str(frame), "sha256": tests_control._file_sha256(frame)}],
    }), encoding="utf-8")
    record_path = tests_control.PROOF_SOURCE_DIR / "record.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(json.dumps({
        "run_id": "12345",
        "git_sha": commit,
        "spec": "proof-video-architecture.spec.ts",
        "status": "passed",
        "source": "scripts_tests",
        "deployment_reference": commit,
        "target": "development",
        "artifact_path": str(video),
        "artifact_sha256": tests_control._file_sha256(video),
        "proof_timeline_path": str(timeline),
        "proof_timeline_sha256": tests_control._file_sha256(timeline),
    }), encoding="utf-8")
    calls: dict[str, object] = {}

    def produce(**kwargs):
        calls["produce"] = kwargs
        return {"spec_id": kwargs["spec_id"], "subject_commit": kwargs["subject_commit"], "publication": {"status": "pending"}}

    def review(**kwargs):
        calls["review"] = kwargs
        return {"status": "passed", "manifest": {"review": {"status": "passed"}, "publication": {"status": "pending"}}}

    def publish(run_dir, manifest):
        calls["publish"] = {"run_dir": run_dir, "manifest": manifest}
        return {**manifest, "publication": {"status": "delivered", "snippet_html": "<video></video>"}}

    finalizations = tests_control.auto_finalize_proof_video_sources(
        {"git_sha": commit, "run_id": "parent-run", "environment": "development"},
        [record_path],
        session_id="8f7c",
        produce_hook=produce,
        review_hook=review,
        publish_hook=publish,
        source_duration_hook=lambda _path: 40.0,
    )

    assert finalizations == [{
        "status": "delivered",
        "spec": "proof-video-architecture.spec.ts",
        "run_id": "12345",
        "run_dir": str(tests_control.RESULTS_DIR / "proof-videos" / "8f7c" / "proof-video-architecture.spec-12345"),
        "subject_commit": commit,
        "device_profile": "web-laptop",
        "publication_status": "delivered",
        "snippet_html": "<video></video>",
    }]
    produce_kwargs = calls["produce"]
    assert produce_kwargs["source"]["browser_domain"] == "app.dev.openmates.org"
    assert produce_kwargs["browser_tutorial_plan"]["request"]["renderer"] == "openmates-remotion-browser-v1"
    assert produce_kwargs["browser_tutorial_plan"]["request"]["domain"] == "app.dev.openmates.org"
    assert produce_kwargs["source"]["state_change_timestamps"] == [0.02, 0.1]
    assert produce_kwargs["source"]["state_change_timestamps_by_id"] == {
        "setup": 0.02,
        "ready": 0.1,
        "welcome.visible": 0.1,
    }
    assert produce_kwargs["source"]["source_end_timestamp_seconds"] == 4.1
    assert produce_kwargs["source"]["action_timestamps"] == [0.05, 4.1]
    assert produce_kwargs["ready_timestamp_seconds"] == 0.1
    assert produce_kwargs["playback_rate"] == 1.0
    assert produce_kwargs["hold_last_frame_seconds"] == 0.0
    assert produce_kwargs["caption_text"] == "Welcome is visible."
    assert produce_kwargs["expected_proof"] == "The welcome screen is visible inside browser chrome."
    assert calls["review"]["correction_round"] == 0
    assert calls["publish"]["run_dir"] == produce_kwargs["run_dir"]


def test_apple_proof_capture_end_excludes_xcode_teardown_tail(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    assert tests_control.proof_capture_end_timestamp_seconds(
        surface="apple",
        source_media_duration_seconds=12.0,
        proof_end_times=[8.0],
    ) == 8.0
    assert tests_control.proof_capture_end_timestamp_seconds(
        surface="web",
        source_media_duration_seconds=12.0,
        proof_end_times=[8.0],
    ) == 12.0


def test_record_latest_run_artifact_attests_each_downloaded_recording(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    artifact = tests_control.RESULTS_DIR / "last-run.json"
    artifact.parent.mkdir(parents=True)
    commit = "a" * 40
    recording_dir = tests_control.RESULTS_DIR / "recordings" / "latest" / "example"
    first_video = recording_dir / "videos" / "first.webm"
    second_video = recording_dir / "videos" / "second.webm"
    first_video.parent.mkdir(parents=True)
    first_video.write_bytes(b"first-video")
    second_video.write_bytes(b"second-video")
    for slug, video in (("flow-one", first_video), ("flow-two", second_video)):
        manifest_dir = tests_control.RESULTS_DIR / "recordings" / "latest" / f"example--{slug}"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "manifest.json").write_text(json.dumps({
            "spec": "example.spec.ts",
            "run_id": "parent-run",
            "git_sha": commit[:9],
            "github_run_url": "https://github.com/glowingkitty/OpenMates/actions/runs/12345",
            "assets": {"video_key": f"latest/example/videos/{video.name}"},
        }), encoding="utf-8")
    artifact.write_text(json.dumps({
        "run_id": "parent-run",
        "git_sha": commit[:9],
        "environment": "https://app.dev.openmates.org",
        "suites": {"playwright": {"status": "passed", "tests": [{
            "file": "example.spec.ts",
            "status": "passed",
            "run_id": 12345,
            "video_paths": ["frontend/test-results/example-one/video.webm", "frontend/test-results/example-two/video.webm"],
        }]}},
    }), encoding="utf-8")

    recorded = tests_control.record_latest_run_artifact(expected_commit=commit, deployment_verified=True)

    assert recorded == commit
    attestations = [json.loads(path.read_text(encoding="utf-8")) for path in tests_control.PROOF_SOURCE_DIR.glob("*.json")]
    assert len(attestations) == 2
    assert {Path(attestation["artifact_path"]).read_bytes() for attestation in attestations} == {b"first-video", b"second-video"}
    assert all(Path(attestation["artifact_path"]).is_relative_to(tests_control.PROOF_SOURCE_ARTIFACTS_DIR) for attestation in attestations)
    assert all(attestation["source_run_id"] == "12345" for attestation in attestations)
    assert all(attestation["run_id"].startswith("12345:") for attestation in attestations)


def test_proof_timeline_attestation_prefers_attached_proof_video(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    artifact = tests_control.RESULTS_DIR / "last-run.json"
    artifact.parent.mkdir(parents=True)
    commit = "a" * 40
    recording_dir = tests_control.RESULTS_DIR / "recordings" / "latest" / "example"
    first_video = recording_dir / "videos" / "first.webm"
    second_video = recording_dir / "videos" / "second.webm"
    first_video.parent.mkdir(parents=True)
    first_video.write_bytes(b"first-video")
    second_video.write_bytes(b"second-video")
    (recording_dir / "artifact-meta.json").write_text(json.dumps({
        "spec": "example.spec.ts",
        "proof_timeline_file": "proof-timeline.json",
        "proof_video_file": "videos/second.webm",
    }), encoding="utf-8")
    for name, video in (("first", first_video), ("second", second_video)):
        manifest_dir = tests_control.RESULTS_DIR / "recordings" / "latest" / f"example--{name}"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "manifest.json").write_text(json.dumps({
            "spec": "example.spec.ts",
            "run_id": "parent-run",
            "git_sha": commit[:9],
            "github_run_url": "https://github.com/glowingkitty/OpenMates/actions/runs/12345",
            "assets": {"video_key": f"latest/example/videos/{video.name}"},
        }), encoding="utf-8")
    timeline = tmp_path / "proof-timeline.json"
    timeline.write_text("{}", encoding="utf-8")
    artifact.write_text(json.dumps({
        "run_id": "parent-run",
        "git_sha": commit[:9],
        "environment": "https://app.dev.openmates.org",
        "suites": {"playwright": {"status": "passed", "tests": [{
            "file": "example.spec.ts",
            "status": "passed",
            "run_id": 12345,
            "proof_timeline_path": str(timeline),
        }]}},
    }), encoding="utf-8")

    recorded = tests_control.record_latest_run_artifact(expected_commit=commit, deployment_verified=True)

    assert recorded == commit
    attestations = [json.loads(path.read_text(encoding="utf-8")) for path in tests_control.PROOF_SOURCE_DIR.glob("*.json")]
    assert len(attestations) == 1
    assert Path(attestations[0]["artifact_path"]).read_bytes() == b"second-video"
    assert Path(attestations[0]["artifact_path"]).is_relative_to(tests_control.PROOF_SOURCE_ARTIFACTS_DIR)


def test_proof_source_attestation_requires_explicit_deploy_gate(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    commit = "a" * 40

    with pytest.raises(RuntimeError, match="passed deploy gate"):
        tests_control.record_proof_source_attestations({
            "run_id": "run-one",
            "git_sha": commit,
            "deployment_reference": commit,
            "deployment_verified": True,
            "suites": {"playwright": {"tests": []}},
        })


def test_full_unit_suite_retires_absent_stale_failures(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result({
        "run_id": "2026-06-19T03:00:02Z",
        "git_sha": "abc123def",
        "git_branch": "dev",
        "environment": "development",
        "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0},
        "suites": {"pytest_unit": {"status": "failed", "tests": [{"name": "tests/test_old.py::test_old_name", "status": "failed", "error": "old failure"}]}},
    })

    tests_control.record_run_result({
        "run_id": "2026-06-19T04:00:02Z",
        "git_sha": "def456abc",
        "git_branch": "dev",
        "environment": "development",
        "flags": {"suite": "pytest", "only_failed": False},
        "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
        "suites": {"pytest_unit": {"status": "passed", "tests": [{"name": "tests/test_old.py::test_new_name", "status": "passed"}]}},
    })

    state = tests_control.load_state()
    stale = state["tests"]["pytest_unit::tests/test_old.py::test_old_name"]
    assert stale["status"] == "not_started"
    assert stale["error"] is None
    assert state["tests"]["pytest_unit::tests/test_old.py::test_new_name"]["status"] == "passed"
    assert state["summary"]["failed"] == 0


def test_triage_supports_limit_category_and_suite_filters(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())

    triage = tests_control.build_triage(category_filter="chat_send_receive", suite_filter="playwright", limit=1)

    assert len(triage["entries"]) == 1
    assert triage["entries"][0]["category"] == "chat_send_receive"
    assert triage["entries"][0]["suite"] == "playwright"

    assert tests_control.build_triage(suite_filter="pytest")["entries"] == []


def test_investigate_returns_bounded_redacted_revision_and_artifact_evidence(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    key = "playwright::chat-flow.spec.ts"
    tests_control.record_run_result({
        "run_id": "run-good",
        "git_sha": "good111",
        "suites": {"playwright": {"status": "passed", "tests": [
            {"name": "chat-flow.spec.ts", "file": "chat-flow.spec.ts", "status": "passed"},
        ]}},
    })
    tests_control.record_run_result({
        "run_id": "run-bad",
        "git_sha": "bad222",
        "changed_files": ["frontend/packages/ui/src/components/ChatHistory.svelte"],
        "suites": {"playwright": {"status": "failed", "tests": [{
            "name": "chat-flow.spec.ts",
            "file": "chat-flow.spec.ts",
            "status": "failed",
            "error": "user@example.com failed with Bearer secret-token",
            "artifact_path": "/private/test-results/trace.zip",
        }]}},
    })

    bundle = tests_control.investigate_test(key, "run-bad")

    assert bundle["test_key"] == key
    assert bundle["source_run_id"] == "run-bad"
    assert bundle["current"]["status"] == "failed"
    assert "user@example.com" not in json.dumps(bundle)
    assert "secret-token" not in json.dumps(bundle)
    assert bundle["revisions"] == {
        "last_good": "good111",
        "first_bad_or_unknown": "bad222",
    }
    assert bundle["changed_files"] == ["frontend/packages/ui/src/components/ChatHistory.svelte"]
    assert bundle["artifacts"]["trace"]["status"] == "missing"
    assert bundle["artifacts"]["screenshot"]["status"] == "missing"
    assert bundle["artifacts"]["report"]["status"] == "missing"
    assert [preset["id"] for preset in bundle["diagnostic_presets"]] == ["backend-errors", "client-console"]
    for preset in bundle["diagnostic_presets"]:
        command = shlex.split(preset["command"])
        query_index = command.index("--query-json")
        query = json.loads(command[query_index + 1])
        assert query["stream"] in {"default", "client_console"}
        assert 0 < query["limit"] <= 50


def test_investigate_links_parent_incident_and_cli_command(tmp_path, monkeypatch, capsys):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result({
        "run_id": "run-worker-down",
        "prerequisites": [{
            "id": "task_worker",
            "status": "failed",
            "error": "worker unavailable",
            "dependant_test_keys": ["playwright::reminder-email.spec.ts"],
        }],
        "suites": {"playwright": {"status": "skipped", "tests": [
            {"name": "reminder-email.spec.ts", "file": "reminder-email.spec.ts", "status": "skipped"},
        ]}},
    })

    assert tests_control.main([
        "investigate",
        "--test-key", "playwright::reminder-email.spec.ts",
        "--run", "run-worker-down",
        "--json",
    ]) == 0
    bundle = json.loads(capsys.readouterr().out)

    assert bundle["parent_incident"]["key"] == "prerequisite::task_worker"
    assert bundle["parent_incident"]["status"] == "failed"


def test_require_active_lease_blocks_when_failures_exist(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())

    with pytest.raises(RuntimeError, match="No active failed-test lease"):
        tests_control.require_active_lease(session_id="s1")

    lease = tests_control.claim_next(session_id="s1")

    assert tests_control.require_active_lease(session_id="s1")["lease_id"] == lease["lease_id"]
    assert tests_control.active_lease_for_session(lease_id=lease["lease_id"])["lease_id"] == lease["lease_id"]


def test_e2e_deploy_gate_reports_preflight_not_test_success(tmp_path, monkeypatch, capsys):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    options = tests_control.ControlRunOptions(forwarded_args=["--spec", "chat-flow.spec.ts"], gate_deploy=True)

    monkeypatch.setattr(tests_control, "current_git_sha", lambda: "abcdef123456")
    monkeypatch.setattr(tests_control, "check_vercel_ready_for_commit", lambda commit: [])
    monkeypatch.setattr(tests_control, "check_dev_health_urls", lambda: [])

    tests_control.run_e2e_deploy_gate(options)

    output = capsys.readouterr().out
    assert "E2E deploy preflight: PASSED" in output
    assert "E2E deploy gate: PASSED" not in output


def test_e2e_deploy_gate_blocks_stale_vercel_commit(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    options = tests_control.ControlRunOptions(
        forwarded_args=["--spec", "chat-flow.spec.ts"],
        expected_commit="abcdef1",
        gate_deploy=True,
    )

    monkeypatch.setattr(tests_control, "current_git_sha", lambda: "abcdef123456")
    monkeypatch.setattr(tests_control, "check_vercel_ready_for_commit", lambda commit: ["not deployed"])
    monkeypatch.setattr(tests_control, "check_dev_health_urls", lambda: [])

    with pytest.raises(RuntimeError, match="not deployed"):
        tests_control.run_e2e_deploy_gate(options)


def test_e2e_deploy_gate_skips_non_playwright_targets(tmp_path, monkeypatch, capsys):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    options = tests_control.ControlRunOptions(forwarded_args=["--suite", "pytest"], gate_deploy=True)

    tests_control.run_e2e_deploy_gate(options)

    assert "SKIPPED" in capsys.readouterr().out


def test_complete_lease_require_passing_blocks_active_failure_group(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    tests_control.record_run_result(sample_run())
    lease = tests_control.claim_next(session_id="s1")

    with pytest.raises(RuntimeError, match="still failing"):
        tests_control.complete_lease(lease["lease_id"], commit="abc123d", require_passing=True)

    fixed_run = {
        "run_id": "2026-06-19T04:00:02Z",
        "git_sha": "def456abc",
        "git_branch": "dev",
        "environment": "development",
        "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0},
        "suites": {"playwright": {"status": "passed", "tests": [{"name": "account-recovery-flow.spec.ts", "file": "account-recovery-flow.spec.ts", "status": "passed"}]}},
    }
    tests_control.record_run_result(fixed_run)

    completed = tests_control.complete_lease(lease["lease_id"], commit="def456a", require_passing=True)

    assert completed["status"] == "completed"
    assert completed["completed_commit"] == "def456a"


def test_complete_debug_group_requires_member_test_keys(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    store = tests_control.get_store()
    store.create_debug_campaign({"campaign_key": "campaign", "status": "active", "session_id": tests_control.os.environ["OPENCODE_SESSION_ID"]})
    store.create_debug_group({"group_key": "group-empty", "campaign_key": "campaign", "member_test_keys": []})

    def fail_list_test_results(test_keys=None):
        raise AssertionError("empty debug groups must fail before test result history lookup")

    monkeypatch.setattr(store, "list_test_results", fail_list_test_results)

    with pytest.raises(RuntimeError, match="no member test keys recorded"):
        tests_control.complete_debug_group("group-empty", commit="abc123d")


def test_command_run_falls_back_to_timestamped_run_artifact(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    monkeypatch.setattr(tests_control, "RUN_TESTS_SCRIPT", tmp_path / "run_tests.py")

    run_data = {
        "run_id": "2026-06-19T05:00:02Z",
        "git_sha": "abc123def",
        "git_branch": "dev",
        "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        "suites": {},
    }

    def fake_run(command, cwd=None, env=None):
        tests_control.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (tests_control.RESULTS_DIR / "last-run.json").write_text(json.dumps(run_data), encoding="utf-8")
        (tests_control.RESULTS_DIR / "run-20260619T050002Z.json").write_text(json.dumps(run_data), encoding="utf-8")
        return tests_control.subprocess.CompletedProcess(command, 0)

    recorded_run_ids = []

    def fake_record_run_result(data):
        recorded_run_ids.append(data["run_id"])
        if len(recorded_run_ids) == 1:
            raise RuntimeError("temporary Directus failure")
        return {"summary": {}, "tests": {}}

    monkeypatch.setattr(tests_control.subprocess, "run", fake_run)
    monkeypatch.setattr(tests_control, "record_run_result", fake_record_run_result)

    assert tests_control.command_run(["--suite", "pytest"]) == 0
    assert recorded_run_ids == ["2026-06-19T05:00:02Z", "2026-06-19T05:00:02Z"]


def test_docker_resources_only_cover_dev_stack_dependent_runs(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)

    assert tests_control.docker_resources_for_run(["--spec", "chat-flow.spec.ts"]) == {"dev-stack"}
    assert tests_control.docker_resources_for_run(["--suite", "playwright"]) == {"dev-stack"}
    assert tests_control.docker_resources_for_run(["--suite", "cli"]) == {"dev-stack"}
    assert tests_control.docker_resources_for_run(["--suite", "pytest"]) == set()
    assert tests_control.docker_resources_for_run(["--suite", "vitest"]) == set()


# contract-test: infrastructure
def test_command_run_does_not_hold_dev_stack_lease_across_cli_runner(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    monkeypatch.setattr(tests_control, "RUN_TESTS_SCRIPT", tmp_path / "run_tests.py")
    monkeypatch.setattr(tests_control, "preflight_test_control_plane", lambda: None)
    monkeypatch.setattr(tests_control, "mark_running", lambda **_kwargs: None)
    monkeypatch.setattr(tests_control, "record_latest_run_artifact", lambda **_kwargs: "")
    acquired = []
    released = []
    monkeypatch.setattr(
        tests_control,
        "acquire_docker_test_lease",
        lambda lease_id, owner, resources: acquired.append((lease_id, owner, resources)),
    )
    monkeypatch.setattr(tests_control, "release_docker_test_lease", lambda lease_id: released.append(lease_id))
    monkeypatch.setattr(
        tests_control.subprocess,
        "run",
        lambda command, cwd=None, env=None: tests_control.subprocess.CompletedProcess(command, 1),
    )

    assert tests_control.command_run(["--suite", "cli"]) == 1
    assert acquired == []
    assert released == []


def test_command_run_marks_externally_held_playwright_account_lease(tmp_path, monkeypatch):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    monkeypatch.setattr(tests_control, "RUN_TESTS_SCRIPT", tmp_path / "run_tests.py")
    monkeypatch.setattr(tests_control, "preflight_test_control_plane", lambda: None)
    monkeypatch.setattr(tests_control, "mark_running", lambda **_kwargs: None)
    monkeypatch.setattr(tests_control, "record_latest_run_artifact", lambda **_kwargs: "abc123def")
    lease = ("playwright-account-25-test", "session-1", {"playwright-account:25"}, "exclusive")
    captured = {}
    released = []

    monkeypatch.setattr(
        tests_control,
        "acquire_standalone_playwright_account",
        lambda forwarded_args, *, owner: (forwarded_args, lease, 25),
    )
    monkeypatch.setattr(tests_control, "release_docker_test_lease", lambda lease_id: released.append(lease_id))

    def fake_run_with_resource_lease_heartbeats(command, *, env, leases):
        captured["command"] = command
        captured["env"] = env
        captured["leases"] = leases
        return 0

    monkeypatch.setattr(
        tests_control,
        "run_with_resource_lease_heartbeats",
        fake_run_with_resource_lease_heartbeats,
    )

    assert tests_control.command_run(["--spec", "chat-flow.spec.ts", "--account", "25"]) == 0
    assert captured["env"]["OPENMATES_TEST_ACCOUNT"] == "25"
    assert captured["env"][tests_control.PLAYWRIGHT_ACCOUNT_LEASE_HELD_ENV] == "1"
    assert captured["leases"] == [lease]
    assert released == ["playwright-account-25-test"]
