"""Tests for frame-only implementation demonstration review.

Purpose: keep full videos out of model context while preserving targeted review.
Architecture: build bounded frame indexes and structured claim verdict records.
Privacy: fixtures contain synthetic frame paths and no media or user data.
Tests: python3 -m pytest scripts/tests/test_spec_demonstration_review.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "spec_demo.py"
VIDEO_HASH = "sha256:" + "a" * 64
FRAME_HASH = "sha256:" + "b" * 64


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
    assert {1.2, 2.0, 4.5, 5.0, 8.0}.issubset(times)


def test_periodic_interval_can_only_be_shorter_than_three_seconds() -> None:
    module = load_module()

    assert module.build_review_frame_times(duration_seconds=4, interval_seconds=1)[-1] == 4.0
    with pytest.raises(module.DemonstrationError, match="three seconds"):
        module.build_review_frame_times(duration_seconds=4, interval_seconds=4)


def test_review_request_contains_frames_and_captions_but_no_video() -> None:
    module = load_module()
    request = module.build_review_request(
        spec_id="example",
        subject_commit="abc1234",
        captions=[{"id": "CAP-1", "narration_id": "NARR-1", "text": "The result is visible.", "start": 1.0, "end": 2.0, "claim_ids": ["CLAIM-1"]}],
        expected_proof=[{"claim_id": "CLAIM-1", "text": "The result is visible.", "acceptance_criteria": ["AC-1"], "evidence_intervals": [[1.0, 2.0]]}],
        frames=[{"timestamp": 1.0, "path": "frames/frame-001.png", "sha256": FRAME_HASH}],
        video_metadata={"duration_seconds": 3.0, "sha256": VIDEO_HASH, "width": 320, "height": 240},
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
                "observation": "Synthetic mismatch.",
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


def test_record_review_requires_exactly_one_verdict_for_every_expected_claim(tmp_path: Path) -> None:
    module = load_module()
    manifest = {
        "expected_proof": [{"claim_id": "CLAIM-1"}, {"claim_id": "CLAIM-2"}],
        "review": {"status": "pending", "attempts": [], "additional_frame_requests": []},
    }
    (tmp_path / "manifest.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")

    with pytest.raises(module.DemonstrationError, match="exactly one verdict"):
        module.record_review(
            tmp_path,
            [{"claim_id": "CLAIM-BOGUS", "verdict": "supported", "observation": "Not relevant."}],
        )


def test_fourth_unresolved_review_requires_user_input() -> None:
    module = load_module()
    result = module.evaluate_review_claims(
        [
            {
                "claim_id": "CLAIM-1",
                "verdict": "ambiguous",
                "defect_class": "recording",
                "observation": "The relevant state is not readable.",
            }
        ],
        prior_attempts=3,
    )

    assert result["attempt_number"] == 4
    assert result["requires_user_input"] is True
