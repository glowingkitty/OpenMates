#!/usr/bin/env python3
"""Test the focused, bounded proof-video workflow orchestrator.

The tests cover only deterministic context, contract, trim, pacing, cache, and
review-routing behavior. They deliberately avoid network calls, OCR, full-video
analysis, and semantic UI judgment. Synthetic session and test records ensure
the workflow never needs real credentials or user data.
"""

# contract-test-file: tooling

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess

import pytest

from scripts import proof_video_workflow as workflow


def frame_quality_review(frame: str, **overrides: str) -> dict[str, object]:
    checks = {
        "layout": "pass",
        "readability": "pass",
        "geometry": "pass",
        "controls": "pass",
        "visual_assets": "pass",
        "application_state": "pass",
        "consistency": "pass",
        "proof_alignment": "pass",
    }
    checks.update(overrides)
    return {
        "frame": frame,
        "checks": checks,
        "observation": "Completed the independent critical UI scan.",
    }


def test_resolve_current_context_matches_session_commit_and_passing_spec() -> None:
    commit = "a" * 40
    sessions = {
        "sessions": {
            "abcd": {
                "opencode_session_id": "ses_current",
                "mode": "feature",
            }
        }
    }
    runs = [
        {
            "run_id": "run-old",
            "git_sha": "old1234",
            "status": "passed",
            "spec": "example.spec.ts",
        },
        {
            "run_id": "run-current",
            "git_sha": commit,
            "status": "passed",
            "spec": "example.spec.ts",
            "source": "scripts_tests",
            "deployment_verified": True,
        },
    ]

    context = workflow.resolve_current_context(
        sessions,
        opencode_session_id="ses_current",
        subject_commit=commit,
        spec_name="example.spec.ts",
        test_runs=runs,
    )

    assert context.session_id == "abcd"
    assert context.subject_commit == commit
    assert context.source_run_id == "run-current"


def test_commit_matches_deployed_descendant(monkeypatch: pytest.MonkeyPatch) -> None:
    subject_commit = "a" * 40
    deployed_commit = "b" * 40

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git", "merge-base", "--is-ancestor", subject_commit, deployed_commit],
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(workflow.subprocess, "run", fake_run)

    assert workflow._commit_matches(deployed_commit, subject_commit) is True
    assert workflow._commit_matches("short", subject_commit) is False


def test_control_plane_root_resolves_shared_session_registry_from_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_root = tmp_path / "OpenMates"
    worktree_root = control_root / ".openmates-agent-worktrees" / "agent-abcd"
    git_dir = control_root / ".git"
    worktree_root.mkdir(parents=True)

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git", "rev-parse", "--git-common-dir"],
            returncode=0,
            stdout=str(git_dir) + "\n",
            stderr="",
        )

    monkeypatch.setattr(workflow.subprocess, "run", fake_run)

    assert workflow._resolve_control_plane_root(worktree_root) == control_root
    assert workflow._resolve_control_plane_root(worktree_root) / ".claude" / "sessions.json" == control_root / ".claude" / "sessions.json"


def test_proof_sources_use_shared_control_plane_results() -> None:
    assert workflow.PROOF_SOURCE_DIR == workflow.CONTROL_PLANE_ROOT / "test-results" / "proof-video-sources"


