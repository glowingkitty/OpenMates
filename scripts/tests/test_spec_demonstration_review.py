"""Tests for frame-only implementation demonstration review.

Purpose: keep full videos out of model context while preserving targeted review.
Architecture: build bounded frame indexes and structured claim verdict records.
Privacy: fixtures contain synthetic frame paths and no media or user data.
Tests: python3 -m pytest scripts/tests/test_spec_demonstration_review.py.
"""

# contract-test-file: tooling

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "spec_demo.py"
VIDEO_HASH = "sha256:" + "a" * 64
FRAME_HASH = "sha256:" + "b" * 64
AUDIO_HASH = "sha256:" + "c" * 64


def narration_audio() -> dict[str, object]:
    return {
        "status": "passed",
        "provider": "elevenlabs",
        "model": "eleven_flash_v2_5",
        "voice": "warm_neutral",
        "path": "narration-audio.mp3",
        "sha256": AUDIO_HASH,
        "mime_type": "audio/mpeg",
        "duration_seconds": 3.0,
        "reused_from": "",
    }


def runner_provenance(request: dict[str, object]) -> dict[str, object]:
    metadata = request["video_metadata"]
    assert isinstance(metadata, dict)
    return {
        "reviewer_session_id": "ses_reviewer",
        "device": metadata.get("device_profile", "unspecified-device"),
        "proof_contract_hash": request["proof_contract_hash"],
        "proof_group_id": request["proof_group_id"],
        "source_artifact_hash": metadata["sha256"],
        "review_request_hash": "sha256:" + hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "subject_commit": request["subject_commit"],
        "correction_round": 0,
        "correction_kind": "none",
        "workflow": {"requires_user_input": False},
    }


def frame_quality_review(frame: str, result: str = "pass", **overrides: str) -> dict[str, object]:
    checks = {
            "layout": result,
            "readability": result,
            "geometry": result,
            "controls": result,
            "visual_assets": result,
            "application_state": result,
            "consistency": result,
            "proof_alignment": result,
    }
    checks.update(overrides)
    return {
        "frame": frame,
        "checks": checks,
        "observation": "Completed the independent critical UI scan.",
    }


