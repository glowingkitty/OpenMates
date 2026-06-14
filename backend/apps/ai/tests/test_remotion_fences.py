# backend/apps/ai/tests/test_remotion_fences.py
#
# Regression tests for the AI stream parser's Remotion fence classifier. These
# tests ensure deterministic video code only becomes a videos.create embed when
# the assistant uses the explicit remotion: fence requested by the product spec.

from backend.apps.ai.utils.remotion_fences import (
    REMOTION_FENCE_LANGUAGE,
    _is_remotion_video_fence,
    _parse_remotion_fence_metadata,
)


def test_explicit_remotion_fence_metadata_is_detected() -> None:
    metadata = _parse_remotion_fence_metadata("remotion:ProductAnnouncement.tsx")

    assert metadata == {"language": REMOTION_FENCE_LANGUAGE, "filename": "ProductAnnouncement.tsx"}
    assert _is_remotion_video_fence("remotion", "ProductAnnouncement.tsx") is True


def test_generic_tsx_is_not_remotion_video_create() -> None:
    assert _parse_remotion_fence_metadata("tsx:Button.tsx") is None
    assert _is_remotion_video_fence("tsx", "Button.tsx") is False
    assert _is_remotion_video_fence("typescript", "composition.tsx") is False