def test_start_current_uses_deployed_session_commit_from_linked_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployed_commit = "a" * 40
    sessions_file = tmp_path / "control" / ".claude" / "sessions.json"
    proof_sources = tmp_path / "worktree" / "test-results" / "proof-video-sources"
    proof_sources.mkdir(parents=True)
    sessions_file.parent.mkdir(parents=True)
    sessions_file.write_text(
        json.dumps(
            {
                "sessions": {
                    "abcd": {
                        "opencode_session_id": "ses_current",
                        "worktree": {"merged_commit": deployed_commit},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (proof_sources / "run-current.json").write_text(
        json.dumps(
            {
                "run_id": "run-current",
                "git_sha": deployed_commit,
                "deployment_reference": deployed_commit,
                "status": "passed",
                "spec": "example.spec.ts",
                "source": "scripts_tests",
                "deployment_verified": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_current")
    monkeypatch.setattr(workflow, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(workflow, "PROOF_SOURCE_DIR", proof_sources)
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path / "worktree" / "test-results")
    monkeypatch.setattr(workflow, "REPO_ROOT", tmp_path / "worktree")
    monkeypatch.setattr(workflow, "_tracked_worktree_changes", lambda: ["frontend/dirty.svelte"])
    monkeypatch.setattr(workflow, "_current_git_sha", lambda: "b" * 40)

    result = workflow.start_current("example.spec.ts")

    assert result["context"]["session_id"] == "abcd"
    assert result["context"]["subject_commit"] == deployed_commit
    assert result["context"]["source_run_id"] == "run-current"


def test_start_current_disambiguates_numeric_cli_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployed_commit = "a" * 40
    sessions_file = tmp_path / "control" / ".claude" / "sessions.json"
    proof_sources = tmp_path / "worktree" / "test-results" / "proof-video-sources"
    proof_sources.mkdir(parents=True)
    sessions_file.parent.mkdir(parents=True)
    sessions_file.write_text(
        json.dumps(
            {
                "sessions": {
                    "abcd": {
                        "opencode_session_id": "ses_current",
                        "worktree": {"merged_commit": deployed_commit},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (proof_sources / "run-current.json").write_text(
        json.dumps(
            {
                "run_id": 31889726729,
                "git_sha": deployed_commit,
                "deployment_reference": deployed_commit,
                "status": "passed",
                "spec": "example.spec.ts",
                "source": "scripts_tests",
                "deployment_verified": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_current")
    monkeypatch.setattr(workflow, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(workflow, "PROOF_SOURCE_DIR", proof_sources)
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path / "worktree" / "test-results")
    monkeypatch.setattr(workflow, "REPO_ROOT", tmp_path / "worktree")
    monkeypatch.setattr(workflow, "_tracked_worktree_changes", lambda: [])
    monkeypatch.setattr(workflow, "_current_git_sha", lambda: "b" * 40)

    result = workflow.start_current("example.spec.ts", run_id="31889726729")

    assert result["context"]["source_run_id"] == "31889726729"


def test_start_current_disambiguates_proof_source_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployed_commit = "a" * 40
    sessions_file = tmp_path / "control" / ".claude" / "sessions.json"
    proof_sources = tmp_path / "worktree" / "test-results" / "proof-video-sources"
    proof_sources.mkdir(parents=True)
    sessions_file.parent.mkdir(parents=True)
    sessions_file.write_text(
        json.dumps(
            {
                "sessions": {
                    "abcd": {
                        "opencode_session_id": "ses_current",
                        "worktree": {"merged_commit": deployed_commit},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (proof_sources / "run-current.json").write_text(
        json.dumps(
            {
                "run_id": "31889726729:example-artifact",
                "source_run_id": "31889726729",
                "git_sha": deployed_commit,
                "deployment_reference": deployed_commit,
                "status": "passed",
                "spec": "example.spec.ts",
                "source": "scripts_tests",
                "deployment_verified": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_current")
    monkeypatch.setattr(workflow, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(workflow, "PROOF_SOURCE_DIR", proof_sources)
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path / "worktree" / "test-results")
    monkeypatch.setattr(workflow, "REPO_ROOT", tmp_path / "worktree")
    monkeypatch.setattr(workflow, "_tracked_worktree_changes", lambda: [])
    monkeypatch.setattr(workflow, "_current_git_sha", lambda: "b" * 40)

    result = workflow.start_current("example.spec.ts", run_id="31889726729")

    assert result["context"]["source_run_id"] == "31889726729"


def test_resolve_current_context_rejects_ambiguous_passing_runs() -> None:
    commit = "a" * 40
    runs = [
        {"run_id": "run-1", "git_sha": commit, "status": "passed", "spec": "example.spec.ts", "source": "scripts_tests", "deployment_verified": True},
        {"run_id": "run-2", "git_sha": commit, "status": "passed", "spec": "example.spec.ts", "source": "scripts_tests", "deployment_verified": True},
    ]

    with pytest.raises(workflow.WorkflowError, match="multiple passing runs"):
        workflow.resolve_current_context(
            {"sessions": {"abcd": {"opencode_session_id": "ses_current"}}},
            opencode_session_id="ses_current",
            subject_commit=commit,
            spec_name="example.spec.ts",
            test_runs=runs,
        )


def test_resolve_current_context_accepts_same_run_with_multiple_video_sources() -> None:
    commit = "a" * 40
    runs = [
        {"run_id": "run-1:phone-1234", "source_run_id": "run-1", "git_sha": commit, "status": "passed", "spec": "example.spec.ts", "source": "scripts_tests", "deployment_verified": True},
        {"run_id": "run-1:laptop-5678", "source_run_id": "run-1", "git_sha": commit, "status": "passed", "spec": "example.spec.ts", "source": "scripts_tests", "deployment_verified": True},
    ]

    context = workflow.resolve_current_context(
        {"sessions": {"abcd": {"opencode_session_id": "ses_current"}}},
        opencode_session_id="ses_current",
        subject_commit=commit,
        spec_name="example.spec.ts",
        test_runs=runs,
    )

    assert context.source_run_id == "run-1"


def test_contract_hash_is_canonical_and_approval_is_exact(tmp_path: Path) -> None:
    contract = {
        "schema_version": 2,
        "title": "Maps Search fullscreen",
        "transcript": [
            {"text": "Maps Search opens in the regular fullscreen shell.", "devices": ["web-phone", "web-laptop"]},
            {"text": "The place list and map stay inside the same parent fullscreen.", "devices": ["web-phone", "web-laptop"]},
        ],
        "assertions": [
            {"id": "header-visible", "description": "The regular embed header is visible.", "devices": ["web-phone", "web-laptop"]},
            {"id": "no-nested-fullscreen", "description": "No nested fullscreen appears.", "devices": ["web-phone", "web-laptop"]},
        ],
        "devices": ["web-phone", "web-laptop"],
    }

    first = workflow.write_contract(tmp_path / "contract.json", contract)
    second = workflow.write_contract(tmp_path / "contract-copy.json", dict(reversed(list(contract.items()))))

    assert first["contract_hash"] == second["contract_hash"]
    workflow.require_approved_contract(first, first["contract_hash"])
    with pytest.raises(workflow.WorkflowError, match="approved contract hash"):
        workflow.require_approved_contract(first, "sha256:stale")


def test_multidevice_contract_requires_device_scoped_transcript_and_assertions() -> None:
    contract = {
        "title": "Responsive proof",
        "transcript": ["The responsive result is visible."],
        "assertions": [{"id": "visible", "description": "The result is visible."}],
        "devices": ["web-phone", "web-laptop"],
    }

    with pytest.raises(workflow.WorkflowError, match="schema_version 2"):
        workflow.canonical_contract(contract)


def test_device_scoped_contract_selects_only_applicable_claims() -> None:
    contract = {
        "schema_version": 2,
        "title": "Responsive proof",
        "transcript": [
            {"text": "The shared shell is visible.", "devices": ["web-phone", "web-laptop"]},
            {"text": "The phone board scrolls horizontally.", "devices": ["web-phone"]},
            {"text": "The laptop board stays below the header.", "devices": ["web-laptop"]},
        ],
        "assertions": [
            {"id": "shared", "description": "The shared shell is visible.", "devices": ["web-phone", "web-laptop"]},
            {"id": "phone-scroll", "description": "The phone board scrolls horizontally.", "devices": ["web-phone"]},
            {"id": "laptop-header", "description": "The laptop board stays below the header.", "devices": ["web-laptop"]},
        ],
        "devices": ["web-phone", "web-laptop"],
    }

    phone = workflow.approved_render_claims(contract, device_profile="web-phone")
    laptop = workflow.approved_render_claims(contract, device_profile="web-laptop")

    assert phone["acceptance_criteria"] == ["shared", "phone-scroll"]
    assert [item["id"] for item in phone["assertions"]] == ["shared", "phone-scroll"]
    assert "phone board" in phone["caption_text"]
    assert "laptop board" not in phone["caption_text"]
    assert laptop["acceptance_criteria"] == ["shared", "laptop-header"]
    assert "laptop board" in laptop["caption_text"]
    assert "phone board" not in laptop["caption_text"]


def test_device_scoped_contract_rejects_unknown_or_uncovered_devices() -> None:
    base = {
        "schema_version": 2,
        "title": "Responsive proof",
        "transcript": [{"text": "The result is visible.", "devices": ["web-phone"]}],
        "assertions": [{"id": "visible", "description": "The result is visible.", "devices": ["web-phone"]}],
        "devices": ["web-phone", "web-laptop"],
    }

    with pytest.raises(workflow.WorkflowError, match="at least one assertion"):
        workflow.canonical_contract(base)
    base["assertions"][0]["devices"] = ["web-tablet"]
    with pytest.raises(workflow.WorkflowError, match="contract devices"):
        workflow.canonical_contract(base)


def test_approved_contract_rejects_tampered_payload_with_embedded_old_hash(tmp_path: Path) -> None:
    contract = workflow.write_contract(
        tmp_path / "contract.json",
        {
            "title": "Visible flow",
            "transcript": ["The screen shows the approved state."],
            "assertions": [{"id": "visible", "description": "The approved state is visible."}],
            "devices": ["web-phone"],
        },
    )
    approved_hash = contract["contract_hash"]
    contract["transcript"] = ["A different unapproved claim is visible."]

    with pytest.raises(workflow.WorkflowError, match="approved contract hash"):
        workflow.require_approved_contract(contract, approved_hash)


def test_context_rejects_local_or_unverified_passing_run() -> None:
    with pytest.raises(workflow.WorkflowError, match="deployed passing run"):
        workflow.resolve_current_context(
            {"sessions": {"abcd": {"opencode_session_id": "ses_current"}}},
            opencode_session_id="ses_current",
            subject_commit="abc1234",
            spec_name="frontend/apps/web_app/tests/example.spec.ts",
            test_runs=[
                {
                    "run_id": "local-run",
                    "git_sha": "abc1234",
                    "status": "passed",
                    "spec": "frontend/apps/web_app/tests/example.spec.ts",
                    "source": "local",
                    "deployment_verified": False,
                }
            ],
        )


def test_clean_worktree_guard_rejects_tracked_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "_tracked_worktree_changes", lambda: ["scripts/example.py"])

    with pytest.raises(workflow.WorkflowError, match="tracked changes"):
        workflow.require_clean_worktree()


def test_clean_worktree_guard_accepts_reusable_worktree_matching_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr=""),
    )

    workflow.require_clean_worktree("a" * 40)


def test_clean_worktree_guard_compares_session_owned_blobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = tmp_path / "created-after-worktree.py"
    owned.write_bytes(b"deployed content\n")
    monkeypatch.setattr(workflow, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        workflow.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=b"deployed content\n",
            stderr=b"",
        ),
    )

    workflow.require_clean_worktree("a" * 40, ["created-after-worktree.py"])


def test_recorded_contract_authorization_is_bound_to_session_spec_path_and_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "APPROVALS_DIR", tmp_path / "approvals")
    contract_path = tmp_path / "contract.json"
    workflow.write_contract(
        contract_path,
        {
            "title": "Visible flow",
            "transcript": ["The screen shows the approved result."],
            "assertions": [{"id": "visible", "description": "The approved result is visible."}],
            "devices": ["web-phone"],
        },
    )
    authorization = workflow.record_contract_authorization(
        session_id="abcd",
        spec_name="example.spec.ts",
        contract_path=contract_path,
    )
    assert authorization["authorized_by"] == "tooling"

    approved = workflow.require_recorded_approval(
        session_id="abcd",
        spec_name="example.spec.ts",
        contract_path=contract_path,
    )
    assert approved["title"] == "Visible flow"

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["transcript"] = ["Unapproved replacement text."]
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(workflow.WorkflowError, match="approved contract hash"):
        workflow.require_recorded_approval(session_id="abcd", spec_name="example.spec.ts", contract_path=contract_path)


def test_deployed_run_rejects_duplicate_attestations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commit = "a" * 40
    video = tmp_path / "video.webm"
    video.write_bytes(b"verified")
    record = {
        "run_id": "run-one",
        "git_sha": commit,
        "deployment_reference": commit,
        "status": "passed",
        "spec": "example.spec.ts",
        "source": "scripts_tests",
        "deployment_verified": True,
        "artifact_path": str(video),
        "artifact_sha256": workflow._file_sha256(video),
    }
    monkeypatch.setattr(
        workflow,
        "_local_test_runs",
        lambda: [record, dict(record)],
    )

    with pytest.raises(workflow.WorkflowError, match="found 2"):
        workflow.resolve_deployed_run(subject_commit=commit, spec_name="example.spec.ts", run_id="run-one")


def test_deployed_run_can_select_exact_source_video_from_multi_video_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commit = "a" * 40
    phone_video = tmp_path / "phone.webm"
    laptop_video = tmp_path / "laptop.webm"
    phone_video.write_bytes(b"phone")
    laptop_video.write_bytes(b"laptop")
    records = []
    for label, video in (("phone", phone_video), ("laptop", laptop_video)):
        records.append({
            "run_id": f"run-one:{label}",
            "source_run_id": "run-one",
            "git_sha": commit,
            "deployment_reference": commit,
            "status": "passed",
            "spec": "example.spec.ts",
            "source": "scripts_tests",
            "deployment_verified": True,
            "artifact_path": str(video),
            "artifact_sha256": workflow._file_sha256(video),
        })
    monkeypatch.setattr(workflow, "_local_test_runs", lambda: records)

    selected = workflow.resolve_deployed_run(
        subject_commit=commit,
        spec_name="example.spec.ts",
        run_id="run-one",
        source_video=laptop_video,
    )

    assert selected["artifact_path"] == str(laptop_video)


def test_deployed_run_accepts_descendant_attestation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subject_commit = "a" * 40
    deployed_commit = "b" * 40
    video = tmp_path / "video.webm"
    video.write_bytes(b"verified descendant")
    monkeypatch.setattr(
        workflow,
        "_commit_matches",
        lambda candidate, expected: (candidate, expected) == (deployed_commit, subject_commit),
    )
    monkeypatch.setattr(workflow, "_local_test_runs", lambda: [{
        "run_id": "run-one", "git_sha": deployed_commit, "deployment_reference": deployed_commit,
        "status": "passed", "spec": "example.spec.ts", "source": "scripts_tests",
        "deployment_verified": True, "artifact_path": str(video), "artifact_sha256": workflow._file_sha256(video),
    }])

    selected = workflow.resolve_deployed_run(
        subject_commit=subject_commit,
        spec_name="example.spec.ts",
        run_id="run-one",
    )

    assert selected["git_sha"] == deployed_commit


def test_deployed_run_requires_exact_full_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "_local_test_runs",
        lambda: [{
            "run_id": "run-one",
            "git_sha": "a" * 40,
            "deployment_reference": "a" * 40,
            "status": "passed",
            "spec": "example.spec.ts",
            "source": "scripts_tests",
            "deployment_verified": True,
            "artifact_path": "video.webm",
            "artifact_sha256": "sha256:" + "0" * 64,
        }],
    )

    with pytest.raises(workflow.WorkflowError, match="found 0"):
        workflow.resolve_deployed_run(subject_commit="abc1234", spec_name="example.spec.ts", run_id="run-one")


def test_deployed_run_rejects_matching_short_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "_local_test_runs", lambda: [{
        "run_id": "run-one", "git_sha": "abc1234", "deployment_reference": "abc1234",
        "status": "passed", "spec": "example.spec.ts", "source": "scripts_tests",
        "deployment_verified": True, "artifact_path": "video.webm", "artifact_sha256": "sha256:" + "0" * 64,
    }])

    with pytest.raises(workflow.WorkflowError, match="found 0"):
        workflow.resolve_deployed_run(subject_commit="abc1234", spec_name="example.spec.ts", run_id="run-one")


def test_deployed_run_rejects_replaced_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commit = "a" * 40
    video = tmp_path / "video.webm"
    video.write_bytes(b"original")
    original_hash = workflow._file_sha256(video)
    video.write_bytes(b"replacement")
    monkeypatch.setattr(workflow, "_local_test_runs", lambda: [{
        "run_id": "run-one", "git_sha": commit, "deployment_reference": commit,
        "status": "passed", "spec": "example.spec.ts", "source": "scripts_tests",
        "deployment_verified": True, "artifact_path": str(video), "artifact_sha256": original_hash,
    }])

    with pytest.raises(workflow.WorkflowError, match="content hash changed"):
        workflow.resolve_deployed_run(subject_commit=commit, spec_name="example.spec.ts", run_id="run-one")


def test_contract_requires_one_to_five_visible_assertions() -> None:
    with pytest.raises(workflow.WorkflowError, match="one to five"):
        workflow.canonical_contract(
            {"title": "Empty", "transcript": ["Visible tutorial sentence."], "assertions": [], "devices": ["web-phone"]}
        )


def test_marker_trim_and_pacing_are_bounded() -> None:
    assert workflow.marker_trim_start(ready_timestamp_seconds=4.35) == pytest.approx(4.2)
    assert workflow.marker_trim_start(ready_timestamp_seconds=0.1) == 0

    pace = workflow.calculate_pacing(source_duration_seconds=9, transcript_words=42)

    assert pace.playback_rate == 0.75
    assert pace.final_hold_seconds == pytest.approx(4.8)
    assert pace.output_duration_seconds == pytest.approx(16.8)
    assert pace.output_duration_seconds <= workflow.MAX_OUTPUT_SECONDS


def test_pacing_speeds_up_long_sources_to_fit_output_cap() -> None:
    pace = workflow.calculate_pacing(source_duration_seconds=40, transcript_words=40)

    assert pace.playback_rate == pytest.approx(1.143)
    assert pace.final_hold_seconds == 0.0
    assert pace.output_duration_seconds <= workflow.MAX_OUTPUT_SECONDS


def test_pacing_rejects_transcript_that_cannot_fit_output_cap() -> None:
    with pytest.raises(workflow.WorkflowError, match="35 second output limit"):
        workflow.calculate_pacing(source_duration_seconds=4, transcript_words=200)


def test_resource_limits_and_cache_key_are_stable() -> None:
    limits = workflow.resource_limits()

    assert limits == {
        "parallel_device_renders": 1,
        "maximum_output_seconds": 35,
        "maximum_analysis_frames": 12,
        "periodic_frame_interval_seconds": 5,
        "maximum_review_frames_per_device": 12,
        "maximum_ai_review_calls": 6,
        "maximum_cumulative_submitted_frames": 48,
        "maximum_automatic_correction_rounds": 2,
        "maximum_product_code_correction_rounds": 1,
        "ocr_enabled": False,
    }
    assert workflow.cache_key("sha256:source", "sha256:contract", renderer_version="1") == workflow.cache_key(
        "sha256:source", "sha256:contract", renderer_version="1"
    )


def test_review_bundle_is_frame_only_and_bounded(tmp_path: Path) -> None:
    frames = []
    for index in range(12):
        frame = tmp_path / f"frame-{index}.png"
        frame.write_bytes(b"image")
        frames.append({"path": str(frame), "timestamp_seconds": float(index)})

    bundle = workflow.build_review_bundle(
        contract={"contract_hash": "sha256:contract", "assertions": [{"id": "visible", "description": "Visible."}]},
        deterministic_metadata={"subject_commit": "abc1234"},
        frames_by_device={"web-phone": frames},
    )

    assert len(bundle["frames_by_device"]["web-phone"]) == 12
    assert "video" not in json.dumps(bundle).lower()
    with pytest.raises(workflow.WorkflowError, match="three to twelve"):
        workflow.build_review_bundle(
            contract={"contract_hash": "sha256:contract", "assertions": [{"id": "visible", "description": "Visible."}]},
            deterministic_metadata={},
            frames_by_device={"web-phone": frames + [frames[0]]},
        )


@pytest.mark.parametrize(
    ("defect", "expected_stage", "automatic"),
    [
        ("blank_first_frame", "render", True),
        ("unexplained_scroll_state", "capture", False),
        ("clipped_header", "implementation", True),
    ],
)
def test_defect_routing_never_hides_product_defects(defect: str, expected_stage: str, automatic: bool) -> None:
    result = workflow.route_defect(defect, prior_automatic_rerenders=0)

    assert result["return_stage"] == expected_stage
    assert result["automatic_correction"] is automatic

    if expected_stage == "implementation":
        assert result["next_action"] == "return_to_failing_test"


def test_mechanical_rerender_limit_is_one() -> None:
    result = workflow.route_defect("blank_first_frame", prior_automatic_rerenders=2)

    assert result["automatic_correction"] is False
    assert result["verdict"] == "uncertain"


def test_review_budget_caps_calls_frames_and_correction_rounds() -> None:
    budget: dict[str, object] = {}

    budget = workflow.reserve_review_budget(
        budget,
        device="web-phone",
        frame_count=12,
        correction_round=0,
        correction_kind="none",
    )
    budget = workflow.reserve_review_budget(
        budget,
        device="web-laptop",
        frame_count=12,
        correction_round=0,
        correction_kind="none",
    )
    budget = workflow.reserve_review_budget(
        budget,
        device="web-phone",
        frame_count=12,
        correction_round=1,
        correction_kind="product",
    )
    budget = workflow.reserve_review_budget(
        budget,
        device="web-phone",
        frame_count=12,
        correction_round=2,
        correction_kind="capture",
    )

    assert budget["ai_review_calls"] == 4
    assert budget["submitted_frames"] == 48
    assert budget["product_code_correction_rounds"] == [1]
    with pytest.raises(workflow.WorkflowError, match="frame budget"):
        workflow.reserve_review_budget(
            budget,
            device="web-laptop",
            frame_count=1,
            correction_round=1,
            correction_kind="capture",
        )
    with pytest.raises(workflow.WorkflowError, match="correction round"):
        workflow.reserve_review_budget(
            {},
            device="web-phone",
            frame_count=1,
            correction_round=3,
            correction_kind="capture",
        )


def test_review_budget_retries_incomplete_reservation_without_spending_global_limits() -> None:
    reservation = {
        "device": "web-laptop",
        "correction_round": 0,
        "frame_index_hash": "sha256:frames",
        "source_artifact_hash": "sha256:video",
        "caption_artifact_hash": "sha256:captions",
        "budget_epoch": 0,
    }
    budget = {
        "ai_review_calls": 1,
        "submitted_frames": 12,
        "reservations": [reservation],
    }

    first_retry_at = datetime(2026, 8, 26, tzinfo=timezone.utc)
    retried = workflow.reserve_review_budget(
        budget,
        device="web-laptop",
        frame_count=12,
        correction_round=0,
        correction_kind="none",
        frame_index_hash="sha256:frames",
        source_artifact_hash="sha256:video",
        caption_artifact_hash="sha256:captions",
        now=first_retry_at,
    )

    assert retried["ai_review_calls"] == 1
    assert retried["submitted_frames"] == 12
    assert retried["reservations"][0]["retry_count"] == 1
    retried_again = workflow.reserve_review_budget(
        retried,
        device="web-laptop",
        frame_count=12,
        correction_round=0,
        correction_kind="none",
        frame_index_hash="sha256:frames",
        source_artifact_hash="sha256:video",
        caption_artifact_hash="sha256:captions",
        now=first_retry_at + timedelta(seconds=workflow.REVIEW_RESERVATION_LEASE_SECONDS + 1),
    )

    assert retried_again["ai_review_calls"] == 1
    assert retried_again["submitted_frames"] == 12
    assert retried_again["reservations"][0]["retry_count"] == 2


def test_persisted_review_budget_blocks_active_reservation_without_spending_budget(tmp_path: Path) -> None:
    budget_path = tmp_path / "review-budget.json"
    values = {
        "proof_identity": "sha256:proof",
        "device": "web-laptop",
        "frame_count": 12,
        "correction_round": 0,
        "correction_kind": "none",
        "frame_index_hash": "sha256:frames",
        "source_artifact_hash": "sha256:video",
        "caption_artifact_hash": "sha256:captions",
    }
    first = workflow.reserve_persisted_review_budget(budget_path, **values)

    with pytest.raises(workflow.WorkflowError, match="already in progress"):
        workflow.reserve_persisted_review_budget(budget_path, **values)

    persisted = json.loads(budget_path.read_text(encoding="utf-8"))
    assert first["ai_review_calls"] == 1
    assert persisted["ai_review_calls"] == 1
    assert persisted["submitted_frames"] == 12
    assert len(persisted["reservations"]) == 1


def test_review_budget_retries_incomplete_exhausted_reservation_without_user_input() -> None:
    budget = {
        "ai_review_calls": 4,
        "submitted_frames": workflow.MAX_CUMULATIVE_SUBMITTED_FRAMES,
        "reservations": [
            {
                "device": "web-laptop",
                "correction_round": 0,
                "frame_index_hash": "sha256:frames",
                "source_artifact_hash": "sha256:video",
                "caption_artifact_hash": "sha256:captions",
                "budget_epoch": 0,
                "lease_expires_at": "2026-08-26T00:00:00+00:00",
                "lease_owner_pid": 987654,
                "retry_count": 3,
            }
        ],
    }

    retried = workflow.reserve_review_budget(
        budget,
        device="web-laptop",
        frame_count=12,
        correction_round=0,
        correction_kind="none",
        frame_index_hash="sha256:frames",
        source_artifact_hash="sha256:video",
        caption_artifact_hash="sha256:captions",
        now=datetime(2026, 8, 26, 0, 10, tzinfo=timezone.utc),
    )

    assert retried["ai_review_calls"] == 4
    assert retried["submitted_frames"] == workflow.MAX_CUMULATIVE_SUBMITTED_FRAMES
    assert retried["reservations"][0]["retry_count"] == 4
    assert retried["reservations"][0]["lease_owner_pid"] == workflow.os.getpid()


def test_review_budget_reclaims_active_reservation_when_owner_pid_is_dead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reservation = {
        "device": "web-laptop",
        "correction_round": 0,
        "frame_index_hash": "sha256:frames",
        "source_artifact_hash": "sha256:video",
        "caption_artifact_hash": "sha256:captions",
        "budget_epoch": 0,
        "lease_expires_at": "2026-08-26T00:15:00+00:00",
        "lease_owner_pid": 987654,
    }
    budget = {
        "ai_review_calls": 1,
        "submitted_frames": 12,
        "reservations": [reservation],
    }

    monkeypatch.setattr(workflow, "_process_is_alive", lambda _pid: False)
    retried = workflow.reserve_review_budget(
        budget,
        device="web-laptop",
        frame_count=12,
        correction_round=0,
        correction_kind="none",
        frame_index_hash="sha256:frames",
        source_artifact_hash="sha256:video",
        caption_artifact_hash="sha256:captions",
        now=datetime(2026, 8, 26, 0, 10, tzinfo=timezone.utc),
    )

    assert retried["ai_review_calls"] == 1
    assert retried["submitted_frames"] == 12
    assert retried["reservations"][0]["retry_count"] == 1
    assert retried["reservations"][0]["lease_owner_pid"] == workflow.os.getpid()


def test_review_budget_rejects_naive_reservation_lease() -> None:
    budget = {
        "ai_review_calls": 1,
        "submitted_frames": 12,
        "reservations": [
            {
                "device": "web-laptop",
                "correction_round": 0,
                "frame_index_hash": "sha256:frames",
                "source_artifact_hash": "sha256:video",
                "caption_artifact_hash": "sha256:captions",
                "budget_epoch": 0,
                "lease_expires_at": "2026-08-26T00:00:00",
            }
        ],
    }

    with pytest.raises(workflow.WorkflowError, match="invalid lease timestamp"):
        workflow.reserve_review_budget(
            budget,
            device="web-laptop",
            frame_count=12,
            correction_round=0,
            correction_kind="none",
            frame_index_hash="sha256:frames",
            source_artifact_hash="sha256:video",
            caption_artifact_hash="sha256:captions",
        )


def test_review_budget_rolls_over_nonpassing_prior_sources_for_new_initial_source() -> None:
    budget = {
        "ai_review_calls": 4,
        "submitted_frames": 46,
        "product_code_correction_rounds": [1],
        "reservations": [
            {"device": "web-laptop", "source_artifact_hash": "sha256:old-video-a", "status": "product_defect"},
            {"device": "web-laptop", "source_artifact_hash": "sha256:old-video-b", "status": "uncertain"},
        ],
    }

    rolled = workflow.reserve_review_budget(
        budget,
        device="web-laptop",
        frame_count=12,
        correction_round=0,
        correction_kind="none",
        frame_index_hash="sha256:new-frames",
        source_artifact_hash="sha256:new-video",
        caption_artifact_hash="sha256:new-captions",
    )

    assert rolled["active_epoch"] == 1
    assert rolled["ai_review_calls"] == 1
    assert rolled["submitted_frames"] == 12
    assert rolled["product_code_correction_rounds"] == []
    assert rolled["superseded_review_epochs"] == [
        {
            "budget_epoch": 0,
            "reason": "new_source_after_nonpassing_device_reviews",
            "device": "web-laptop",
            "reservation_count": 2,
            "ai_review_calls": 4,
            "submitted_frames": 46,
            "superseded_by_source_artifact_hash": "sha256:new-video",
        }
    ]
    assert rolled["reservations"][-1]["budget_epoch"] == 1


def test_review_budget_does_not_roll_over_passed_prior_source() -> None:
    budget = {
        "ai_review_calls": 4,
        "submitted_frames": 46,
        "reservations": [
            {"device": "web-laptop", "source_artifact_hash": "sha256:old-video", "status": "passed"},
        ],
    }

    with pytest.raises(workflow.WorkflowError, match="frame budget"):
        workflow.reserve_review_budget(
            budget,
            device="web-laptop",
            frame_count=12,
            correction_round=0,
            correction_kind="none",
            source_artifact_hash="sha256:new-video",
        )


def test_review_budget_rolls_over_when_latest_source_supersedes_an_older_pass() -> None:
    budget = {
        "ai_review_calls": 4,
        "submitted_frames": 46,
        "reservations": [
            {"device": "web-laptop", "source_artifact_hash": "sha256:passed-video", "status": "passed"},
            {"device": "web-laptop", "source_artifact_hash": "sha256:failed-video", "status": "capture_defect"},
        ],
    }

    rolled = workflow.reserve_review_budget(
        budget,
        device="web-laptop",
        frame_count=12,
        correction_round=0,
        correction_kind="none",
        source_artifact_hash="sha256:fixed-video",
    )

    assert rolled["active_epoch"] == 1
    assert rolled["ai_review_calls"] == 1
    assert rolled["superseded_review_epochs"][-1]["reason"] == "new_source_after_nonpassing_device_reviews"


def test_review_budget_rolls_over_for_first_review_of_another_required_device() -> None:
    budget = {
        "active_epoch": 2,
        "ai_review_calls": 4,
        "submitted_frames": 48,
        "reservations": [
            {
                "device": "web-laptop",
                "source_artifact_hash": "sha256:laptop-video",
                "status": "passed",
            },
        ],
    }

    rolled = workflow.reserve_review_budget(
        budget,
        device="web-phone",
        frame_count=12,
        correction_round=0,
        correction_kind="none",
        frame_index_hash="sha256:phone-frames",
        source_artifact_hash="sha256:phone-video",
        caption_artifact_hash="sha256:phone-captions",
    )

    assert rolled["active_epoch"] == 3
    assert rolled["ai_review_calls"] == 1
    assert rolled["submitted_frames"] == 12
    assert rolled["superseded_review_epochs"] == [
        {
            "budget_epoch": 2,
            "reason": "first_review_for_new_device",
            "device": "web-phone",
            "reservation_count": 1,
            "ai_review_calls": 4,
            "submitted_frames": 48,
            "superseded_by_source_artifact_hash": "sha256:phone-video",
        }
    ]
    assert rolled["reservations"][-1]["budget_epoch"] == 3


def test_review_budget_allows_only_one_product_code_correction_round() -> None:
    budget = workflow.reserve_review_budget(
        {},
        device="web-phone",
        frame_count=1,
        correction_round=1,
        correction_kind="product",
    )

    with pytest.raises(workflow.WorkflowError, match="product-code correction"):
        workflow.reserve_review_budget(
            budget,
            device="web-laptop",
            frame_count=1,
            correction_round=2,
            correction_kind="product",
        )


def test_review_budget_reuses_cached_unchanged_device_evidence() -> None:
    budget = workflow.reserve_review_budget(
        {},
        device="web-phone",
        frame_count=12,
        correction_round=0,
        correction_kind="none",
        frame_index_hash="sha256:frames",
        source_artifact_hash="sha256:video",
    )
    budget["reservations"][0]["receipt_path"] = "review-receipt.json"

    with pytest.raises(workflow.WorkflowError, match="cached receipt"):
        workflow.reserve_review_budget(
            budget,
            device="web-phone",
            frame_count=12,
            correction_round=1,
            correction_kind="capture",
            frame_index_hash="sha256:frames",
            source_artifact_hash="sha256:video",
        )

    changed_captions = workflow.reserve_review_budget(
        budget,
        device="web-phone",
        frame_count=12,
        correction_round=1,
        correction_kind="capture",
        frame_index_hash="sha256:frames",
        source_artifact_hash="sha256:video",
        caption_artifact_hash="sha256:changed-captions",
    )
    assert changed_captions["ai_review_calls"] == 2


def test_review_budget_retries_incomplete_unchanged_device_reservation() -> None:
    budget = workflow.reserve_review_budget(
        {},
        device="web-phone",
        frame_count=12,
        correction_round=0,
        correction_kind="none",
        frame_index_hash="sha256:frames",
        source_artifact_hash="sha256:video",
    )

    retry = workflow.reserve_review_budget(
        budget,
        device="web-phone",
        frame_count=12,
        correction_round=1,
        correction_kind="capture",
        frame_index_hash="sha256:frames",
        source_artifact_hash="sha256:video",
    )

    assert retry["ai_review_calls"] == 2


def test_uncertain_review_requires_user_input_immediately() -> None:
    result = workflow.review_next_action(
        {
            "status": "uncertain",
            "assertions": [],
            "incidental_findings": [],
            "return_stage": "review",
            "next_action": "Clarify whether the loading state is expected.",
        },
        prior_defect_fingerprints=[],
    )

    assert result["requires_user_input"] is True
    assert result["automatic_correction"] is False


def test_obvious_product_defect_routes_to_automatic_implementation_repair() -> None:
    result = workflow.review_next_action(
        {
            "status": "product_defect",
            "confidence": 0.98,
            "assertions": [],
            "frame_reviews": [],
            "incidental_findings": [
                {
                    "id": "UI-1",
                    "category": "clipping",
                    "severity": "blocking",
                    "confidence": 0.98,
                    "intent": "obvious",
                    "quality_categories": ["layout"],
                    "frames": ["frames/frame-0001.png"],
                    "observation": "Text is unreadable against the menu background.",
                }
            ],
            "return_stage": "capture",
            "next_action": "Crop around the unreadable menu.",
        },
        prior_defect_fingerprints=[],
    )

    assert result["requires_user_input"] is False
    assert result["automatic_correction"] is True
    assert result["disposition"] == "auto_fix"
    assert result["return_stage"] == "implementation"
    assert "failing test" in result["next_action"]


def test_frame_only_contrast_finding_requires_user_intent() -> None:
    review = {
        "status": "product_defect",
        "confidence": 0.98,
        "assertions": [
            {"id": "heading.visible", "verdict": "supported", "frames": ["frames/frame.png"]}
        ],
        "frame_reviews": [frame_quality_review("frames/frame.png", readability="fail")],
        "incidental_findings": [
            {
                "id": "UI-1",
                "category": "contrast",
                "severity": "blocking",
                "confidence": 0.98,
                "intent": "obvious",
                "quality_categories": ["readability"],
                "frames": ["frames/frame.png"],
                "observation": "The intentionally subdued heading appears pale.",
            }
        ],
        "return_stage": "implementation",
        "next_action": "Change the product colors.",
    }

    assert workflow.require_user_intent_for_subjective_visual_findings(review) is True
    assert review["status"] == "uncertain"
    assert review["return_stage"] == "review"
    assert review["assertions"][0]["verdict"] == "supported"
    assert review["frame_reviews"][0]["checks"]["readability"] == "uncertain"
    assert review["incidental_findings"][0]["intent"] == "unclear"


def test_unclear_product_intent_requires_user_consent_before_code_changes() -> None:
    result = workflow.review_next_action(
        {
            "status": "product_defect",
            "confidence": 0.98,
            "assertions": [],
            "frame_reviews": [],
            "incidental_findings": [
                {
                    "id": "UI-1",
                    "category": "geometry",
                    "severity": "blocking",
                    "confidence": 0.98,
                    "intent": "unclear",
                    "quality_categories": ["layout", "geometry"],
                    "frames": ["frames/frame-0001.png"],
                    "observation": "The content uses only half of the available pane, but this may be intentional.",
                }
            ],
            "return_stage": "implementation",
            "next_action": "Ask whether the narrow layout is intentional.",
        },
        prior_defect_fingerprints=[],
    )

    assert result["requires_user_input"] is True
    assert result["automatic_correction"] is False
    assert result["disposition"] == "ask_user"
    assert result["return_stage"] == "review"
    assert "consent" in result["next_action"]


def test_repeated_defect_requires_user_input() -> None:
    review = {
        "status": "render_defect",
        "assertions": [
            {
                "id": "visible",
                "verdict": "wrong_time",
                "frames": ["frames/frame-0001.png"],
                "observation": "Caption overlaps the control.",
            }
        ],
        "incidental_findings": [],
        "return_stage": "render",
        "next_action": "Move the caption.",
    }
    fingerprint = workflow.review_defect_fingerprint(review)

    result = workflow.review_next_action(review, prior_defect_fingerprints=[fingerprint])

    assert result["requires_user_input"] is True
    assert result["automatic_correction"] is False


def _write_review_run(tmp_path: Path, *, frame_path: str = "frames/frame.png") -> tuple[Path, dict[str, object]]:
    from scripts import spec_demo

    run_dir = tmp_path
    frame = run_dir / frame_path
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes(b"frame")
    video = run_dir / "demo.mp4"
    video.write_bytes(b"video")
    request = spec_demo.build_review_request(
        spec_id="example",
        subject_commit="a" * 40,
        captions=[{"id": "CAP-1", "narration_id": "NARR-1", "text": "Visible.", "start": 0.0, "end": 1.0, "claim_ids": ["visible"]}],
        expected_proof=[{"claim_id": "visible", "text": "Visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[0.0, 1.0]]}],
        frames=[{"timestamp_seconds": 0.0, "path": frame_path, "sha256": workflow._file_sha256(frame)}],
        video_metadata={
            "duration_seconds": 1.0,
            "sha256": workflow._file_sha256(video),
            "width": 320,
            "height": 240,
            "device_profile": "web-phone",
        },
        narration_audio={"status": "not_required", "provider": "", "model": "", "voice": "", "path": "", "sha256": "", "mime_type": "", "duration_seconds": 0.0, "reused_from": ""},
        proof_contract_hash="sha256:" + "b" * 64,
    )
    (run_dir / "review-request.json").write_text(json.dumps(request), encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "subject_commit": request["subject_commit"],
                "proof_contract_hash": request["proof_contract_hash"],
                "proof_group_id": request["proof_group_id"],
                "video_path": str(video),
                "video_metadata": request["video_metadata"],
                "expected_proof": request["expected_proof"],
                "review": {"status": "pending", "attempts": []},
            }
        ),
        encoding="utf-8",
    )
    return run_dir, request


def test_review_run_preserves_reviewer_frame_hash_and_contract_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REPO_ROOT", tmp_path)
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "first")
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")

    def reviewer(prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        prompt_data = json.loads(prompt.read_text(encoding="utf-8"))
        assert "every listed quality category must be fail or uncertain on every cited frame" in prompt_data["instructions"]
        assert "split findings when category sets differ" in prompt_data["required_output"]["incidental_findings"]
        assert prompt_data["review_request"]["frames"][0]["read_path"] == "frames/frame.png"
        return (
            {
                "status": "passed",
                "confidence": 0.99,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png")],
                "assertions": [{"id": "visible", "verdict": "supported", "frames": ["frames/frame.png"], "observation": "Visible in the frame."}],
                "incidental_findings": [],
                "return_stage": "complete",
                "next_action": "Publish.",
            },
            "ses_reviewer",
        )

    result = workflow.review_run(
        run_dir=run_dir,
        correction_round=0,
        correction_kind="none",
        reviewer_runner=reviewer,
    )

    assert result["status"] == "passed"
    assert len(list((tmp_path / "budgets").glob("*.json"))) == 1

    second_dir, _ = _write_review_run(tmp_path / "proof-videos" / "second")
    cached = workflow.review_run(
        run_dir=second_dir,
        correction_round=0,
        correction_kind="none",
        reviewer_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must use cache")),
    )
    assert cached["cached"] is True
    assert cached["status"] == "passed"
    assert cached["manifest"]["review"]["status"] == "passed"
    assert (second_dir / "review-receipt.json").is_file()
    from scripts import spec_demo

    spec_demo.require_review_receipt_integrity(second_dir, cached["manifest"])


def test_review_run_accepts_control_plane_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_plane_root = tmp_path / "control-plane"
    monkeypatch.setattr(workflow, "CONTROL_PLANE_ROOT", control_plane_root)
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path / "worktree" / "test-results")
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(
        control_plane_root / "test-results" / "proof-videos" / "session" / "run"
    )

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "passed",
                "confidence": 0.99,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png")],
                "assertions": [
                    {
                        "id": "visible",
                        "verdict": "supported",
                        "frames": ["frames/frame.png"],
                        "observation": "Visible.",
                    }
                ],
                "incidental_findings": [],
                "return_stage": "complete",
                "next_action": "Publish.",
            },
            "ses_reviewer",
        )

    result = workflow.review_run(
        run_dir=run_dir,
        correction_round=0,
        correction_kind="none",
        reviewer_runner=reviewer,
    )

    assert result["status"] == "passed"


def test_review_run_recovers_receipt_written_before_cache_attachment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "recover-written-receipt")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "passed",
                "confidence": 0.99,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png")],
                "assertions": [{"id": "visible", "verdict": "supported", "frames": ["frames/frame.png"], "observation": "Visible."}],
                "incidental_findings": [],
                "return_stage": "complete",
                "next_action": "Publish.",
            },
            "ses_reviewer",
        )

    workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)
    budget_path = next((tmp_path / "budgets").glob("*.json"))
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    for key in ("receipt_path", "receipt_sha256", "manifest_path", "status"):
        budget["reservations"][0].pop(key, None)
    budget_path.write_text(json.dumps(budget, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    recovered = workflow.review_run(
        run_dir=run_dir,
        correction_round=0,
        correction_kind="none",
        reviewer_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must recover persisted receipt")),
    )

    assert recovered["cached"] is True
    assert recovered["status"] == "passed"
    assert recovered["budget"]["ai_review_calls"] == 1


def test_review_run_rolls_back_persistence_when_cache_attachment_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "review-rollback")
    original_manifest = (run_dir / "manifest.json").read_bytes()

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "capture_defect",
                "confidence": 0.96,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png", proof_alignment="fail")],
                "assertions": [
                    {"id": "visible", "verdict": "not_visible", "frames": ["frames/frame.png"], "observation": "Not visible."}
                ],
                "incidental_findings": [
                    {
                        "id": "UI-1",
                        "category": "loading",
                        "severity": "warning",
                        "confidence": 0.96,
                        "intent": "obvious",
                        "quality_categories": ["proof_alignment"],
                        "frames": ["frames/frame.png"],
                        "observation": "The expected state is not visible.",
                    }
                ],
                "return_stage": "capture",
                "next_action": "Capture the expected state.",
            },
            "ses_reviewer",
        )

    monkeypatch.setattr(
        workflow,
        "record_cached_review",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(workflow.WorkflowError("cache attachment failed")),
    )

    with pytest.raises(workflow.WorkflowError, match="cache attachment failed"):
        workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)

    budget = json.loads(next((tmp_path / "budgets").glob("*.json")).read_text(encoding="utf-8"))
    assert (run_dir / "manifest.json").read_bytes() == original_manifest
    assert not (run_dir / "review-receipt.json").exists()
    assert budget.get("defect_fingerprints", []) == []
    assert "receipt_path" not in budget["reservations"][0]


@pytest.mark.parametrize("status", ["uncertain", "capture_defect", "render_defect", "product_defect"])
def test_review_run_recovers_nonpassing_receipt_without_new_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / status)
    intent = "unclear" if status == "uncertain" else "obvious"
    quality_result = "uncertain" if status == "uncertain" else "fail"

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": status,
                "confidence": 0.95,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png", proof_alignment=quality_result)],
                "assertions": [{"id": "visible", "verdict": "not_visible", "frames": ["frames/frame.png"], "observation": "Not visible."}],
                "incidental_findings": [
                    {
                        "id": "UI-1",
                        "category": "loading",
                        "severity": "blocking" if status == "product_defect" else "warning",
                        "confidence": 0.95,
                        "intent": intent,
                        "quality_categories": ["proof_alignment"],
                        "frames": ["frames/frame.png"],
                        "observation": "The expected state is not visible.",
                    }
                ],
                "return_stage": "review" if status == "uncertain" else "capture",
                "next_action": "Resolve the blocker.",
            },
            "ses_reviewer",
        )

    first = workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)
    budget_path = next((tmp_path / "budgets").glob("*.json"))
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    for key in ("receipt_path", "receipt_sha256", "manifest_path", "status"):
        budget["reservations"][0].pop(key, None)
    budget_path.write_text(json.dumps(budget, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    recovered = workflow.review_run(
        run_dir=run_dir,
        correction_round=0,
        correction_kind="none",
        reviewer_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must recover blocker receipt")),
    )

    assert first["status"] == status
    assert recovered["cached"] is True
    assert recovered["status"] == status
    assert recovered["budget"]["ai_review_calls"] == 1
    assert recovered["manifest"]["review"]["attempt_count"] == 1


def test_review_run_includes_blocker_media_for_failed_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "blocked")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "render_defect",
                "confidence": 0.95,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png", application_state="fail", proof_alignment="fail")],
                "assertions": [{"id": "visible", "verdict": "not_visible", "frames": ["frames/frame.png"], "observation": "Blank frame."}],
                "incidental_findings": [
                    {
                        "id": "UI-1",
                        "category": "loading",
                        "severity": "blocking",
                        "confidence": 0.99,
                        "intent": "obvious",
                        "quality_categories": ["application_state", "proof_alignment"],
                        "frames": ["frames/frame.png"],
                        "observation": "The frame is blank instead of showing the proof state.",
                    }
                ],
                "return_stage": "render",
                "next_action": "Regenerate the video.",
            },
            "ses_reviewer",
        )

    result = workflow.review_run(
        run_dir=run_dir,
        correction_round=0,
        correction_kind="none",
        reviewer_runner=reviewer,
    )

    blocker_media = result["blocker_media"]
    assert blocker_media["media_status"] == "available"
    assert blocker_media["image_status"] == "available"
    assert blocker_media["video_status"] == "available"
    assert blocker_media["video_path"] == str(run_dir / "demo.mp4")
    assert blocker_media["upload_command"].startswith("python3 scripts/opencode_response_media.py ")
    assert blocker_media["image_path"] == str(run_dir / "frames" / "frame.png")
    assert blocker_media["image_upload_command"].startswith("python3 scripts/opencode_response_media.py ")
    assert result["receipt"]["workflow"]["blocker_media"] == blocker_media


def test_blocker_media_uses_assertion_frame_when_failed_review_has_no_finding(tmp_path: Path) -> None:
    run_dir = tmp_path / "proof"
    frame = run_dir / "frames" / "frame.png"
    video = run_dir / "demo.mp4"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"frame")
    video.write_bytes(b"video")
    manifest = {
        "video_path": str(video),
        "review": {
            "status": "failed",
            "attempts": [
                {
                    "assertions": [
                        {"id": "visible", "verdict": "not_visible", "frames": ["frames/frame.png"]}
                    ],
                    "incidental_findings": [],
                    "frame_reviews": [],
                    "reviewed_frames": ["frames/frame.png"],
                }
            ],
        },
    }

    blocker_media = workflow.proof_blocker_media(run_dir, manifest, "capture_defect")

    assert blocker_media["image_path"] == str(frame)
    assert blocker_media["image_upload_command"].startswith("python3 scripts/opencode_response_media.py ")


def test_blocker_media_keeps_cited_image_when_video_is_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "proof"
    frame = run_dir / "frames" / "frame.png"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"frame")
    manifest = {
        "video_path": str(run_dir / "missing.mp4"),
        "review": {
            "attempts": [
                {
                    "incidental_findings": [
                        {"id": "UI-1", "intent": "unclear", "frames": ["frames/frame.png"]}
                    ],
                    "assertions": [],
                    "frame_reviews": [],
                    "reviewed_frames": ["frames/frame.png"],
                }
            ]
        },
    }

    blocker_media = workflow.proof_blocker_media(run_dir, manifest, "uncertain")

    assert blocker_media["media_status"] == "missing"
    assert blocker_media["image_status"] == "available"
    assert blocker_media["video_status"] == "missing"
    assert blocker_media["finding_id"] == "UI-1"
    assert blocker_media["image_path"] == str(frame)
    assert blocker_media["image_upload_command"].startswith("python3 scripts/opencode_response_media.py ")
    assert "upload_command" not in blocker_media


def test_blocker_media_selects_unclear_consent_finding_frame(tmp_path: Path) -> None:
    run_dir = tmp_path / "proof"
    frames_dir = run_dir / "frames"
    frames_dir.mkdir(parents=True)
    obvious_frame = frames_dir / "obvious.png"
    unclear_frame = frames_dir / "unclear.png"
    obvious_frame.write_bytes(b"obvious")
    unclear_frame.write_bytes(b"unclear")
    manifest = {
        "review": {
            "attempts": [
                {
                    "incidental_findings": [
                        {"id": "UI-1", "intent": "obvious", "frames": ["frames/obvious.png"]},
                        {"id": "UI-2", "intent": "unclear", "frames": ["frames/unclear.png"]},
                    ],
                    "assertions": [],
                    "frame_reviews": [],
                    "reviewed_frames": ["frames/obvious.png", "frames/unclear.png"],
                }
            ]
        }
    }

    blocker_media = workflow.proof_blocker_media(run_dir, manifest, "uncertain")

    assert blocker_media["finding_id"] == "UI-2"
    assert blocker_media["image_path"] == str(unclear_frame)


def test_cached_failed_review_preserves_representative_frame(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import spec_demo

    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "cached-blocker")
    receipt = {
        "status": "capture_defect",
        "reviewed_frames": ["frames/frame.png"],
        "frame_reviews": [frame_quality_review("frames/frame.png", proof_alignment="fail")],
        "assertions": [
            {"id": "visible", "verdict": "not_visible", "frames": ["frames/frame.png"], "observation": "Not visible."}
        ],
        "incidental_findings": [],
        "workflow": {},
    }
    monkeypatch.setattr(
        workflow,
        "load_cached_review",
        lambda *_args, **_kwargs: {"status": "capture_defect", "receipt": receipt, "budget": {}, "cached": True},
    )
    monkeypatch.setattr(spec_demo, "record_review_receipt", lambda _run_dir, _receipt, **_kwargs: {"review": {"status": "failed"}})
    monkeypatch.setattr(workflow, "record_cached_review", lambda *_args, **_kwargs: {})

    result = workflow.review_run(
        run_dir=run_dir,
        correction_round=0,
        correction_kind="none",
        reviewer_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must use cache")),
    )

    assert result["blocker_media"]["image_path"] == str(run_dir / "frames" / "frame.png")
    assert result["blocker_media"]["image_upload_command"].startswith("python3 scripts/opencode_response_media.py ")


def test_user_approved_visual_intent_resolves_only_cited_uncertainty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "approved-intent")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "uncertain",
                "confidence": 0.9,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png", readability="uncertain")],
                "assertions": [
                    {"id": "visible", "verdict": "supported", "frames": ["frames/frame.png"], "observation": "Visible."}
                ],
                "incidental_findings": [
                    {
                        "id": "UI-1",
                        "category": "contrast",
                        "severity": "warning",
                        "confidence": 0.9,
                        "intent": "unclear",
                        "quality_categories": ["readability"],
                        "frames": ["frames/frame.png"],
                        "observation": "The intentionally subdued heading appears pale.",
                    }
                ],
                "return_stage": "review",
                "next_action": "Ask the user.",
            },
            "ses_reviewer",
        )

    workflow.review_run(
        run_dir=run_dir,
        correction_round=0,
        correction_kind="none",
        reviewer_runner=reviewer,
    )
    original_hash = workflow._file_sha256(run_dir / "review-receipt.json")
    budget_path = next((tmp_path / "budgets").glob("*.json"))
    stale_budget = budget_path.read_text(encoding="utf-8")

    result = workflow.approve_visual_intent(
        run_dir=run_dir,
        finding_id="UI-1",
        reason="User confirmed the pale heading is intentional visual hierarchy.",
        approved_at="2026-08-25T23:43:00Z",
    )

    assert result["status"] == "passed"
    assert result["approval"]["original_receipt_sha256"] == original_hash
    receipt = json.loads((run_dir / "review-receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "passed"
    assert receipt["frame_reviews"][0]["checks"]["readability"] == "pass"
    assert receipt["incidental_findings"] == []
    assert receipt["approved_visual_intents"][0]["finding_id"] == "UI-1"
    assert result["manifest"]["review"]["attempt_count"] == 2

    budget_path.write_text(stale_budget, encoding="utf-8")

    cached = workflow.review_run(
        run_dir=run_dir,
        correction_round=0,
        correction_kind="none",
        reviewer_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must reuse approved receipt")),
    )
    assert cached["cached"] is True
    assert cached["status"] == "passed"


def test_cached_subjective_normalization_replaces_latest_attempt_when_budget_is_full(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import spec_demo

    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "normalize-full-budget")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "product_defect",
                "confidence": 0.96,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png", readability="fail")],
                "assertions": [
                    {"id": "visible", "verdict": "contradicted", "frames": ["frames/frame.png"], "observation": "The heading is too pale."}
                ],
                "incidental_findings": [
                    {
                        "id": "UI-1",
                        "category": "contrast",
                        "severity": "blocking",
                        "confidence": 0.96,
                        "intent": "obvious",
                        "quality_categories": ["readability"],
                        "frames": ["frames/frame.png"],
                        "observation": "The intentionally subdued heading appears pale.",
                    }
                ],
                "return_stage": "implementation",
                "next_action": "Change the product colors.",
            },
            "ses_reviewer",
        )

    workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)
    receipt = json.loads((run_dir / "review-receipt.json").read_text(encoding="utf-8"))
    receipt_without_attempt = {key: value for key, value in receipt.items() if key != "attempt_number"}
    spec_demo.record_review_receipt(run_dir, receipt_without_attempt)
    spec_demo.record_review_receipt(run_dir, receipt_without_attempt)
    budget_path = next((tmp_path / "budgets").glob("*.json"))
    workflow.record_cached_review(
        budget_path,
        device="web-phone",
        correction_round=0,
        frame_index_hash=request["frame_index_hash"],
        source_artifact_hash=request["video_metadata"]["sha256"],
        caption_artifact_hash=str(request["video_metadata"].get("captions_sha256") or ""),
        run_dir=run_dir,
        status="uncertain",
    )

    cached = workflow.review_run(
        run_dir=run_dir,
        correction_round=0,
        correction_kind="none",
        reviewer_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must use cache")),
    )

    assert cached["cached"] is True
    assert cached["status"] == "uncertain"
    assert cached["manifest"]["review"]["attempt_count"] == 3
    assert len(cached["manifest"]["review"]["attempts"]) == 3


