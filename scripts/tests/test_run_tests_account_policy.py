#!/usr/bin/env python3
"""
Regression tests for Playwright credential-isolation policy.

These tests keep auth-mutating E2E specs from silently using regular shared
accounts. They exercise pure orchestration helpers so the policy can be checked
without dispatching GitHub Actions or touching real credentials.

Architecture: docs/specs/e2e-credential-isolation/spec.yml
"""

# contract-test-file: tooling

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_TESTS_PATH = PROJECT_ROOT / "scripts" / "run_tests.py"


def load_run_tests_module():
    spec = importlib.util.spec_from_file_location("openmates_run_tests", RUN_TESTS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_test_video(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
            "color=blue:s=800x450:r=10:d=1", "-c:v", "libvpx", str(path),
        ],
        check=True,
        capture_output=True,
    )


def write_video_timing(artifact: Path, video_path: str, finalized_at_epoch_ms: int) -> None:
    (artifact / "playwright-video-timing.json").write_text(json.dumps({
        "schema_version": 1,
        "videos": [{
            "path": video_path,
            "finalized_at_epoch_ms": finalized_at_epoch_ms,
        }],
    }), encoding="utf-8")


def test_recording_artifacts_persist_proof_timeline_attachment(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    artifact = tmp_path / "artifact"
    artifact.mkdir(parents=True)
    proof_video_dir = artifact / "frontend" / "apps" / "web_app" / "test-results" / "proof-flow"
    proof_video_dir.mkdir(parents=True)
    write_test_video(proof_video_dir / "video.webm")
    write_video_timing(artifact, "frontend/apps/web_app/test-results/proof-flow/video.webm", 1767225601500)
    timeline = json.dumps({
        "schema_version": 2,
        "events": [
            {
                "id": "open",
                "kind": "action",
                "start_ms": 200,
                "end_ms": 400,
                "start_at_epoch_ms": 1767225600700,
                "end_at_epoch_ms": 1767225600900,
            },
            {
                "id": "welcome-visible",
                "kind": "checkpoint",
                "at_ms": 500,
                "captured_at_epoch_ms": 1767225601000,
            },
        ],
        "assertion_results": [{
            "id": "welcome.visible",
            "status": "passed",
            "at_ms": 450,
            "captured_at_epoch_ms": 1767225600950,
        }],
        "checkpoint_frames": [{
            "checkpoint": "welcome-visible",
            "at_ms": 500,
            "captured_at_epoch_ms": 1767225601000,
        }],
    }).encode()
    report = {
        "suites": [{
            "specs": [{
                "tests": [{
                    "results": [{
                        "status": "passed",
                        "startTime": "2026-01-01T00:00:00.000Z",
                        "duration": 1500,
                        "attachments": [
                            {
                                "name": "openmates-proof-timeline",
                                "contentType": "application/vnd.openmates.proof-timeline+json",
                                "body": base64.b64encode(timeline).decode("ascii"),
                            },
                            {
                                "name": "video",
                                "contentType": "video/webm",
                                "path": "/home/runner/work/OpenMates/OpenMates/frontend/apps/web_app/test-results/proof-flow/video.webm",
                            },
                        ]
                    }]
                }]
            }]
        }]
    }
    (artifact / "playwright.json").write_text(json.dumps(report), encoding="utf-8")
    recordings = tmp_path / "recordings"
    monkeypatch.setattr(run_tests, "TEST_RECORDINGS_DIR", recordings)

    persisted = run_tests.BatchRunner._persist_recording_artifacts("proof.spec.ts", artifact)

    expected = recordings / "proof" / "proof-timeline.json"
    assert persisted == str(expected)
    persisted_timeline = json.loads(expected.read_text(encoding="utf-8"))
    persisted_frame = recordings / "proof" / "proof-frames" / "welcome-visible.png"
    assert persisted_frame.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert persisted_timeline["checkpoint_frames"][0]["path"] == str(persisted_frame)
    assert persisted_timeline["checkpoint_frames"][0]["sha256"] == (
        "sha256:" + hashlib.sha256(persisted_frame.read_bytes()).hexdigest()
    )
    assert persisted_timeline["events"][0]["start_ms"] == pytest.approx(200, abs=100)
    assert persisted_timeline["events"][0]["end_ms"] == pytest.approx(400, abs=100)
    assert persisted_timeline["events"][1]["at_ms"] == pytest.approx(500, abs=100)
    assert persisted_timeline["assertion_results"][0]["at_ms"] == pytest.approx(450, abs=100)
    metadata = json.loads((recordings / "proof" / "artifact-meta.json").read_text(encoding="utf-8"))
    assert metadata["proof_timeline_file"] == "proof-timeline.json"
    assert metadata["proof_video_file"] == "videos/proof-flow.webm"


def test_recording_artifacts_extract_fixed_thumbnail_from_completed_video(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    artifact = tmp_path / "artifact"
    artifact.mkdir(parents=True)
    video_dir = artifact / "frontend" / "apps" / "web_app" / "test-results" / "signup-flow"
    video_dir.mkdir(parents=True)
    write_test_video(video_dir / "video.webm")
    write_video_timing(artifact, "frontend/apps/web_app/test-results/signup-flow/video.webm", 1767225601500)
    thumbnail_metadata = json.dumps({
        "schema_version": 2,
        "viewport": {"width": 1280, "height": 720},
        "clip": {"x": 320, "y": 160, "width": 640, "height": 400},
        "captured_at_epoch_ms": 1767225601000,
    }).encode()
    proof_timeline = json.dumps({
        "schema_version": 2,
        "events": [{
            "id": "thumbnail-ready",
            "kind": "checkpoint",
            "at_ms": 500,
            "captured_at_epoch_ms": 1767225601000,
        }],
        "checkpoint_frames": [{
            "checkpoint": "thumbnail-ready",
            "at_ms": 500,
            "captured_at_epoch_ms": 1767225601000,
        }],
    }).encode()
    report = {
        "suites": [{
            "specs": [{
                "tests": [{
                    "results": [
                        {
                            "status": "passed",
                            "startTime": "2026-01-01T00:00:00.000Z",
                            "duration": 100,
                            "attachments": [
                                {
                                    "name": "openmates-test-thumbnail-metadata",
                                    "contentType": "application/vnd.openmates.test-thumbnail+json",
                                    "body": base64.b64encode(thumbnail_metadata).decode("ascii"),
                                },
                                {
                                    "name": "video",
                                    "contentType": "video/webm",
                                    "path": "/home/runner/work/OpenMates/OpenMates/frontend/apps/web_app/test-results/signup-flow/video.webm",
                                },
                                {
                                    "name": "openmates-proof-timeline",
                                    "contentType": "application/vnd.openmates.proof-timeline+json",
                                    "body": base64.b64encode(proof_timeline).decode("ascii"),
                                },
                            ],
                        },
                    ]
                }]
            }]
        }]
    }
    (artifact / "playwright.json").write_text(json.dumps(report), encoding="utf-8")
    recordings = tmp_path / "recordings"
    monkeypatch.setattr(run_tests, "TEST_RECORDINGS_DIR", recordings)

    run_tests.BatchRunner._persist_recording_artifacts("signup.spec.ts", artifact)

    thumbnail = recordings / "signup" / "thumbnail.png"
    thumbnail_bytes = thumbnail.read_bytes()
    assert thumbnail_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", thumbnail_bytes[16:24]) == (1280, 800)
    metadata = json.loads((recordings / "signup" / "artifact-meta.json").read_text(encoding="utf-8"))
    assert metadata["thumbnail_file"] == "thumbnail.png"
    assert metadata["thumbnail_source"] == "video_frame"


def test_recording_artifacts_select_terminal_passing_proof_retry(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    artifact = tmp_path / "artifact"
    artifact.mkdir(parents=True)
    proof_video_dir = artifact / "frontend" / "apps" / "web_app" / "test-results" / "proof-retry"
    proof_video_dir.mkdir(parents=True)
    write_test_video(proof_video_dir / "video.webm")
    write_video_timing(artifact, "frontend/apps/web_app/test-results/proof-retry/video.webm", 1767225601500)

    def attachments(checkpoint: str, captured_at_ms: int) -> list[dict]:
        timeline = json.dumps({
            "schema_version": 2,
            "checkpoint_frames": [{
                "checkpoint": checkpoint,
                "at_ms": 500,
                "captured_at_epoch_ms": captured_at_ms,
            }],
        }).encode()
        return [
            {
                "name": "openmates-proof-timeline",
                "contentType": "application/vnd.openmates.proof-timeline+json",
                "body": base64.b64encode(timeline).decode("ascii"),
            },
            {
                "name": "video",
                "contentType": "video/webm",
                "path": "/home/runner/work/OpenMates/OpenMates/frontend/apps/web_app/test-results/proof-retry/video.webm",
            },
        ]

    report = {
        "suites": [{
            "specs": [{
                "tests": [{
                    "results": [
                        {
                            "status": "failed",
                            "startTime": "2026-01-01T00:00:00.000Z",
                            "duration": 1500,
                            "attachments": attachments("failed-attempt", 1767225600800),
                        },
                        {
                            "status": "passed",
                            "startTime": "2026-01-01T00:00:00.000Z",
                            "duration": 1500,
                            "attachments": attachments("passed-attempt", 1767225601000),
                        },
                    ]
                }]
            }]
        }]
    }
    (artifact / "playwright.json").write_text(json.dumps(report), encoding="utf-8")
    recordings = tmp_path / "recordings"
    monkeypatch.setattr(run_tests, "TEST_RECORDINGS_DIR", recordings)

    run_tests.BatchRunner._persist_recording_artifacts("proof.spec.ts", artifact)

    timeline = json.loads((recordings / "proof" / "proof-timeline.json").read_text(encoding="utf-8"))
    assert timeline["checkpoint_frames"][0]["checkpoint"] == "passed-attempt"


def test_git_info_uses_exact_deployed_session_subject(monkeypatch):
    run_tests = load_run_tests_module()
    monkeypatch.setenv("OPENMATES_TEST_SUBJECT_COMMIT", "abcdef1234567890")

    assert run_tests._git_info() == ("abcdef123", "dev")


def test_daily_git_info_refreshes_origin_dev_subject(monkeypatch):
    run_tests = load_run_tests_module()
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_check_output(command, **_kwargs):
        commands.append(command)
        return "123456789abcdef123456789abcdef123456789a\n"

    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)
    monkeypatch.setattr(run_tests.subprocess, "check_output", fake_check_output)

    assert run_tests._daily_git_info("oldsha123", "dev") == ("123456789", "dev")
    assert commands == [
        [
            "git", "-C", str(PROJECT_ROOT), "fetch", "--quiet", "origin",
            "+dev:refs/remotes/origin/dev",
        ],
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "origin/dev"],
    ]


def test_daily_git_info_preserves_explicit_subject(monkeypatch):
    run_tests = load_run_tests_module()
    monkeypatch.setenv("OPENMATES_TEST_SUBJECT_COMMIT", "abcdef1234567890")

    assert run_tests._daily_git_info("abcdef123", "dev") == ("abcdef123", "dev")


def test_worktree_vercel_gate_reads_shared_control_plane_config(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    control_plane_root = tmp_path / "OpenMates"
    project_dir = control_plane_root / "frontend" / "apps" / "web_app" / ".vercel"
    project_dir.mkdir(parents=True)
    (control_plane_root / ".env").write_text("VERCEL_TOKEN=<TOKEN>\n")
    (project_dir / "project.json").write_text(json.dumps({"orgId": "team", "projectId": "project"}))

    monkeypatch.setattr(run_tests, "CONTROL_PLANE_ROOT", control_plane_root)

    assert run_tests._read_env_file() == {"VERCEL_TOKEN": "<TOKEN>"}
    assert run_tests._vercel_project_config() == ("team", "project")


def test_reserved_specs_use_reserved_accounts_for_single_spec_dispatch():
    run_tests = load_run_tests_module()

    for spec_name, expected_account in run_tests.RESERVED_PLAYWRIGHT_ACCOUNTS_BY_SPEC.items():
        plan = run_tests.build_playwright_dispatch_plan([spec_name], batch_size=20)
        assert plan == [(0, spec_name, expected_account)]


def test_regular_specs_use_normal_accounts_and_skip_reserved_slots():
    run_tests = load_run_tests_module()
    regular_specs = [f"regular-{index}.spec.ts" for index in range(20)]

    plan = run_tests.build_playwright_dispatch_plan(regular_specs, batch_size=20)
    assigned_accounts = [account for _batch, _spec, account in plan]

    assert run_tests.MAX_ACCOUNTS == 27
    assert assigned_accounts == [*range(1, 14), *range(21, 28)]
    assert assigned_accounts == list(run_tests.NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS)
    assert not set(assigned_accounts) & set(run_tests.RESERVED_PLAYWRIGHT_ACCOUNT_SLOTS)


def test_batch_size_is_capped_to_normal_account_pool():
    run_tests = load_run_tests_module()
    regular_specs = [f"regular-{index}.spec.ts" for index in range(21)]

    plan = run_tests.build_playwright_dispatch_plan(regular_specs, batch_size=20)

    assert plan[19] == (0, "regular-19.spec.ts", 27)
    assert plan[20] == (1, "regular-20.spec.ts", 1)


def test_gift_card_fixture_is_seeded_only_for_dev_redemption_spec(monkeypatch):
    run_tests = load_run_tests_module()
    calls: list[str] = []

    def fake_seed(spec_name: str):
        calls.append(spec_name)
        return run_tests.SeededGiftCard(
            spec=spec_name,
            code="E2E2-TEST-CARD",
            directus_id="gift-card-id",
            credits_value=run_tests.E2E_GIFT_CARD_REDEMPTION_CREDITS,
        )

    monkeypatch.setattr(run_tests, "_seed_e2e_gift_card", fake_seed)

    assert run_tests._seed_playwright_fixtures_for_specs(
        [run_tests.E2E_GIFT_CARD_REDEMPTION_SPEC],
        "production",
    ) == {}
    assert calls == []

    fixtures = run_tests._seed_playwright_fixtures_for_specs(
        ["regular.spec.ts", run_tests.E2E_GIFT_CARD_REDEMPTION_SPEC],
        "development",
    )

    assert calls == [run_tests.E2E_GIFT_CARD_REDEMPTION_SPEC]
    assert fixtures[run_tests.E2E_GIFT_CARD_REDEMPTION_SPEC].code == "E2E2-TEST-CARD"


def test_seeded_gift_card_code_is_passed_to_matching_dispatch(monkeypatch):
    run_tests = load_run_tests_module()
    dispatches: list[tuple[str, str | None]] = []

    class FakeClient:
        last_dispatch_error = ""

        def dispatch_spec(self, spec, _account, *_args, seeded_gift_card_code=None, **_kwargs):
            dispatches.append((spec, seeded_gift_card_code))
            return len(dispatches)

        def wait_for_runs(self, run_ids, _fail_fast):
            return {run_id: {"status": "completed", "conclusion": "success"} for run_id in run_ids}

        def download_artifact(self, *_args, **_kwargs):
            return None

    runner = run_tests.BatchRunner(
        client=FakeClient(),
        specs=["regular.spec.ts", run_tests.E2E_GIFT_CARD_REDEMPTION_SPEC],
        batch_size=2,
        fail_fast=True,
        seeded_gift_cards={
            run_tests.E2E_GIFT_CARD_REDEMPTION_SPEC: run_tests.SeededGiftCard(
                spec=run_tests.E2E_GIFT_CARD_REDEMPTION_SPEC,
                code="E2E2-TEST-CARD",
                directus_id="gift-card-id",
                credits_value=run_tests.E2E_GIFT_CARD_REDEMPTION_CREDITS,
            )
        },
    )

    result = runner.run_all_batches()

    assert result.status == "passed"
    assert sorted(dispatches) == sorted([
        ("regular.spec.ts", None),
        (run_tests.E2E_GIFT_CARD_REDEMPTION_SPEC, "E2E2-TEST-CARD"),
    ])


def test_seeded_gift_card_code_is_not_passed_to_unrelated_dispatch(monkeypatch):
    run_tests = load_run_tests_module()
    dispatches: list[tuple[str, str | None]] = []

    class FakeClient:
        last_dispatch_error = ""

        def dispatch_spec(self, spec, _account, *_args, seeded_gift_card_code=None, **_kwargs):
            dispatches.append((spec, seeded_gift_card_code))
            return len(dispatches)

        def wait_for_runs(self, run_ids, _fail_fast):
            return {run_id: {"status": "completed", "conclusion": "success"} for run_id in run_ids}

        def download_artifact(self, *_args, **_kwargs):
            return None

    runner = run_tests.BatchRunner(
        client=FakeClient(),
        specs=["regular.spec.ts"],
        batch_size=1,
        fail_fast=True,
        seeded_gift_cards={
            run_tests.E2E_GIFT_CARD_REDEMPTION_SPEC: run_tests.SeededGiftCard(
                spec=run_tests.E2E_GIFT_CARD_REDEMPTION_SPEC,
                code="E2E2-TEST-CARD",
                directus_id="gift-card-id",
                credits_value=run_tests.E2E_GIFT_CARD_REDEMPTION_CREDITS,
            )
        },
    )

    result = runner.run_all_batches()

    assert result.status == "passed"
    assert dispatches == [("regular.spec.ts", None)]


def test_cancelled_playwright_dispatch_is_not_recorded_as_passed():
    run_tests = load_run_tests_module()

    class FakeClient:
        last_dispatch_error = ""

        def dispatch_spec(self, *_args, **_kwargs):
            return 123

        def wait_for_runs(self, run_ids, _fail_fast):
            return {run_id: {"status": "completed", "conclusion": "cancelled"} for run_id in run_ids}

        def download_artifact(self, *_args, **_kwargs):
            return None

    runner = run_tests.BatchRunner(
        client=FakeClient(),
        specs=["regular.spec.ts"],
        batch_size=1,
        fail_fast=True,
    )

    result = runner.run_all_batches()

    assert result.status == "failed"
    assert result.tests[0]["status"] == "not_started"
    assert result.tests[0]["error"] == "Run was cancelled"


def test_dispatch_plan_can_use_preflight_available_normal_slots():
    run_tests = load_run_tests_module()
    regular_specs = [f"regular-{index}.spec.ts" for index in range(5)]

    plan = run_tests.build_playwright_dispatch_plan(
        regular_specs,
        batch_size=20,
        normal_account_slots=(1, 2),
    )

    assert plan == [
        (0, "regular-0.spec.ts", 1),
        (0, "regular-1.spec.ts", 2),
        (1, "regular-2.spec.ts", 1),
        (1, "regular-3.spec.ts", 2),
        (2, "regular-4.spec.ts", 1),
    ]


def test_preflight_availability_reduces_normal_pool_and_blocks_reserved_specs():
    run_tests = load_run_tests_module()
    preflight_results = [
        run_tests.SpecResult(name=run_tests.ACCOUNT_PREFLIGHT_SPEC, status="passed", account=1),
        run_tests.SpecResult(name=run_tests.ACCOUNT_PREFLIGHT_SPEC, status="passed", account=2),
        run_tests.SpecResult(name=run_tests.ACCOUNT_PREFLIGHT_SPEC, status="skipped", account=3),
        run_tests.SpecResult(name=run_tests.ACCOUNT_PREFLIGHT_SPEC, status="skipped", account=14),
        run_tests.SpecResult(name=run_tests.ACCOUNT_PREFLIGHT_SPEC, status="passed", account=15),
    ]

    runnable, blocked, normal_slots, reason = run_tests._apply_preflight_account_availability(
        [
            "regular.spec.ts",
            "account-recovery-flow.spec.ts",
            "backup-code-login-flow.spec.ts",
        ],
        preflight_results,
    )

    assert runnable == ["regular.spec.ts", "backup-code-login-flow.spec.ts"]
    assert normal_slots == (1, 2)
    assert len(blocked) == 1
    assert blocked[0].file == "account-recovery-flow.spec.ts"
    assert blocked[0].status == "failed"
    assert blocked[0].account == 14
    assert reason is not None
    assert "Unavailable normal account slot(s)" in reason
    assert "account-recovery-flow.spec.ts (slot 14)" in reason


def test_single_regular_spec_falls_back_to_healthy_normal_account(monkeypatch):
    run_tests = load_run_tests_module()
    captured: dict[str, object] = {}
    preflight_calls: list[list[int] | None] = []

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.max_concurrent = 20
    orchestrator.dry_run = False
    orchestrator.environment = "production"
    orchestrator.git_sha = "abc123"
    orchestrator.dot_env = {}
    orchestrator.spec = "regular.spec.ts"
    orchestrator.account = None
    orchestrator.create_account_slot = None
    orchestrator.only_failed = False
    orchestrator.fail_fast = True
    orchestrator.use_mocks = True
    orchestrator.record_live_fixtures = False
    orchestrator.proof_video_profile = ""
    orchestrator._discover_specs = lambda: ["regular.spec.ts"]

    def fake_preflight(_client, accounts=None):
        preflight_calls.append(accounts)
        if accounts == [1]:
            return run_tests.SuiteResult(
                status="failed",
                tests=[{
                    "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                    "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                    "status": "failed",
                    "account": 1,
                }],
                reason="slot 1 failed",
            )
        return run_tests.SuiteResult(
            status="passed",
            tests=[{
                "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                "status": "passed",
                "account": 2,
            }],
        )

    class FakeBatchRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run_all_batches(self):
            return run_tests.SuiteResult(
                status="passed",
                tests=[{"name": "regular.spec.ts", "file": "regular.spec.ts", "status": "passed"}],
            )

    monkeypatch.setattr(orchestrator, "_run_account_preflight", fake_preflight)
    monkeypatch.setattr(run_tests, "_single_spec_fallback_accounts", lambda _account: [2, 3, 4])
    monkeypatch.setattr(run_tests, "GitHubActionsClient", lambda **_kwargs: object())
    monkeypatch.setattr(run_tests, "BatchRunner", FakeBatchRunner)

    result = orchestrator._run_playwright()

    assert result.status == "passed"
    assert preflight_calls == [[1], [2, 3, 4]]
    assert captured["normal_account_slots"] == (2,)
    assert result.reason == "Selected normal account slot 1 failed preflight; using fallback slot 2 for regular.spec.ts"


def test_single_spec_fallback_accounts_are_bounded():
    run_tests = load_run_tests_module()

    failed_account = run_tests.NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS[0]
    fallback_accounts = run_tests._single_spec_fallback_accounts(failed_account)

    assert len(fallback_accounts) == run_tests.SINGLE_SPEC_PREFLIGHT_FALLBACK_LIMIT
    assert failed_account not in fallback_accounts
    assert fallback_accounts == list(run_tests.NORMAL_PLAYWRIGHT_ACCOUNT_SLOTS[1:4])


def test_single_spec_reuses_wrapper_account_lease(monkeypatch):
    run_tests = load_run_tests_module()
    captured: dict[str, object] = {}

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.max_concurrent = 20
    orchestrator.dry_run = False
    orchestrator.environment = "production"
    orchestrator.git_sha = "abc123"
    orchestrator.dot_env = {}
    orchestrator.spec = "regular.spec.ts"
    orchestrator.account = 22
    orchestrator.create_account_slot = None
    orchestrator.only_failed = False
    orchestrator.fail_fast = True
    orchestrator.use_mocks = True
    orchestrator.record_live_fixtures = False
    orchestrator.proof_video_profile = ""
    orchestrator._discover_specs = lambda: ["regular.spec.ts"]
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT", "22")

    def fake_preflight(_client, accounts=None):
        assert accounts == [22]
        return run_tests.SuiteResult(
            status="passed",
            tests=[{
                "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                "status": "passed",
                "account": 22,
            }],
        )

    class FakeBatchRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run_all_batches(self):
            return run_tests.SuiteResult(
                status="passed",
                tests=[{"name": "regular.spec.ts", "file": "regular.spec.ts", "status": "passed"}],
            )

    monkeypatch.setattr(orchestrator, "_run_account_preflight", fake_preflight)
    monkeypatch.setattr(run_tests, "GitHubActionsClient", lambda **_kwargs: object())
    monkeypatch.setattr(run_tests, "BatchRunner", FakeBatchRunner)

    result = orchestrator._run_playwright()

    assert result.status == "passed"
    assert captured["normal_account_slots"] == (22,)
    assert captured["coordinate_accounts"] is False


def test_only_failed_batch_preflights_and_skips_unhealthy_normal_account(monkeypatch):
    run_tests = load_run_tests_module()
    captured: dict[str, object] = {}
    preflight_calls: list[list[int] | None] = []

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.max_concurrent = 20
    orchestrator.dry_run = False
    orchestrator.environment = "production"
    orchestrator.git_sha = "abc123"
    orchestrator.dot_env = {}
    orchestrator.spec = None
    orchestrator.account = None
    orchestrator.create_account_slot = None
    orchestrator.only_failed = True
    orchestrator.fail_fast = False
    orchestrator.use_mocks = True
    orchestrator.record_live_fixtures = False
    orchestrator.proof_video_profile = ""
    orchestrator._discover_specs = lambda: ["regular-a.spec.ts", "regular-b.spec.ts"]
    orchestrator._merge_cookie_audits = lambda: None

    def fake_preflight(_client, accounts=None):
        preflight_calls.append(accounts)
        return run_tests.SuiteResult(
            status="failed",
            tests=[
                {
                    "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                    "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                    "status": "failed",
                    "account": 1,
                },
                {
                    "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                    "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                    "status": "passed",
                    "account": 2,
                },
            ],
            reason="slot 1 failed",
        )

    class FakeBatchRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run_all_batches(self):
            return run_tests.SuiteResult(
                status="passed",
                tests=[
                    {"name": "regular-a.spec.ts", "file": "regular-a.spec.ts", "status": "passed"},
                    {"name": "regular-b.spec.ts", "file": "regular-b.spec.ts", "status": "passed"},
                ],
            )

    monkeypatch.setattr(orchestrator, "_run_account_preflight", fake_preflight)
    monkeypatch.setattr(run_tests, "GitHubActionsClient", lambda **_kwargs: object())
    monkeypatch.setattr(run_tests, "BatchRunner", FakeBatchRunner)

    result = orchestrator._run_playwright()

    assert result.status == "passed"
    assert preflight_calls == [[1, 2]]
    assert captured["normal_account_slots"] == (2,)
    assert result.reason is not None
    assert "Unavailable normal account slot(s)" in result.reason


def test_single_campaign_spec_preflights_only_its_planned_account():
    run_tests = load_run_tests_module()

    assert run_tests._preflight_accounts_for_specs(["import-chats.spec.ts"], 20) == [1]


def test_cli_integration_falls_back_to_healthy_normal_account(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    preflight_calls: list[list[int] | None] = []
    dispatch_accounts: list[int] = []

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.dry_run = False
    orchestrator.environment = "development"
    orchestrator.git_sha = "abc123"
    orchestrator.use_mocks = True
    orchestrator.record_live_fixtures = False
    captured_git_sha = {}

    def fake_preflight(_client, accounts=None):
        preflight_calls.append(accounts)
        if accounts == [1]:
            return run_tests.SuiteResult(
                status="failed",
                tests=[{
                    "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                    "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                    "status": "failed",
                    "account": 1,
                }],
                duration_seconds=1.0,
                reason="slot 1 failed",
            )
        return run_tests.SuiteResult(
            status="passed",
            tests=[{
                "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
                "status": "passed",
                "account": 2,
            }],
            duration_seconds=2.0,
        )

    class FakeClient:
        last_dispatch_error = ""

        def __init__(self, **kwargs):
            captured_git_sha.update(kwargs)

        def dispatch_spec(self, _spec, account, **_kwargs):
            dispatch_accounts.append(account)
            return 456

        def wait_for_runs(self, run_ids, **_kwargs):
            return {run_ids[0]: {"status": "completed", "conclusion": "success"}}

        def download_artifact(self, _run_id, _artifact_name, artifact_dir):
            results_dir = artifact_dir / "test-results"
            results_dir.mkdir(parents=True)
            (results_dir / "cli-integration.json").write_text(
                json.dumps({
                    "tests": [{
                        "nodeid": "cli-integration/code-docs/preflight",
                        "outcome": "passed",
                        "duration": 0.1,
                    }]
                }),
                encoding="utf-8",
            )
            return artifact_dir

        def get_failed_job_error(self, _run_id):
            return None

    monkeypatch.setattr(orchestrator, "_run_account_preflight", fake_preflight)
    monkeypatch.setattr(run_tests, "_full_git_sha", lambda sha: f"full-{sha}")
    monkeypatch.setattr(run_tests, "_single_spec_fallback_accounts", lambda _account: [2, 3, 4])
    monkeypatch.setattr(run_tests, "GitHubActionsClient", FakeClient)
    monkeypatch.setattr(run_tests.tempfile, "mkdtemp", lambda prefix: str(tmp_path / prefix))

    result = orchestrator._run_cli_integration()

    assert result.status == "passed"
    assert preflight_calls == [[1], [2, 3, 4]]
    assert dispatch_accounts == [2]
    assert captured_git_sha == {"git_sha": "full-abc123"}
    assert result.tests[0] == {
        "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
        "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
        "status": "passed",
        "duration_seconds": 3.0,
    }
    assert result.reason == "Selected normal account slot 1 failed preflight; using fallback slot 2 for CLI integration"


def test_discover_single_spec_blocks_missing_file(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "SPEC_DIR", tmp_path / "tests")

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.spec = "missing.spec.ts"

    try:
        orchestrator._discover_specs()
    except RuntimeError as exc:
        assert "Spec file not found" in str(exc)
    else:
        raise AssertionError("missing spec should block dispatch")


def test_discover_single_spec_blocks_untracked_file(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    spec_dir = tmp_path / "frontend" / "apps" / "web_app" / "tests"
    spec_dir.mkdir(parents=True)
    spec_path = spec_dir / "local-only.spec.ts"
    spec_path.write_text("import { test } from '@playwright/test';\n", encoding="utf-8")
    monkeypatch.setattr(run_tests, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(run_tests, "SPEC_DIR", spec_dir)

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.spec = "local-only.spec.ts"

    try:
        orchestrator._discover_specs()
    except RuntimeError as exc:
        assert "Spec file is untracked" in str(exc)
    else:
        raise AssertionError("untracked spec should block dispatch")


def test_deployed_single_spec_can_run_from_session_worktree(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    spec_dir = tmp_path / "frontend" / "apps" / "web_app" / "tests"
    spec_dir.mkdir(parents=True)
    spec_path = spec_dir / "deployed.spec.ts"
    spec_path.write_text("import { test } from '@playwright/test';\n", encoding="utf-8")
    monkeypatch.setattr(run_tests, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(run_tests, "SPEC_DIR", spec_dir)

    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0 if command[1] == "cat-file" else 1})()

    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)

    assert run_tests._validate_requested_playwright_spec("deployed.spec.ts", "abc123") == ""
    assert calls[-1] == [
        "git",
        "cat-file",
        "-e",
        "abc123:frontend/apps/web_app/tests/deployed.spec.ts",
    ]


def test_single_reserved_spec_does_not_fall_back_when_reserved_account_fails(monkeypatch):
    run_tests = load_run_tests_module()
    preflight_calls: list[list[int] | None] = []

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.max_concurrent = 20
    orchestrator.dry_run = False
    orchestrator.environment = "production"
    orchestrator.git_sha = "abc123"
    orchestrator.dot_env = {}
    orchestrator.spec = "account-recovery-flow.spec.ts"
    orchestrator.account = None
    orchestrator.create_account_slot = None
    orchestrator.only_failed = False
    orchestrator.fail_fast = True
    orchestrator.use_mocks = True
    orchestrator._discover_specs = lambda: ["account-recovery-flow.spec.ts"]

    expected = run_tests.SuiteResult(
        status="failed",
        tests=[{
            "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
            "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
            "status": "failed",
            "account": 14,
        }],
        reason="slot 14 failed",
    )

    def fake_preflight(_client, accounts=None):
        preflight_calls.append(accounts)
        return expected

    monkeypatch.setattr(orchestrator, "_run_account_preflight", fake_preflight)
    monkeypatch.setattr(run_tests, "GitHubActionsClient", lambda **_kwargs: object())

    result = orchestrator._run_playwright()

    assert result is expected
    assert preflight_calls == [[14]]


def test_single_account_preflight_honors_explicit_account(monkeypatch):
    run_tests = load_run_tests_module()
    preflight_calls: list[list[int] | None] = []

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.max_concurrent = 20
    orchestrator.dry_run = False
    orchestrator.environment = "production"
    orchestrator.git_sha = "abc123"
    orchestrator.dot_env = {}
    orchestrator.spec = run_tests.ACCOUNT_PREFLIGHT_SPEC
    orchestrator.account = 19
    orchestrator.create_account_slot = None
    orchestrator.only_failed = False
    orchestrator.fail_fast = True
    orchestrator.use_mocks = True
    orchestrator._discover_specs = lambda: [run_tests.ACCOUNT_PREFLIGHT_SPEC]

    expected = run_tests.SuiteResult(
        status="passed",
        tests=[{
            "name": run_tests.ACCOUNT_PREFLIGHT_SPEC,
            "file": run_tests.ACCOUNT_PREFLIGHT_SPEC,
            "status": "passed",
            "account": 19,
        }],
    )

    def fake_preflight(_client, accounts=None):
        preflight_calls.append(accounts)
        return expected

    class UnexpectedBatchRunner:
        def __init__(self, **_kwargs):
            raise AssertionError("explicit account preflight should not dispatch through BatchRunner")

    monkeypatch.setattr(orchestrator, "_run_account_preflight", fake_preflight)
    monkeypatch.setattr(run_tests, "GitHubActionsClient", lambda **_kwargs: object())
    monkeypatch.setattr(run_tests, "BatchRunner", UnexpectedBatchRunner)

    result = orchestrator._run_playwright()

    assert result is expected
    assert preflight_calls == [[19]]


def test_hourly_dev_specs_exist():
    run_tests = load_run_tests_module()
    tests_dir = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"

    missing_specs = [
        spec_name
        for spec_name in run_tests.HOURLY_DEV_SPECS
        if not (tests_dir / spec_name).is_file()
    ]

    assert missing_specs == []


def test_dispatch_run_matching_uses_unique_token():
    run_tests = load_run_tests_module()

    runs = [
        {"databaseId": 111, "displayTitle": "Playwright: chat-flow.spec.ts account 1 rt-other"},
        {"databaseId": 222, "displayTitle": "Playwright: test-account-preflight.spec.ts account 11 rt-target"},
    ]

    assert run_tests._matching_dispatched_run_id(runs, "rt-target") == 222
    assert run_tests._matching_dispatched_run_id(runs, "rt-missing") is None


def test_full_git_sha_expands_short_display_ref(monkeypatch):
    run_tests = load_run_tests_module()
    full_sha = "a" * 40
    commands: list[list[str]] = []

    def fake_check_output(command, **_kwargs):
        commands.append(command)
        return full_sha

    monkeypatch.setattr(run_tests.subprocess, "check_output", fake_check_output)

    assert run_tests._full_git_sha("abc123") == full_sha
    assert commands == [["git", "-C", str(PROJECT_ROOT), "rev-parse", "abc123"]]


def test_canceled_vercel_deployment_retries_once_before_ready(monkeypatch):
    run_tests = load_run_tests_module()
    deployments = iter([
        {"id": "dpl-canceled", "state": "CANCELED", "errorMessage": "transient cancellation"},
        {"id": "dpl-canceled", "state": "CANCELED", "errorMessage": "transient cancellation"},
        {"id": "dpl-ready", "state": "READY"},
    ])
    redeployed: list[str] = []

    monkeypatch.setattr(run_tests, "_vercel_project_config", lambda: ("team", "project"))
    monkeypatch.setattr(run_tests, "_latest_vercel_deployment_for_sha", lambda *_args: next(deployments))
    monkeypatch.setattr(
        run_tests,
        "_redeploy_vercel_deployment",
        lambda _token, _team, deployment_id: redeployed.append(deployment_id),
        raising=False,
    )
    monkeypatch.setattr(run_tests.time, "sleep", lambda _seconds: None)

    ready, reason = run_tests._wait_for_vercel_deployment("abc123", {"VERCEL_TOKEN": "test-token"})

    assert ready is True
    assert reason == ""
    assert redeployed == ["dpl-canceled"]


def test_undispatched_specs_are_recorded_as_not_started():
    run_tests = load_run_tests_module()

    tests = run_tests._not_started_playwright_specs(
        ["signup-flow-passkey.spec.ts", "settings-buy-credits-stripe-eu.spec.ts", "chat-flow.spec.ts"],
        "Vercel deployment dpl-canceled was canceled",
    )

    assert [test["name"] for test in tests] == [
        "signup-flow-passkey.spec.ts",
        "settings-buy-credits-stripe-eu.spec.ts",
        "chat-flow.spec.ts",
    ]
    assert {test["status"] for test in tests} == {"not_started"}
    assert {test["error"] for test in tests} == {"Vercel deployment dpl-canceled was canceled"}


def test_playwright_gate_reports_every_undispatched_spec(monkeypatch):
    run_tests = load_run_tests_module()
    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.max_concurrent = 1
    orchestrator.dry_run = False
    orchestrator.environment = "development"
    orchestrator.use_mocks = True
    orchestrator.record_live_fixtures = False
    orchestrator.git_sha = "abc123"
    orchestrator.dot_env = {}
    orchestrator._discover_specs = lambda: ["signup-flow-passkey.spec.ts", "chat-flow.spec.ts"]
    monkeypatch.setattr(
        run_tests,
        "_wait_for_vercel_deployment",
        lambda _git_sha, _dot_env: (False, "Vercel deployment dpl-canceled was canceled"),
    )
    monkeypatch.setattr(run_tests, "_development_backend_live_mock_preflight_error", lambda: None)

    result = orchestrator._run_playwright()

    assert result.status == "failed"
    assert result.tests[0]["name"] == "vercel-deployment-gate"
    assert [test["status"] for test in result.tests[1:]] == ["not_started", "not_started"]
    assert [test["name"] for test in result.tests[1:]] == [
        "signup-flow-passkey.spec.ts",
        "chat-flow.spec.ts",
    ]


def test_dispatch_passes_full_checkout_ref_to_workflow(monkeypatch):
    run_tests = load_run_tests_module()
    commands: list[list[str]] = []

    monkeypatch.setattr(run_tests.GitHubActionsClient, "_check_gh", lambda _self: None)
    monkeypatch.setattr(run_tests.time, "sleep", lambda _seconds: None)

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    client = run_tests.GitHubActionsClient(
        git_sha="abc123",
    )
    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)
    monkeypatch.setattr(
        client,
        "_recent_runs",
        lambda limit=50: [{
            "databaseId": 123,
            "displayTitle": next(
                item.removeprefix("dispatch_token=")
                for item in commands[0]
                if item.startswith("dispatch_token=")
            ),
        }],
    )

    assert client.dispatch_spec("chat-flow.spec.ts", account=1) == 123
    assert "checkout_ref=abc123" in commands[0]
    assert "allow_credential_updates=true" in commands[0]


def test_dispatch_can_disable_credential_updates_for_release_bootstrap(monkeypatch):
    run_tests = load_run_tests_module()
    commands: list[list[str]] = []

    monkeypatch.setattr(run_tests.GitHubActionsClient, "_check_gh", lambda _self: None)
    monkeypatch.setattr(run_tests.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        run_tests.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command)
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    client = run_tests.GitHubActionsClient(git_sha="abc123")
    monkeypatch.setattr(
        client,
        "_recent_runs",
        lambda limit=50: [{
            "databaseId": 123,
            "displayTitle": next(
                item.removeprefix("dispatch_token=")
                for item in commands[0]
                if item.startswith("dispatch_token=")
            ),
        }],
    )

    assert client.dispatch_spec(
        "signup-flow-stripe-managed.spec.ts",
        account=2,
        allow_credential_updates=False,
    ) == 123
    assert "allow_credential_updates=false" in commands[0]


def test_dispatch_can_pass_create_account_slot_to_workflow(monkeypatch):
    run_tests = load_run_tests_module()
    commands: list[list[str]] = []

    monkeypatch.setattr(run_tests.GitHubActionsClient, "_check_gh", lambda _self: None)
    monkeypatch.setattr(run_tests.time, "sleep", lambda _seconds: None)

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    client = run_tests.GitHubActionsClient()
    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)
    monkeypatch.setattr(
        client,
        "_recent_runs",
        lambda limit=50: [{
            "databaseId": 123,
            "displayTitle": next(
                item.removeprefix("dispatch_token=")
                for item in commands[0]
                if item.startswith("dispatch_token=")
            ),
        }],
    )

    assert client.dispatch_spec(
        run_tests.PROVISION_AUTH_ACCOUNTS_SPEC,
        account=19,
        create_account_slot=19,
    ) == 123
    assert "create_account_slot=19" in commands[0]


def test_dispatch_can_record_live_fixtures(monkeypatch):
    run_tests = load_run_tests_module()
    commands: list[list[str]] = []

    monkeypatch.setattr(run_tests.GitHubActionsClient, "_check_gh", lambda _self: None)
    monkeypatch.setattr(run_tests.time, "sleep", lambda _seconds: None)

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    client = run_tests.GitHubActionsClient()
    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)
    monkeypatch.setattr(
        client,
        "_recent_runs",
        lambda limit=50: [{
            "databaseId": 123,
            "displayTitle": next(
                item.removeprefix("dispatch_token=")
                for item in commands[0]
                if item.startswith("dispatch_token=")
            ),
        }],
    )

    assert client.dispatch_spec(
        "models3d-search.spec.ts",
        account=1,
        record_live_fixtures=True,
    ) == 123
    assert "record_live_fixtures=true" in commands[0]


def test_dispatch_can_request_exact_proof_video_profiles(monkeypatch):
    run_tests = load_run_tests_module()
    commands: list[list[str]] = []

    monkeypatch.setattr(run_tests.GitHubActionsClient, "_check_gh", lambda _self: None)
    monkeypatch.setattr(run_tests.time, "sleep", lambda _seconds: None)

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    client = run_tests.GitHubActionsClient()
    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)
    monkeypatch.setattr(
        client,
        "_recent_runs",
        lambda limit=50: [{
            "databaseId": 123,
            "displayTitle": next(
                item.removeprefix("dispatch_token=")
                for item in commands[-1]
                if item.startswith("dispatch_token=")
            ),
        }],
    )

    for profile in ("web-laptop", "web-phone"):
        commands.clear()
        assert client.dispatch_spec(
            "audio-recording.spec.ts",
            account=1,
            proof_video_profile=profile,
        ) == 123
        assert f"proof_video_profile={profile}" in commands[0]


