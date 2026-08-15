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
    run_dir, request = _write_review_run(tmp_path / "proof-videos" / "first")
    monkeypatch.setattr(workflow, "REVIEW_BUDGETS_DIR", tmp_path / "budgets")

    def reviewer(_prompt: Path, **_kwargs: object) -> tuple[dict[str, object], str]:
        return (
            {
                "status": "passed",
                "confidence": 0.99,
                "frame_index_hash": request["frame_index_hash"],
                "reviewed_frames": ["frames/frame.png"],
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
                "assertions": [{"id": "visible", "verdict": "not_visible", "frames": ["frames/frame.png"], "observation": "Blank frame."}],
                "incidental_findings": [],
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
    assert blocker_media["video_path"] == str(run_dir / "demo.mp4")
    assert blocker_media["upload_command"].startswith("python3 scripts/opencode_response_media.py ")
    assert result["receipt"]["workflow"]["blocker_media"] == blocker_media


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


def test_default_reviewer_is_scoped_to_run_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "frames").mkdir()
    prompt = run_dir / "review-prompt-round-0.json"
    prompt.write_text("{}\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def run(command: list[str], **kwargs: object):
        observed.update({"command": command, **kwargs})
        return type("Result", (), {"returncode": 0, "stdout": '{"type":"text","part":{"text":"{}"}}\n', "stderr": ""})()

    monkeypatch.setattr(workflow.subprocess, "run", run)
    monkeypatch.setattr(workflow, "_resolve_opencode_bin", lambda: "/test/opencode")
    monkeypatch.setattr(workflow, "REPO_ROOT", repo_root)
    workflow._default_reviewer_runner(prompt, run_dir=run_dir, correction_round=0)

    assert observed["cwd"] == repo_root
    assert observed["command"][0] == "/test/opencode"
    assert "--dir" in observed["command"]
    assert str(repo_root) in observed["command"]
    assert str(prompt.resolve()) not in " ".join(observed["command"])
    assert "review-prompt-round-0.json" in " ".join(observed["command"])
    assert not (repo_root / "review-prompt-round-0.json").exists()
    assert not (repo_root / "frames").exists()


def test_default_reviewer_requires_resolvable_opencode_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prompt = tmp_path / "review-prompt-round-0.json"
    prompt.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(workflow, "_resolve_opencode_bin", lambda: None)

    with pytest.raises(workflow.WorkflowError, match="OPENCODE_BIN"):
        workflow._default_reviewer_runner(prompt, run_dir=tmp_path, correction_round=0)


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