def test_user_approved_visual_intent_replaces_latest_duplicate_when_budget_is_full(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import spec_demo

    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "approve-full-budget")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "uncertain",
                "confidence": 0.96,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png", readability="uncertain")],
                "assertions": [
                    {"id": "visible", "verdict": "supported", "frames": ["frames/frame.png"], "observation": "The heading is visible."}
                ],
                "incidental_findings": [
                    {
                        "id": "UI-1",
                        "category": "contrast",
                        "severity": "blocking",
                        "confidence": 0.96,
                        "intent": "unclear",
                        "quality_categories": ["readability"],
                        "frames": ["frames/frame.png"],
                        "observation": "The intentionally subdued heading appears pale.",
                    }
                ],
                "return_stage": "review",
                "next_action": "Ask the user.",
            },
            "ses_reviewer",
        )

    workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)
    receipt = json.loads((run_dir / "review-receipt.json").read_text(encoding="utf-8"))
    receipt_without_attempt = {key: value for key, value in receipt.items() if key != "attempt_number"}
    spec_demo.record_review_receipt(run_dir, receipt_without_attempt)
    spec_demo.record_review_receipt(run_dir, receipt_without_attempt)
    manifest_before = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    retained_original = spec_demo.review_attempt_sha256(manifest_before["review"]["attempts"][1])
    current_receipt_hash = workflow._file_sha256(run_dir / "review-receipt.json")

    result = workflow.approve_visual_intent(
        run_dir=run_dir,
        finding_id="UI-1",
        reason="User confirmed the pale heading is intentional visual hierarchy.",
        approved_at="2026-08-27T00:20:00Z",
    )

    receipt = json.loads((run_dir / "review-receipt.json").read_text(encoding="utf-8"))
    attempts = result["manifest"]["review"]["attempts"]
    approval_receipt_hash = workflow._file_sha256(run_dir / "review-receipt.json")
    assert result["status"] == "passed"
    assert result["manifest"]["review"]["attempt_count"] == 3
    assert len(attempts) == 3
    assert receipt["attempt_number"] == 3
    assert receipt["assertions"][0]["verdict"] == "supported"
    assert receipt["approved_visual_intents"][0]["original_receipt_sha256"] == retained_original
    assert receipt["approved_visual_intents"][0]["original_receipt_sha256"] != current_receipt_hash
    assert result["budget"]["reservations"][0]["receipt_sha256"] == approval_receipt_hash
    spec_demo.require_review_receipt_integrity(run_dir, result["manifest"], verify_video=False)


