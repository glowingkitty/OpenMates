#!/usr/bin/env python3
"""Test the focused, bounded proof-video workflow orchestrator.

The tests cover only deterministic context, contract, trim, pacing, cache, and
review-routing behavior. They deliberately avoid network calls, OCR, full-video
analysis, and semantic UI judgment. Synthetic session and test records ensure
the workflow never needs real credentials or user data.
"""

# contract-test-file: tooling

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts import proof_video_workflow as workflow


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
        "title": "Maps Search fullscreen",
        "transcript": [
            "Maps Search opens in the regular fullscreen shell.",
            "The place list and map stay inside the same parent fullscreen.",
        ],
        "assertions": [
            {"id": "header-visible", "description": "The regular embed header is visible."},
            {"id": "no-nested-fullscreen", "description": "No nested fullscreen appears."},
        ],
        "devices": ["web-phone", "web-laptop"],
    }

    first = workflow.write_contract(tmp_path / "contract.json", contract)
    second = workflow.write_contract(tmp_path / "contract-copy.json", dict(reversed(list(contract.items()))))

    assert first["contract_hash"] == second["contract_hash"]
    workflow.require_approved_contract(first, first["contract_hash"])
    with pytest.raises(workflow.WorkflowError, match="approved contract hash"):
        workflow.require_approved_contract(first, "sha256:stale")


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


def test_recorded_contract_approval_is_bound_to_session_spec_path_and_content(
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
    workflow.record_contract_approval(session_id="abcd", spec_name="example.spec.ts", contract_path=contract_path)

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


def test_pacing_rejects_transcript_that_cannot_fit_output_cap() -> None:
    with pytest.raises(workflow.WorkflowError, match="35 second output limit"):
        workflow.calculate_pacing(source_duration_seconds=4, transcript_words=200)


def test_resource_limits_and_cache_key_are_stable() -> None:
    limits = workflow.resource_limits()

    assert limits == {
        "parallel_device_renders": 1,
        "maximum_output_seconds": 35,
        "maximum_analysis_frames": 12,
        "maximum_review_frames_per_device": 8,
        "maximum_automatic_rerenders": 1,
        "ocr_enabled": False,
    }
    assert workflow.cache_key("sha256:source", "sha256:contract", renderer_version="1") == workflow.cache_key(
        "sha256:source", "sha256:contract", renderer_version="1"
    )


def test_review_bundle_is_frame_only_and_bounded(tmp_path: Path) -> None:
    frames = []
    for index in range(8):
        frame = tmp_path / f"frame-{index}.png"
        frame.write_bytes(b"image")
        frames.append({"path": str(frame), "timestamp_seconds": float(index)})

    bundle = workflow.build_review_bundle(
        contract={"contract_hash": "sha256:contract", "assertions": [{"id": "visible", "description": "Visible."}]},
        deterministic_metadata={"subject_commit": "abc1234"},
        frames_by_device={"web-phone": frames},
    )

    assert len(bundle["frames_by_device"]["web-phone"]) == 8
    assert "video" not in json.dumps(bundle).lower()
    with pytest.raises(workflow.WorkflowError, match="three to eight"):
        workflow.build_review_bundle(
            contract={"contract_hash": "sha256:contract", "assertions": [{"id": "visible", "description": "Visible."}]},
            deterministic_metadata={},
            frames_by_device={"web-phone": frames + [frames[0]]},
        )


@pytest.mark.parametrize(
    ("defect", "expected_stage", "automatic"),
    [
        ("blank_first_frame", "render", True),
        ("caption_alignment", "render", True),
        ("unexplained_scroll_state", "capture", False),
        ("clipped_header", "implementation", False),
    ],
)
def test_defect_routing_never_hides_product_defects(defect: str, expected_stage: str, automatic: bool) -> None:
    result = workflow.route_defect(defect, prior_automatic_rerenders=0)

    assert result["return_stage"] == expected_stage
    assert result["automatic_correction"] is automatic

    if expected_stage == "implementation":
        assert result["next_action"] == "return_to_failing_test"


def test_mechanical_rerender_limit_is_one() -> None:
    result = workflow.route_defect("blank_first_frame", prior_automatic_rerenders=1)

    assert result["automatic_correction"] is False
    assert result["verdict"] == "uncertain"
