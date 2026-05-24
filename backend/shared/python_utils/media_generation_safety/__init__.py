# backend/shared/python_utils/media_generation_safety/__init__.py
#
# Shared prompt-level safety checks for generated media skills.
# Image, video, and music generation all import this package before invoking
# paid providers so scam, spam, and impersonation requests are blocked early.
# The image-specific visual classifier pipeline remains separate.

from .pipeline import (
    MediaGenerationDecision,
    MediaGenerationSafetyRejection,
    validate_media_generation_request,
)

__all__ = [
    "MediaGenerationDecision",
    "MediaGenerationSafetyRejection",
    "validate_media_generation_request",
]