def test_user_approved_visual_intent_rejects_unrelated_same_frame_assertion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "approval-unrelated-assertion")
    request["expected_proof"] = [
        {"claim_id": "heading.intentional", "text": "Heading visual hierarchy is visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[0.0, 1.0]]},
        {"claim_id": "cta.visible", "text": "The primary CTA is visible.", "acceptance_criteria": ["AC-2"], "evidence_intervals": [[0.0, 1.0]]},
    ]
    request["captions"][0]["claim_ids"] = ["heading.intentional", "cta.visible"]
    (run_dir / "review-request.json").write_text(json.dumps(request), encoding="utf-8")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["expected_proof"] = request["expected_proof"]
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "uncertain",
                "confidence": 0.96,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png", readability="uncertain")],
                "assertions": [
                    {
                        "id": "heading.intentional",
                        "verdict": "ambiguous",
                        "frames": ["frames/frame.png"],
                        "observation": "The heading may be too pale.",
                    },
                    {
                        "id": "cta.visible",
                        "verdict": "contradicted",
                        "frames": ["frames/frame.png"],
                        "observation": "The primary CTA is missing from the captured state.",
                    },
                ],
                "incidental_findings": [
                    {
                        "id": "UI-1",
                        "category": "contrast",
                        "severity": "blocking",
                        "confidence": 0.96,
                        "intent": "unclear",
                        "quality_categories": ["readability"],
                        "frames": ["frames/frame.png"],
                        "observation": "The intentionally subdued heading appears pale.",
                    }
                ],
                "return_stage": "review",
                "next_action": "Ask the user.",
            },
            "ses_reviewer",
        )

    workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)

    with pytest.raises(workflow.WorkflowError, match="unsupported proof assertion"):
        workflow.approve_visual_intent(
            run_dir=run_dir,
            finding_id="UI-1",
            reason="User confirmed the pale heading is intentional visual hierarchy.",
            approved_at="2026-08-27T00:20:00Z",
        )

    receipt = json.loads((run_dir / "review-receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "uncertain"
    assert receipt["assertions"][0]["verdict"] == "ambiguous"
    assert receipt["assertions"][1]["verdict"] == "contradicted"


def test_user_approved_visual_intent_requires_full_prior_finding_identity_when_budget_is_full(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import spec_demo

    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "approval-finding-identity")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "uncertain",
                "confidence": 0.96,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png", readability="uncertain")],
                "assertions": [
                    {
                        "id": "visible",
                        "verdict": "supported",
                        "frames": ["frames/frame.png"],
                        "observation": "The heading is visible.",
                    }
                ],
                "incidental_findings": [
                    {
                        "id": "UI-1",
                        "category": "contrast",
                        "severity": "blocking",
                        "confidence": 0.96,
                        "intent": "unclear",
                        "quality_categories": ["readability"],
                        "frames": ["frames/frame.png"],
                        "observation": "The intentionally subdued heading appears pale.",
                    }
                ],
                "return_stage": "review",
                "next_action": "Ask the user.",
            },
            "ses_reviewer",
        )

    workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)
    receipt = json.loads((run_dir / "review-receipt.json").read_text(encoding="utf-8"))
    receipt_without_attempt = {key: value for key, value in receipt.items() if key != "attempt_number"}
    spec_demo.record_review_receipt(run_dir, receipt_without_attempt)
    spec_demo.record_review_receipt(run_dir, receipt_without_attempt)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    for attempt in manifest["review"]["attempts"][:-1]:
        attempt["incidental_findings"][0]["observation"] = "A different same-frame contrast concern."
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(workflow.WorkflowError, match="no prior matching unclear receipt"):
        workflow.approve_visual_intent(
            run_dir=run_dir,
            finding_id="UI-1",
            reason="User confirmed the pale heading is intentional visual hierarchy.",
            approved_at="2026-08-27T00:20:00Z",
        )


