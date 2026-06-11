# backend/tests/test_remotion_video_embed_parser.py
#
# Regression tests for Remotion video-create fence handling. These tests keep
# deterministic video code separate from generic TSX code embeds and prove the
# stream parser can build the videos.create placeholder contract without calling
# the real renderer.

from backend.apps.ai.utils.remotion_fences import (
    REMOTION_FENCE_LANGUAGE,
    _is_remotion_video_fence,
    _parse_remotion_fence_metadata,
)


def test_explicit_remotion_fence_metadata_is_detected() -> None:
    metadata = _parse_remotion_fence_metadata("remotion:ProductAnnouncement.tsx")

    assert metadata == {"language": REMOTION_FENCE_LANGUAGE, "filename": "ProductAnnouncement.tsx"}
    assert _is_remotion_video_fence("remotion", "ProductAnnouncement.tsx") is True


def test_generic_tsx_is_not_remotion() -> None:
    assert _parse_remotion_fence_metadata("tsx:Button.tsx") is None
    assert _is_remotion_video_fence("tsx", "Button.tsx") is False
    assert _is_remotion_video_fence("typescript", "composition.tsx") is False
