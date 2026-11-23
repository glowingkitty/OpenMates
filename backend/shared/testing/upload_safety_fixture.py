"""Isolated CI-only second opinion for uploaded images.

The isolated CI stack has no image-safety provider credentials (no Sightengine,
no decision model). Since uploads are refused as "safety_service_unavailable"
when both are missing, every synthetic test image (call camera frames, chat
images) was refused there. In isolated CI only, the second opinion answers
"clearly harmless" for the synthetic test images, so the real upload policy
still runs and allows them.

Unreachable without all four isolated CI environment guards; it never runs on
dev or production. Image bytes are neither inspected, logged nor stored.
"""

from __future__ import annotations

from backend.shared.testing.voice_call_fixture import isolated_voice_fixture_enabled


def isolated_image_second_opinion() -> dict[str, float] | None:
    """Benign probabilities in isolated CI, otherwise None (the real check runs)."""
    if not isolated_voice_fixture_enabled():
        return None
    return {"nudity": 0.0, "minor": 0.0, "gore": 0.0}