@pytest.mark.parametrize(
    ("finding_category", "quality_category", "error"),
    [
        ("geometry", "geometry", "color or contrast finding"),
        ("contrast", "proof_alignment", "proof-alignment or structural quality categories"),
    ],
)
def test_user_approved_visual_intent_rejects_non_subjective_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    finding_category: str,
    quality_category: str,
    error: str,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / f"approval-{finding_category}-{quality_category}")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "uncertain",
                "confidence": 0.96,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png", **{quality_category: "uncertain"})],
                "assertions": [
                    {"id": "visible", "verdict": "supported", "frames": ["frames/frame.png"], "observation": "Visible."}
                ],
                "incidental_findings": [
                    {
                        "id": "UI-1",
                        "category": finding_category,
                        "severity": "blocking",
                        "confidence": 0.96,
                        "intent": "unclear",
                        "quality_categories": [quality_category],
                        "frames": ["frames/frame.png"],
                        "observation": "The visual treatment may be intentional.",
                    }
                ],
                "return_stage": "review",
                "next_action": "Ask the user.",
            },
            "ses_reviewer",
        )

    workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)

    with pytest.raises(workflow.WorkflowError, match=error):
        workflow.approve_visual_intent(
            run_dir=run_dir,
            finding_id="UI-1",
            reason="User confirmed this treatment is intentional.",
            approved_at="2026-08-27T00:20:00Z",
        )