def load_module():
    spec = importlib.util.spec_from_file_location("spec_demo", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_review_frame_times_combine_periodic_and_event_boundaries() -> None:
    module = load_module()

    times = module.build_review_frame_times(
        duration_seconds=10,
        interval_seconds=3,
        scene_times=[1.2],
        action_times=[4.5],
        caption_intervals=[(2.0, 5.0)],
        state_change_times=[8.0],
    )

    assert {0.0, 3.0, 6.0, 9.0, 10.0}.issubset(times)
    assert {2.0, 4.5, 7.75}.issubset(times)
    assert len(times) <= module.MAX_REVIEW_FRAMES_PER_DEVICE


def test_periodic_interval_can_only_be_shorter_than_five_seconds() -> None:
    module = load_module()

    assert module.build_review_frame_times(duration_seconds=4, interval_seconds=1)[-1] == 4.0
    assert module.END_FRAME_OFFSET_SECONDS == 0.5
    with pytest.raises(module.DemonstrationError, match="five seconds"):
        module.build_review_frame_times(duration_seconds=6, interval_seconds=6)


def test_review_request_contains_frames_and_captions_but_no_video() -> None:
    module = load_module()
    request = module.build_review_request(
        spec_id="example",
        subject_commit="abc1234",
        captions=[{"id": "CAP-1", "narration_id": "NARR-1", "text": "The result is visible.", "start": 1.0, "end": 2.0, "claim_ids": ["CLAIM-1"]}],
        expected_proof=[{"claim_id": "CLAIM-1", "text": "The result is visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[1.0, 2.0]]}],
        frames=[{"timestamp": 1.0, "path": "frames/frame-001.png", "sha256": FRAME_HASH}],
        video_metadata={"duration_seconds": 3.0, "sha256": VIDEO_HASH, "width": 320, "height": 240},
        narration_audio=narration_audio(),
    )

    assert request["frames"][0]["path"].endswith(".png")
    assert "video_path" not in request
    assert "video_bytes" not in request
    module.assert_frame_only_review_request(request)


@pytest.mark.parametrize(
    ("forbidden_key", "value"),
    [("video_path", "demo.mp4"), ("video_bytes", b"video"), ("video_base64", "AAAA")],
)
def test_review_request_rejects_full_video_inputs(forbidden_key: str, value: object) -> None:
    module = load_module()

    with pytest.raises(module.DemonstrationError, match="full video"):
        module.assert_frame_only_review_request({forbidden_key: value, "frames": []})


def test_review_request_rejects_unknown_payload_fields() -> None:
    module = load_module()
    request = module.build_review_request(
        spec_id="example",
        subject_commit="abc1234",
        captions=[{"id": "CAP-1", "narration_id": "NARR-1", "text": "Visible.", "start": 0.0, "end": 1.0, "claim_ids": ["CLAIM-1"]}],
        expected_proof=[{"claim_id": "CLAIM-1", "text": "Visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[0.0, 1.0]]}],
        frames=[{"timestamp_seconds": 0.0, "path": "frames/frame.png", "sha256": FRAME_HASH}],
        video_metadata={"duration_seconds": 1.0, "sha256": VIDEO_HASH, "width": 320, "height": 240},
        narration_audio=narration_audio(),
    )
    request["recording_attachment"] = "demo.mp4"

    with pytest.raises(module.DemonstrationError, match="unsupported field"):
        module.assert_frame_only_review_request(request)


def test_review_request_rejects_missing_required_allowlisted_fields() -> None:
    module = load_module()

    with pytest.raises(module.DemonstrationError, match="missing required field"):
        module.assert_frame_only_review_request({"frames": [], "video_metadata": {}})


def test_review_request_rejects_ambiguous_frame_timestamps() -> None:
    module = load_module()
    request = module.build_review_request(
        spec_id="example",
        subject_commit="abc1234",
        captions=[{"id": "CAP-1", "narration_id": "NARR-1", "text": "Visible.", "start": 0.0, "end": 1.0, "claim_ids": ["CLAIM-1"]}],
        expected_proof=[{"claim_id": "CLAIM-1", "text": "Visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[0.0, 1.0]]}],
        frames=[{"timestamp_seconds": 0.0, "path": "frames/frame.png", "sha256": FRAME_HASH}],
        video_metadata={"duration_seconds": 1.0, "sha256": VIDEO_HASH, "width": 320, "height": 240},
        narration_audio=narration_audio(),
    )
    request["frames"][0]["timestamp"] = "invalid"

    with pytest.raises(module.DemonstrationError, match="frame is missing required fields"):
        module.assert_frame_only_review_request(request)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("captions", "text", None),
        ("expected_proof", "acceptance_criteria", "AC-1"),
        ("expected_proof", "evidence_intervals", ["invalid"]),
        ("frames", "timestamp_seconds", "now"),
        ("video_metadata", "duration_seconds", -1),
        ("video_metadata", "duration_seconds", float("nan")),
        ("video_metadata", "sha256", "sha256:short"),
    ],
)
def test_review_request_rejects_malformed_allowlisted_values(section: str, field: str, value: object) -> None:
    module = load_module()
    request = module.build_review_request(
        spec_id="example",
        subject_commit="abc1234",
        captions=[{"id": "CAP-1", "narration_id": "NARR-1", "text": "Visible.", "start": 0.0, "end": 1.0, "claim_ids": ["CLAIM-1"]}],
        expected_proof=[{"claim_id": "CLAIM-1", "text": "Visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[0.0, 1.0]]}],
        frames=[{"timestamp_seconds": 0.0, "path": "frames/frame.png", "sha256": FRAME_HASH}],
        video_metadata={"duration_seconds": 1.0, "sha256": VIDEO_HASH, "width": 320, "height": 240},
        narration_audio=narration_audio(),
    )
    target = request[section][0] if isinstance(request[section], list) else request[section]
    target[field] = value

    with pytest.raises(module.DemonstrationError, match="Review request"):
        module.assert_frame_only_review_request(request)


def test_exact_timestamp_frame_requests_are_bounded_and_recorded() -> None:
    module = load_module()
    review = {"additional_frame_requests": []}

    for index in range(module.MAX_ADDITIONAL_FRAME_REQUESTS):
        module.register_exact_timestamp_request(review, timestamp_seconds=index + 0.25, reason="Clarify claim")

    assert len(review["additional_frame_requests"]) == module.MAX_ADDITIONAL_FRAME_REQUESTS
    assert review["additional_frame_requests"][0]["timestamp_seconds"] == 0.25
    with pytest.raises(module.DemonstrationError, match="limit"):
        module.register_exact_timestamp_request(review, timestamp_seconds=99, reason="Too many")


@pytest.mark.parametrize(
    ("defect_class", "return_stage", "invalidates"),
    [
        ("implementation", "implementation", True),
        ("test_coverage", "tests", True),
        ("recording", "capture", False),
        ("narration", "captions", False),
        ("composition", "render", False),
        ("environment", "environment", False),
    ],
)
def test_failed_claims_map_to_one_responsible_stage(
    defect_class: str,
    return_stage: str,
    invalidates: bool,
) -> None:
    module = load_module()
    result = module.evaluate_review_claims(
        [
            {
                "claim_id": "CLAIM-1",
                "verdict": "contradicted",
                "defect_class": defect_class,
                "observation": "Synthetic mismatch is visible in frame 0001.",
            }
        ],
        prior_attempts=0,
    )

    assert result["status"] == "failed"
    assert result["return_stages"] == [return_stage]
    assert result["invalidate_implementation_evidence"] is invalidates
    assert result["attempt_number"] == 1


def test_supported_claims_pass_without_return_stage() -> None:
    module = load_module()
    result = module.evaluate_review_claims(
        [{"claim_id": "CLAIM-1", "verdict": "supported", "observation": "Visible in frame 2."}],
        prior_attempts=0,
    )

    assert result["status"] == "passed"
    assert result["return_stages"] == []
    assert result["invalidate_implementation_evidence"] is False


def test_supported_claims_require_frame_grounded_observation() -> None:
    module = load_module()

    with pytest.raises(module.DemonstrationError, match="reviewed frames"):
        module.evaluate_review_claims(
            [{"claim_id": "CLAIM-1", "verdict": "supported", "observation": "Looks good."}],
            prior_attempts=0,
        )


def test_uncertain_review_requires_user_input_immediately() -> None:
    module = load_module()
    result = module.evaluate_review_claims(
        [
            {
                "claim_id": "CLAIM-1",
                "verdict": "ambiguous",
                "defect_class": "recording",
                "observation": "The relevant state is not readable in frame 0003.",
            }
        ],
        prior_attempts=0,
    )

    assert result["attempt_number"] == 1
    assert result["requires_user_input"] is True


def test_third_failed_review_requires_user_input() -> None:
    module = load_module()
    result = module.evaluate_review_claims(
        [
            {
                "claim_id": "CLAIM-1",
                "verdict": "contradicted",
                "defect_class": "composition",
                "observation": "The defect remains visible in frame 0003.",
            }
        ],
        prior_attempts=2,
    )

    assert result["attempt_number"] == 3
    assert result["requires_user_input"] is True


def test_review_receipt_rejects_uncited_frames_and_blocking_incidental_pass(tmp_path: Path) -> None:
    module = load_module()
    frame_path = tmp_path / "frames" / "frame.png"
    frame_path.parent.mkdir()
    frame_path.write_bytes(b"frame")
    request = module.build_review_request(
        spec_id="example",
        subject_commit="abc1234",
        captions=[{"id": "CAP-1", "narration_id": "NARR-1", "text": "Visible.", "start": 0.0, "end": 1.0, "claim_ids": ["visible"]}],
        expected_proof=[{"claim_id": "visible", "text": "Visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[0.0, 1.0]]}],
        frames=[{"timestamp_seconds": 0.0, "path": "frames/frame.png", "sha256": module.sha256_file(frame_path)}],
        video_metadata={"duration_seconds": 1.0, "sha256": VIDEO_HASH, "width": 320, "height": 240},
        narration_audio=narration_audio(),
    )
    (tmp_path / "review-request.json").write_text(__import__("json").dumps(request), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        __import__("json").dumps({"expected_proof": request["expected_proof"], "review": {"status": "pending", "attempts": []}}),
        encoding="utf-8",
    )
    receipt = {
        **runner_provenance(request),
        "status": "passed",
        "confidence": 0.98,
        "frame_index_hash": request["frame_index_hash"],
        "reviewed_frames": ["frames/frame.png"],
        "frame_reviews": [frame_quality_review("frames/frame.png")],
        "assertions": [{"id": "visible", "verdict": "supported", "frames": ["frames/missing.png"], "observation": "Visible."}],
        "incidental_findings": [],
        "return_stage": "complete",
        "next_action": "Publish.",
    }

    missing_integrity_scan = dict(receipt)
    missing_integrity_scan.pop("incidental_findings")
    with pytest.raises(module.DemonstrationError, match="incidental_findings"):
        module.record_review_receipt(tmp_path, missing_integrity_scan)

    with pytest.raises(module.DemonstrationError, match="unknown frame"):
        module.record_review_receipt(tmp_path, receipt)

    receipt["assertions"][0]["frames"] = ["frames/frame.png"]
    missing_frame_reviews = dict(receipt)
    missing_frame_reviews.pop("frame_reviews")
    with pytest.raises(module.DemonstrationError, match="frame_reviews"):
        module.record_review_receipt(tmp_path, missing_frame_reviews)

    receipt["frame_reviews"] = [frame_quality_review("frames/frame.png", geometry="fail")]
    receipt["incidental_findings"] = [
        {
            "id": "UI-1",
            "category": "clipping",
            "severity": "blocking",
            "confidence": 0.98,
            "intent": "obvious",
            "quality_categories": ["geometry", "readability"],
            "frames": ["frames/frame.png"],
            "observation": "The header is clipped.",
        }
    ]
    with pytest.raises(module.DemonstrationError, match="matching non-passing"):
        module.record_review_receipt(tmp_path, receipt)

    receipt["incidental_findings"][0]["quality_categories"] = ["geometry"]
    with pytest.raises(module.DemonstrationError, match="unresolved incidental"):
        module.record_review_receipt(tmp_path, receipt)


def test_review_receipt_requires_every_frame_and_exact_assertion_schema(tmp_path: Path) -> None:
    module = load_module()
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    first = frames_dir / "first.png"
    second = frames_dir / "second.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    request = module.build_review_request(
        spec_id="example",
        subject_commit="abc1234",
        captions=[{"id": "CAP-1", "narration_id": "NARR-1", "text": "Visible.", "start": 0.0, "end": 1.0, "claim_ids": ["visible"]}],
        expected_proof=[{"claim_id": "visible", "text": "Visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[0.0, 1.0]]}],
        frames=[
            {"timestamp_seconds": 0.0, "path": "frames/first.png", "sha256": module.sha256_file(first)},
            {"timestamp_seconds": 1.0, "path": "frames/second.png", "sha256": module.sha256_file(second)},
        ],
        video_metadata={"duration_seconds": 1.0, "sha256": VIDEO_HASH, "width": 320, "height": 240},
        narration_audio=narration_audio(),
    )
    (tmp_path / "review-request.json").write_text(__import__("json").dumps(request), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        __import__("json").dumps({"expected_proof": request["expected_proof"], "review": {"status": "pending", "attempts": []}}),
        encoding="utf-8",
    )
    receipt = {
        **runner_provenance(request),
        "status": "passed",
        "confidence": 0.99,
        "frame_index_hash": request["frame_index_hash"],
        "reviewed_frames": ["frames/first.png"],
        "frame_reviews": [frame_quality_review("frames/first.png"), frame_quality_review("frames/second.png")],
        "assertions": [{"id": "visible", "verdict": "supported", "frames": ["frames/first.png"], "observation": "Visible."}],
        "incidental_findings": [],
        "return_stage": "complete",
        "next_action": "Publish.",
    }

    with pytest.raises(module.DemonstrationError, match="every canonical frame"):
        module.record_review_receipt(tmp_path, receipt)

    receipt["reviewed_frames"] = ["frames/first.png", "frames/second.png"]
    receipt["assertions"][0]["unexpected"] = True
    with pytest.raises(module.DemonstrationError, match="canonical schema"):
        module.record_review_receipt(tmp_path, receipt)


def test_passed_review_rejects_uncertain_frame_quality(tmp_path: Path) -> None:
    module = load_module()
    frame_path = tmp_path / "frames" / "frame.png"
    frame_path.parent.mkdir()
    frame_path.write_bytes(b"frame")
    request = module.build_review_request(
        spec_id="example",
        subject_commit="abc1234",
        captions=[{"id": "CAP-1", "narration_id": "NARR-1", "text": "Visible.", "start": 0.0, "end": 1.0, "claim_ids": ["visible"]}],
        expected_proof=[{"claim_id": "visible", "text": "Visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[0.0, 1.0]]}],
        frames=[{"timestamp_seconds": 0.0, "path": "frames/frame.png", "sha256": module.sha256_file(frame_path)}],
        video_metadata={"duration_seconds": 1.0, "sha256": VIDEO_HASH, "width": 320, "height": 240},
        narration_audio=narration_audio(),
    )
    (tmp_path / "review-request.json").write_text(__import__("json").dumps(request), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        __import__("json").dumps({"expected_proof": request["expected_proof"], "review": {"status": "pending", "attempts": []}}),
        encoding="utf-8",
    )
    receipt = {
        **runner_provenance(request),
        "status": "passed",
        "confidence": 0.8,
        "frame_index_hash": request["frame_index_hash"],
        "reviewed_frames": ["frames/frame.png"],
        "frame_reviews": [frame_quality_review("frames/frame.png", "uncertain")],
        "assertions": [{"id": "visible", "verdict": "supported", "frames": ["frames/frame.png"], "observation": "Visible."}],
        "incidental_findings": [],
        "return_stage": "complete",
        "next_action": "Publish.",
    }

    with pytest.raises(module.DemonstrationError, match="quality scan"):
        module.record_review_receipt(tmp_path, receipt)


def test_visual_intent_approval_requires_matching_prior_uncertain_receipt(tmp_path: Path) -> None:
    module = load_module()
    frame_path = tmp_path / "frames" / "frame.png"
    frame_path.parent.mkdir()
    frame_path.write_bytes(b"frame")
    request = module.build_review_request(
        spec_id="example",
        subject_commit="abc1234",
        captions=[{"id": "CAP-1", "narration_id": "NARR-1", "text": "Visible.", "start": 0.0, "end": 1.0, "claim_ids": ["visible"]}],
        expected_proof=[{"claim_id": "visible", "text": "Visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[0.0, 1.0]]}],
        frames=[{"timestamp_seconds": 0.0, "path": "frames/frame.png", "sha256": module.sha256_file(frame_path)}],
        video_metadata={"duration_seconds": 1.0, "sha256": VIDEO_HASH, "width": 320, "height": 240},
        narration_audio=narration_audio(),
    )
    (tmp_path / "review-request.json").write_text(__import__("json").dumps(request), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        __import__("json").dumps({"expected_proof": request["expected_proof"], "review": {"status": "pending", "attempts": []}}),
        encoding="utf-8",
    )
    uncertain = {
        **runner_provenance(request),
        "status": "uncertain",
        "confidence": 0.9,
        "frame_index_hash": request["frame_index_hash"],
        "reviewed_frames": ["frames/frame.png"],
        "frame_reviews": [frame_quality_review("frames/frame.png", geometry="uncertain")],
        "assertions": [{"id": "visible", "verdict": "supported", "frames": ["frames/frame.png"], "observation": "Visible."}],
        "incidental_findings": [
            {
                "id": "UI-1",
                "category": "geometry",
                "severity": "warning",
                "confidence": 0.9,
                "intent": "unclear",
                "quality_categories": ["geometry"],
                "frames": ["frames/frame.png"],
                "observation": "The partial item may be intentional.",
            }
        ],
        "return_stage": "review",
        "next_action": "Ask the user.",
    }
    module.record_review_receipt(tmp_path, uncertain)
    approved = {
        **uncertain,
        "status": "passed",
        "frame_reviews": [frame_quality_review("frames/frame.png")],
        "incidental_findings": [],
        "return_stage": "complete",
        "next_action": "Publish.",
        "approved_visual_intents": [
            {
                "finding_id": "UI-1",
                "approved_by": "user",
                "approved_at": "2026-08-25T23:43:00Z",
                "reason": "Intentional carousel affordance.",
                "frames": ["frames/frame.png"],
                "quality_categories": ["geometry"],
                "original_receipt_sha256": "sha256:" + "f" * 64,
            }
        ],
    }

    with pytest.raises(module.DemonstrationError, match="prior uncertain review receipt"):
        module.record_review_receipt(tmp_path, approved)
