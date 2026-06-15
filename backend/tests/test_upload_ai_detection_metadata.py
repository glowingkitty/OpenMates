# backend/tests/test_upload_ai_detection_metadata.py
# Contract tests for upload AI-detection metadata emitted by Sightengine helpers.
# The frontend authenticity badge relies on failed detections being explicit,
# not silently encoded as a 0.0 AI-generated score.
# This keeps temporary provider failures distinct from authentic images.

from backend.upload.services.sightengine_service import AIDetectionResult


def test_ai_detection_result_serialises_success_status() -> None:
    result = AIDetectionResult(ai_generated=0.98, provider="sightengine")

    assert result.to_dict() == {
        "ai_generated": 0.98,
        "provider": "sightengine",
        "status": "success",
        "error": None,
    }


def test_ai_detection_result_serialises_failed_status() -> None:
    result = AIDetectionResult(ai_generated=0.0, provider="sightengine", error="timeout")

    assert result.to_dict() == {
        "ai_generated": 0.0,
        "provider": "sightengine",
        "status": "failed",
        "error": "timeout",
    }