def test_user_approved_visual_intent_rolls_back_when_cache_attachment_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "approval-rollback")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "uncertain",
                "confidence": 0.96,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png", readability="uncertain")],
                "assertions": [
                    {"id": "visible", "verdict": "supported", "frames": ["frames/frame.png"], "observation": "Visible."}
                ],
                "incidental_findings": [
                    {
                        "id": "UI-1",
                        "category": "contrast",
                        "severity": "blocking",
                        "confidence": 0.96,
                        "intent": "unclear",
                        "quality_categories": ["readability"],
                        "frames": ["frames/frame.png"],
                        "observation": "The intentionally subdued heading appears pale.",
                    }
                ],
                "return_stage": "review",
                "next_action": "Ask the user.",
            },
            "ses_reviewer",
        )

    workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)
    budget_path = next((tmp_path / "budgets").glob("*.json"))
    original_files = {
        run_dir / "review-receipt.json": (run_dir / "review-receipt.json").read_bytes(),
        run_dir / "manifest.json": (run_dir / "manifest.json").read_bytes(),
        budget_path: budget_path.read_bytes(),
    }
    with pytest.raises(workflow.WorkflowError, match="valid timezone-aware approved_at timestamp"):
        workflow.approve_visual_intent(
            run_dir=run_dir,
            finding_id="UI-1",
            reason="User confirmed the pale heading is intentional visual hierarchy.",
            approved_at="2026-08-27T00:20:00",
        )
    assert {path: path.read_bytes() for path in original_files} == original_files

    monkeypatch.setattr(
        workflow,
        "record_cached_review",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(workflow.WorkflowError("cache attachment failed")),
    )

    with pytest.raises(workflow.WorkflowError, match="cache attachment failed"):
        workflow.approve_visual_intent(
            run_dir=run_dir,
            finding_id="UI-1",
            reason="User confirmed the pale heading is intentional visual hierarchy.",
            approved_at="2026-08-27T00:20:00Z",
        )

    assert {path: path.read_bytes() for path in original_files} == original_files