def test_proof_video_size_also_sets_browser_viewport(tmp_path):
    config_url = (PROJECT_ROOT / "frontend/apps/web_app/playwright.config.ts").as_uri()
    loader = tmp_path / "load-playwright-config.mjs"
    loader.write_text(
        f"const config = (await import('{config_url}')).default;\n"
        "console.log(JSON.stringify({ viewport: config.use.viewport ?? null, video: config.use.video }));\n",
        encoding="utf-8",
    )

    for width, height, expected in (("1440", "900", {"width": 1440, "height": 900}), ("390", "844", {"width": 390, "height": 844}), (None, None, None)):
        env = os.environ.copy()
        env["PLAYWRIGHT_TEST_BASE_URL"] = "https://example.invalid"
        if width is None:
            env.pop("PLAYWRIGHT_VIDEO_WIDTH", None)
            env.pop("PLAYWRIGHT_VIDEO_HEIGHT", None)
        else:
            env["PLAYWRIGHT_VIDEO_WIDTH"] = width
            env["PLAYWRIGHT_VIDEO_HEIGHT"] = height
        result = subprocess.run(
            ["node", "--experimental-strip-types", str(loader)],
            cwd=PROJECT_ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        loaded = json.loads(result.stdout)
        assert loaded["viewport"] == expected
        if expected is not None:
            assert loaded["video"]["size"] == expected


def test_prod_smoke_dispatch_matches_unique_token(monkeypatch, tmp_path):
    run_tests = load_run_tests_module()
    commands: list[list[str]] = []
    waited_run_ids: list[list[int]] = []

    monkeypatch.setattr(run_tests, "_docker_restarted_recently", lambda: False)
    monkeypatch.setattr(run_tests, "_git_info", lambda: ("abc123", "dev"))
    monkeypatch.setattr(run_tests.time, "sleep", lambda _seconds: None)

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)

    class FakeClient:
        def __init__(self):
            self.recent_run_calls = 0

        def _recent_run_ids(self, limit=5, workflow=run_tests.WORKFLOW_NAME):
            return [111]

        def _recent_runs(self, limit=5, workflow=run_tests.WORKFLOW_NAME):
            token = next(
                item.removeprefix("dispatch_token=")
                for item in commands[0]
                if item.startswith("dispatch_token=")
            )
            return [
                {"databaseId": 222, "displayTitle": "Prod smoke paid-chat prod-other"},
                {"databaseId": 333, "displayTitle": f"Prod smoke paid-chat {token}"},
            ]

        def wait_for_runs(self, run_ids, **_kwargs):
            waited_run_ids.append(run_ids)
            return {run_ids[0]: {"status": "completed", "conclusion": "success"}}

        def download_artifact(self, _run_id, _artifact_name, artifact_dir):
            results_dir = artifact_dir / "test-results"
            results_dir.mkdir(parents=True)
            (results_dir / "paid-chat.json").write_text(
                '{"status":"passed","scenarios":{"paid_chat":{"status":"passed"}}}',
                encoding="utf-8",
            )
            return artifact_dir

        def get_failed_job_error(self, _run_id):
            return ""

    class FakeNotification:
        discord_webhook_prod_smoke = None

        def _send_summary_to_discord(self, *_args, **_kwargs):
            return None

        def send_prod_failure_email(self, *_args, **_kwargs):
            return None

        def send_per_test_md_messages(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(run_tests, "GitHubActionsClient", FakeClient)

    result = run_tests._run_prod_smoke_suite(
        FakeNotification(),
        force=True,
        suite=run_tests.PROD_SMOKE_SUITE_PAID_CHAT,
        archive_dir=tmp_path,
        mode_flag="prod-paid-chat",
        mode_label="prod paid chat",
        display_title="Prod paid chat",
    )

    assert result == 0
    assert "suite=paid-chat" in commands[0]
    assert any(item.startswith("dispatch_token=prod-paid-chat-") for item in commands[0])
    assert waited_run_ids == [[333]]


def test_prod_smoke_parser_accepts_flattened_cli_artifact(tmp_path):
    run_tests = load_run_tests_module()
    (tmp_path / "paid-chat.json").write_text(
        '{"status":"failed","scenarios":{"paid_chat":{"status":"failed","error":"HTTP 401"}}}',
        encoding="utf-8",
    )

    results = run_tests._parse_prod_smoke_artifact(
        tmp_path,
        run_tests.PROD_SMOKE_SPECS_BY_SUITE[run_tests.PROD_SMOKE_SUITE_PAID_CHAT],
    )

    assert results == [{
        "key": "paid-chat",
        "filename": "verify_prod_cli_smoke.py",
        "name": "CLI paid chat smoke",
        "status": "failed",
        "error": "HTTP 401",
        "passed": 0,
        "failed": 1,
    }]


def test_preflight_account_payload_deduplicates_emails():
    run_tests = load_run_tests_module()

    results = [
        run_tests.SpecResult(name="test-account-preflight.spec.ts", status="passed", account=1, account_email="Test@Example.test"),
        run_tests.SpecResult(name="test-account-preflight.spec.ts", status="passed", account=2, account_email="test@example.test"),
        run_tests.SpecResult(name="test-account-preflight.spec.ts", status="passed", account=3, account_email=None),
    ]

    assert run_tests._configured_preflight_accounts(results) == [
        {"slot": 1, "email": "Test@Example.test"}
    ]


def test_extract_account_email_from_playwright_stdout(tmp_path):
    run_tests = load_run_tests_module()
    report = tmp_path / "playwright.json"
    report.write_text(
        '{"suites":[{"specs":[{"tests":[{"results":[{"stdout":['
        '{"text":"[ACCOUNT_PREFLIGHT][slot 1] Starting. | meta={\\"email\\":\\"acct@example.test\\"}\\n"}'
        ']}]}]}]}]}',
        encoding="utf-8",
    )

    assert run_tests.BatchRunner._extract_account_email_from_playwright_json(report) == "acct@example.test"


def test_playwright_json_passed_with_skipped_phases_is_not_an_error(tmp_path):
    run_tests = load_run_tests_module()
    report = tmp_path / "playwright.json"
    report.write_text(
        '{"suites":[{"specs":[{"tests":[{"results":['
        '{"status":"passed","steps":[]},'
        '{"status":"skipped","steps":[]}'
        ']}]}]}]}',
        encoding="utf-8",
    )

    extracted_err, errors, steps, result_statuses = (
        run_tests.BatchRunner._extract_structured_data_from_playwright_json(report)
    )

    assert extracted_err is None
    assert errors == []
    assert steps == []
    assert set(result_statuses) == {"passed", "skipped"}


def test_playwright_retry_pass_is_a_passing_flake(tmp_path):
    run_tests = load_run_tests_module()
    report = tmp_path / "playwright.json"
    report.write_text(
        '{"suites":[{"specs":[{"tests":[{"results":['
        '{"retry":0,"status":"failed","error":{"message":"first attempt"}},'
        '{"retry":1,"status":"passed"}'
        ']}]}]}]}',
        encoding="utf-8",
    )

    summary = run_tests.BatchRunner._playwright_attempt_summary(report)

    assert summary["terminal_statuses"] == ["passed"]
    assert summary["attempt_statuses"] == ["failed", "passed"]
    assert summary["retries"] == 1
    assert summary["flaky"] is True


def test_playwright_debug_outputs_are_persisted(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "RESULTS_DIR", tmp_path / "test-results")
    report = tmp_path / "playwright.json"
    report.write_text(
        json.dumps({
            "suites": [{
                "specs": [{
                    "tests": [{
                        "results": [{
                            "retry": 0,
                            "status": "failed",
                            "stdout": [{"text": "[debug] full stdout\n"}],
                            "stderr": [{"text": "[debug] full stderr\n"}],
                        }]
                    }]
                }]
            }]
        }),
        encoding="utf-8",
    )

    summary = run_tests.BatchRunner._persist_playwright_debug_outputs("cli-skills-pdf.spec.ts", report)

    artifacts = summary["artifact_paths"]
    assert "debug/current/cli-skills-pdf/attempt-1-0-stdout.txt" in artifacts
    assert "debug/current/cli-skills-pdf/attempt-1-0-stderr.txt" in artifacts
    assert "[debug] full stdout" in summary["summary"]
    assert (run_tests.RESULTS_DIR / "debug" / "current" / "cli-skills-pdf" / "attempt-1-0-result.json").is_file()


def test_api_key_device_approval_blocker_is_detected():
    run_tests = load_run_tests_module()

    assert run_tests.BatchRunner._environment_blocker_from_text(
        "A new device attempted to use your API key. Please review and approve it in Developer Settings."
    ) == "api_key_device_approval_required"
    assert run_tests.BatchRunner._environment_blocker_from_text("ordinary locator failure") is None


def test_passing_flake_is_not_counted_as_a_final_failure():
    run_tests = load_run_tests_module()
    suite = run_tests.SuiteResult(
        status="passed",
        tests=[{"name": "example.spec.ts", "status": "passed", "flaky": True, "retries": 1}],
    )

    result = run_tests.ResultAggregator.build_run_result(
        {"playwright": suite}, "run-1", "sha", "dev", "development", 1.0, {}
    )

    assert result.summary["passed"] == 1
    assert result.summary["failed"] == 0


def test_apple_remote_default_nightly_commands_are_serialized(monkeypatch):
    run_tests = load_run_tests_module()
    monkeypatch.delenv("OPENMATES_APPLE_REMOTE_NIGHTLY_COMMANDS", raising=False)

    commands = run_tests._apple_remote_commands_for_nightly()

    assert [name for name, _command in commands] == [
        "sync-repo",
        "test-ios",
        "test-macos",
        "verify-watch-startup",
    ]
    assert commands[1][1] == ("test-ios", "--simulator", "iPhone 17")


def test_apple_remote_nightly_commands_accept_json_override(monkeypatch):
    run_tests = load_run_tests_module()
    monkeypatch.setenv(
        "OPENMATES_APPLE_REMOTE_NIGHTLY_COMMANDS",
        json.dumps([
            {"name": "ios-focused", "command": ["test-ios", "--only-testing", "OpenMatesTests/ExampleTests"]},
            ["verify-macos-startup", "--duration", "30"],
        ]),
    )

    commands = run_tests._apple_remote_commands_for_nightly()

    assert commands == [
        ("ios-focused", ("test-ios", "--only-testing", "OpenMatesTests/ExampleTests")),
        ("apple-remote-2", ("verify-macos-startup", "--duration", "30")),
    ]


def test_apple_remote_suite_counts_like_regular_failures():
    run_tests = load_run_tests_module()
    suite = run_tests.SuiteResult(
        status="failed",
        tests=[
            {"name": "test-ios", "status": "passed"},
            {"name": "test-macos", "status": "failed", "error": "xcodebuild failed"},
        ],
    )

    result = run_tests.ResultAggregator.build_run_result(
        {"apple_remote": suite}, "run-1", "sha", "dev", "development", 1.0, {}
    )

    assert result.summary["total"] == 2
    assert result.summary["passed"] == 1
    assert result.summary["failed"] == 1


def test_flake_history_is_idempotent_by_run_id(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "RESULTS_DIR", tmp_path)
    data = {
        "run_id": "run-1",
        "suites": {"playwright": {"tests": [{
            "name": "example.spec.ts", "file": "example.spec.ts", "status": "passed",
            "flaky": True, "retries": 1, "attempt_statuses": ["failed", "passed"],
        }]}},
    }

    run_tests.record_flake_history(data)
    run_tests.record_flake_history(data)

    history = __import__("json").loads((tmp_path / "flaky-history.json").read_text(encoding="utf-8"))
    entry = history["tests"]["playwright::example.spec.ts"]
    assert entry["total_runs"] == 1
    assert entry["flaky_count"] == 1
    assert entry["last_attempt_statuses"] == ["failed", "passed"]


def test_credit_guard_pipes_local_script_into_api_container(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    guard_script = tmp_path / "backend" / "scripts" / "top_up_test_account_credits.py"
    guard_script.parent.mkdir(parents=True)
    guard_script.write_text("print('guard script')\n", encoding="utf-8")
    monkeypatch.setattr(run_tests, "PROJECT_ROOT", tmp_path)

    captured = {}

    def fake_run(cmd, input, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["input"] = input
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return SimpleNamespace(stdout="accounts_checked=1\nok slots=1 credits=50000\n", stderr="", returncode=0)

    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)

    error = run_tests.TestOrchestrator._ensure_preflight_account_credits([
        run_tests.SpecResult(
            name="test-account-preflight.spec.ts",
            status="passed",
            account=1,
            account_email="acct@example.test",
        )
    ])

    assert error is None
    assert captured["cmd"][:6] == ["docker", "exec", "-i", "api", "python", "-"]
    assert captured["cmd"][6] == "--accounts-json"
    assert '"email": "acct@example.test"' in captured["cmd"][7]
    assert captured["input"] == "print('guard script')\n"
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["timeout"] == 180


def test_account_id_repair_pipes_local_script_for_missing_account_id_preflight(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    repair_script = tmp_path / "backend" / "scripts" / "repair_test_account_account_ids.py"
    repair_script.parent.mkdir(parents=True)
    repair_script.write_text("print('repair script')\n", encoding="utf-8")
    monkeypatch.setattr(run_tests, "PROJECT_ROOT", tmp_path)

    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.environment = "development"
    captured = {}

    def fake_run(cmd, input, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["input"] = input
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return SimpleNamespace(stdout="accounts_checked=1\nrepaired slots=1 account_id_present=true\n", stderr="", returncode=0)

    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)

    repaired = orchestrator._repair_missing_preflight_account_ids([
        run_tests.SpecResult(
            name="test-account-preflight.spec.ts",
            status="failed",
            account=1,
            account_email="acct@example.test",
            error="Persistent E2E account is missing users.account_id",
        )
    ])

    assert repaired is True
    assert captured["cmd"][:6] == ["docker", "exec", "-i", "api", "python", "-c"]
    assert "acct@example.test" not in " ".join(captured["cmd"])
    payload = json.loads(captured["input"])
    assert payload["script"] == "print('repair script')\n"
    assert payload["accounts"] == [{"slot": 1, "email": "acct@example.test"}]
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["timeout"] == 180


def test_account_id_repair_skips_non_development_environment():
    run_tests = load_run_tests_module()
    orchestrator = object.__new__(run_tests.TestOrchestrator)
    orchestrator.environment = "production"

    repaired = orchestrator._repair_missing_preflight_account_ids([
        run_tests.SpecResult(
            name="test-account-preflight.spec.ts",
            status="failed",
            account=1,
            account_email="acct@example.test",
            error="Persistent E2E account is missing users.account_id",
        )
    ])

    assert repaired is False


def test_credential_update_artifacts_are_persisted_outside_screenshots(tmp_path, monkeypatch):
    run_tests = load_run_tests_module()
    artifact_root = tmp_path / "artifact"
    uploaded_artifacts = artifact_root / "frontend" / "apps" / "web_app" / "artifacts"
    uploaded_artifacts.mkdir(parents=True)
    (uploaded_artifacts / "new_otp_key.txt").write_text("OTP_PLACEHOLDER", encoding="utf-8")
    (uploaded_artifacts / "api_key.txt").write_text("API_KEY_PLACEHOLDER", encoding="utf-8")

    results_dir = tmp_path / "test-results"
    monkeypatch.setattr(run_tests, "RESULTS_DIR", results_dir)

    run_tests.BatchRunner._persist_credential_update_artifacts(
        "backup-code-login-flow.spec.ts",
        artifact_root,
    )

    dest = results_dir / "credential-updates" / "backup-code-login-flow"
    assert (dest / "new_otp_key.txt").read_text(encoding="utf-8") == "OTP_PLACEHOLDER"
    assert (dest / "api_key.txt").read_text(encoding="utf-8") == "API_KEY_PLACEHOLDER"
    assert not (results_dir / "screenshots" / "current" / "backup-code-login-flow" / "new_otp_key.txt").exists()


def test_vercel_gate_fails_immediately_for_stale_dev_ancestor(monkeypatch):
    run_tests = load_run_tests_module()
    monkeypatch.setattr(run_tests, "_vercel_project_config", lambda: ("team", "project"))
    monkeypatch.setattr(run_tests, "_latest_vercel_deployment_for_sha", lambda *_args: None)
    monkeypatch.setattr(run_tests, "_requested_commit_is_stale_dev_ancestor", lambda _sha: True)

    ready, reason = run_tests._wait_for_vercel_deployment(
        "a" * 40,
        {"VERCEL_TOKEN": "test-token", "OPENMATES_VERCEL_WAIT_TIMEOUT": "3600"},
    )

    assert ready is False
    assert "stale dev ancestor" in reason


def test_recent_runs_uses_direct_workflow_runs_endpoint(monkeypatch):
    run_tests = load_run_tests_module()
    client = object.__new__(run_tests.GitHubActionsClient)
    client.last_dispatch_error = None
    client.dispatch_circuit = run_tests.DispatchCircuit()
    captured = []

    def fake_run(command, **_kwargs):
        captured.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"workflow_runs": [{"id": 123, "display_title": "dispatch-token"}]}),
            stderr="",
        )

    monkeypatch.setattr(run_tests.subprocess, "run", fake_run)

    assert client._recent_runs(limit=50) == [{"databaseId": 123, "displayTitle": "dispatch-token"}]
    assert captured == [[
        "gh",
        "api",
        f"repos/{run_tests.GH_REPO}/actions/workflows/playwright-spec.yml/runs?per_page=50",
    ]]


def test_recent_runs_surfaces_rate_limit_without_silent_empty_retry(monkeypatch):
    run_tests = load_run_tests_module()
    client = object.__new__(run_tests.GitHubActionsClient)
    client.last_dispatch_error = None
    client.dispatch_circuit = run_tests.DispatchCircuit()
    monkeypatch.setattr(
        run_tests.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="HTTP 403: API rate limit exceeded",
        ),
    )

    assert client._recent_runs() == []
    assert client.last_dispatch_error == "GitHub Actions rate limit blocked workflow run discovery"
    assert client.dispatch_circuit.is_open is True