def test_review_publication_integrity_rejects_empty_self_consistent_quality_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "integrity")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "passed",
                "confidence": 0.99,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png")],
                "assertions": [{"id": "visible", "verdict": "supported", "frames": ["frames/frame.png"], "observation": "Visible."}],
                "incidental_findings": [],
                "return_stage": "complete",
                "next_action": "Publish.",
            },
            "ses_reviewer",
        )

    result = workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)
    receipt_path = run_dir / "review-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["reviewed_frames"] = []
    receipt["frame_reviews"] = []
    receipt["assertions"] = []
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    result["manifest"]["review"]["receipt_sha256"] = "sha256:" + hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    from scripts import spec_demo

    with pytest.raises(spec_demo.DemonstrationError, match="complete passed frame quality scans"):
        spec_demo.require_review_receipt_integrity(run_dir, result["manifest"], verify_video=False)


def test_review_publication_integrity_rejects_changed_canonical_claim_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "changed-request")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "passed",
                "confidence": 0.99,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png")],
                "assertions": [{"id": "visible", "verdict": "supported", "frames": ["frames/frame.png"], "observation": "Visible."}],
                "incidental_findings": [],
                "return_stage": "complete",
                "next_action": "Publish.",
            },
            "ses_reviewer",
        )

    result = workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)
    request_path = run_dir / "review-request.json"
    changed = json.loads(request_path.read_text(encoding="utf-8"))
    changed["expected_proof"][0]["text"] = "A different visual claim."
    request_path.write_text(json.dumps(changed), encoding="utf-8")

    from scripts import spec_demo

    with pytest.raises(spec_demo.DemonstrationError, match="passed manifest review"):
        spec_demo.require_review_receipt_integrity(run_dir, result["manifest"], verify_video=False)


def test_review_run_rejects_tampered_cached_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "first")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "passed",
                "confidence": 0.99,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png")],
                "assertions": [{"id": "visible", "verdict": "supported", "frames": ["frames/frame.png"], "observation": "Visible."}],
                "incidental_findings": [],
                "return_stage": "complete",
                "next_action": "Publish.",
            },
            "ses_reviewer",
        )

    workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)
    (run_dir / "review-receipt.json").write_text("{}\n", encoding="utf-8")
    second_dir, _ = _write_review_run(tmp_path / "proof-videos" / "second")

    with pytest.raises(workflow.WorkflowError, match="receipt hash changed"):
        workflow.review_run(run_dir=second_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("subject_commit", "c" * 40),
        ("proof_contract_hash", "sha256:" + "d" * 64),
        ("frame_index_hash", "sha256:" + "e" * 64),
    ],
)
def test_review_run_rejects_mismatched_cached_request_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: str,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "first")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "passed",
                "confidence": 0.99,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
                "frame_reviews": [frame_quality_review("frames/frame.png")],
                "assertions": [{"id": "visible", "verdict": "supported", "frames": ["frames/frame.png"], "observation": "Visible."}],
                "incidental_findings": [],
                "return_stage": "complete",
                "next_action": "Publish.",
            },
            "ses_reviewer",
        )

    workflow.review_run(run_dir=run_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)
    cached_request_path = run_dir / "review-request.json"
    cached_request = json.loads(cached_request_path.read_text(encoding="utf-8"))
    cached_request[field] = replacement
    cached_request_path.write_text(json.dumps(cached_request), encoding="utf-8")
    second_dir, _ = _write_review_run(tmp_path / "proof-videos" / "second")

    with pytest.raises(workflow.WorkflowError, match="integrity validation|provenance"):
        workflow.review_run(run_dir=second_dir, correction_round=0, correction_kind="none", reviewer_runner=reviewer)


def test_default_reviewer_reuses_canonical_project_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    run_dir = repo_root / "test-results" / "proof-videos" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "frames").mkdir()
    prompt = run_dir / "review-prompt-round-0.json"
    prompt.write_text("{}\n", encoding="utf-8")
    observed: dict[str, object] = {}

    class Process:
        returncode = 0

        def __init__(self, command: list[str], **kwargs: object) -> None:
            observed.update({"command": command, **kwargs})
            kwargs["stdout"].write('{"type":"text","part":{"text":"{}"}}\n')

        def wait(self, timeout: float) -> int:
            return self.returncode

    def popen(command: list[str], **kwargs: object):
        return Process(command, **kwargs)

    monkeypatch.setattr(workflow.subprocess, "Popen", popen)
    monkeypatch.setattr(workflow, "_resolve_opencode_bin", lambda: "/test/opencode")
    monkeypatch.setattr(workflow, "REPO_ROOT", repo_root)
    monkeypatch.setattr(workflow, "CONTROL_PLANE_ROOT", repo_root)
    monkeypatch.chdir(repo_root)
    relative_run_dir = Path("test-results") / "proof-videos" / "run"
    workflow._default_reviewer_runner(
        relative_run_dir / "review-prompt-round-0.json",
        run_dir=relative_run_dir,
        correction_round=0,
    )

    assert observed["cwd"] == run_dir
    assert observed["command"][0] == "/test/opencode"
    assert "--dir" in observed["command"]
    assert observed["command"][observed["command"].index("--attach") + 1] == workflow.REVIEWER_ATTACH_URL
    assert observed["command"][observed["command"].index("--dir") + 1] == str(repo_root)
    attached_files = [
        observed["command"][index + 1]
        for index, value in enumerate(observed["command"])
        if value == "--file"
    ]
    assert attached_files == [str(prompt.resolve())]
    assert not (repo_root / "review-prompt-round-0.json").exists()
    assert not (repo_root / "frames").exists()


def test_default_reviewer_uses_checkout_containing_runtime_proof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    control_plane_root = tmp_path / "control-plane"
    runtime_root = tmp_path / "runtime"
    control_plane_root.mkdir()
    run_dir = runtime_root / "test-results" / "proof-videos" / "run"
    run_dir.mkdir(parents=True)
    frame_path = run_dir / "frames" / "frame-0000.png"
    frame_path.parent.mkdir()
    frame_path.write_bytes(b"frame")
    prompt = run_dir / "review-prompt-round-0.json"
    prompt.write_text(
        json.dumps({"review_request": {"frames": [{"path": "frames/frame-0000.png"}]}}),
        encoding="utf-8",
    )
    observed: dict[str, object] = {}

    class Process:
        returncode = 0

        def __init__(self, command: list[str], **kwargs: object) -> None:
            observed["command"] = command
            kwargs["stdout"].write('{"type":"text","part":{"text":"{}"}}\n')

        def wait(self, timeout: float) -> int:
            return self.returncode

    monkeypatch.setattr(workflow.subprocess, "Popen", lambda command, **kwargs: Process(command, **kwargs))
    monkeypatch.setattr(workflow, "_resolve_opencode_bin", lambda: "/test/opencode")
    monkeypatch.setattr(workflow, "CONTROL_PLANE_ROOT", control_plane_root)
    monkeypatch.setattr(workflow, "REPO_ROOT", runtime_root)

    workflow._default_reviewer_runner(prompt, run_dir=run_dir, correction_round=0)

    command = observed["command"]
    assert isinstance(command, list)
    assert command[command.index("--dir") + 1] == str(runtime_root)
    attached_files = [command[index + 1] for index, value in enumerate(command) if value == "--file"]
    assert attached_files == [str(prompt), str(frame_path)]
    prompt_payload = json.loads(prompt.read_text(encoding="utf-8"))
    assert prompt_payload["review_request"]["frames"][0]["read_path"] == (
        "test-results/proof-videos/run/frames/frame-0000.png"
    )


def test_default_reviewer_requires_resolvable_opencode_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = tmp_path / "review-prompt-round-0.json"
    prompt.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(workflow, "_resolve_opencode_bin", lambda: None)

    with pytest.raises(workflow.WorkflowError, match="OPENCODE_BIN"):
        workflow._default_reviewer_runner(prompt, run_dir=tmp_path, correction_round=0)


def test_default_reviewer_reports_progress_and_terminates_at_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    run_dir = repo_root / "test-results" / "proof-videos" / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "frames").mkdir()
    prompt = run_dir / "review-prompt-round-0.json"
    prompt.write_text("{}\n", encoding="utf-8")

    class Process:
        terminated = False

        def wait(self, timeout: float) -> int:
            if self.terminated:
                return -15
            raise workflow.subprocess.TimeoutExpired("opencode", timeout)

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.terminated = True

    process = Process()
    monotonic_values = iter([0.0, 0.0, 31.0, 601.0])
    monkeypatch.setattr(workflow.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(workflow.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(workflow, "_resolve_opencode_bin", lambda: "/test/opencode")
    monkeypatch.setattr(workflow, "REPO_ROOT", repo_root)
    with pytest.raises(workflow.WorkflowError, match="timed out after 600s"):
        workflow._default_reviewer_runner(
            prompt,
            run_dir=run_dir,
            correction_round=0,
        )

    output = capsys.readouterr().out
    assert "still running (31s elapsed)" in output
    assert process.terminated is True
    assert not (repo_root / "review-prompt-round-0.json").exists()
    assert not (repo_root / "frames").exists()


def test_review_run_rejects_reviewer_frame_hash_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    run_dir, _request = _write_review_run(tmp_path / "proof-videos" / "run")
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return ({"status": "passed", "frame_index_hash": "sha256:" + "0" * 64}, "ses_reviewer")

    with pytest.raises(workflow.WorkflowError, match="did not preserve"):
        workflow.review_run(
            run_dir=run_dir,
            correction_round=0,
            correction_kind="none",
            reviewer_runner=reviewer,
        )


def test_review_run_rejects_frame_path_escape_before_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "RESULTS_DIR", tmp_path)
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "run")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    request["frames"][0].update({"path": "../outside.png", "sha256": workflow._file_sha256(outside)})
    from scripts import spec_demo

    request["frame_index_hash"] = spec_demo.frame_index_hash(request["frames"])
    (run_dir / "review-request.json").write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")
    invoked = False

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        nonlocal invoked
        invoked = True
        return ({}, "ses_reviewer")

    with pytest.raises(workflow.WorkflowError, match="escapes"):
        workflow.review_run(
            run_dir=run_dir,
            correction_round=0,
            correction_kind="none",
            reviewer_runner=reviewer,
        )
    assert invoked is False
