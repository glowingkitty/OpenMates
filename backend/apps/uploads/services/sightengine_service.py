# backend/apps/uploads/services/sightengine_service.py
#
# SightEngine AI-generated image detection service.
#
# API documentation: https://sightengine.com/docs/ai-generated-image-detection
#
# Response format from the 'genai' model:
#   {
#     "status": "success",
#     "request": {"id": "...", "timestamp": 1234567890, "operations": 1},
#     "type": {
#       "ai_generated": 0.01   ← float 0.0-1.0 (higher = more likely AI-generated)
#     },
#     "media": {"id": "...", "uri": "..."}
#   }
#
# We post raw image bytes (Option 2 in the docs) to avoid exposing an S3 URL
# before the file is encrypted and stored.
#
# The AI detection result is stored as metadata in the embed TOON content.
# It is shown to the user as a badge on the image embed card. Upload always
# succeeds regardless of the detection result.

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SIGHTENGINE_API_URL = "https://api.sightengine.com/1.0/check.json"


class AIDetectionResult:
    """Result of SightEngine AI-generated content detection."""

    def __init__(
        self,
        ai_generated: float,
        provider: str = "sightengine",
        error: Optional[str] = None,
    ) -> None:
        # Probability 0.0–1.0 that the image is AI-generated.
        # None if the check was skipped or failed.
        self.ai_generated = ai_generated
        self.provider = provider
        self.error = error  # Non-None if the API call failed (non-blocking)

    def to_dict(self) -> dict:
        """Serialise for embedding in embed content TOON."""
        return {
            "ai_generated": self.ai_generated,
            "provider": self.provider,
        }

    def __repr__(self) -> str:
        return f"AIDetectionResult(ai_generated={self.ai_generated:.2f}, provider={self.provider})"


class SightEngineService:
    """
    Async wrapper for the SightEngine AI-generated image detection API.

    Credentials are loaded from environment variables at startup:
      SIGHTENGINE_API_USER   — API user ID
      SIGHTENGINE_API_SECRET — API secret key

    The service is optional: if credentials are not configured, detection is
    skipped and the embed will have no ai_detection metadata.
    """

    def __init__(self) -> None:
        self.api_user = os.environ.get("SIGHTENGINE_API_USER", "")
        self.api_secret = os.environ.get("SIGHTENGINE_API_SECRET", "")
        self._enabled = bool(self.api_user and self.api_secret)

        if self._enabled:
            logger.info("[SightEngine] AI detection service enabled")
        else:
            logger.warning(
                "[SightEngine] SIGHTENGINE_API_USER/SIGHTENGINE_API_SECRET not set — "
                "AI detection will be skipped for uploaded images"
            )

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def check_image(self, image_bytes: bytes, filename: str = "upload.jpg") -> Optional[AIDetectionResult]:
        """
        Check whether an image was AI-generated using SightEngine's 'genai' model.

        Sends the raw image bytes to the API (no URL exposure).
        Returns None if the service is disabled or the API call fails non-fatally.
        Never raises — upload must succeed even if detection fails.

        Args:
            image_bytes: Raw image file bytes (plaintext, before encryption).
            filename: Original filename (used for multipart form Content-Disposition).

        Returns:
            AIDetectionResult with ai_generated probability, or None if unavailable.
        """
        if not self._enabled:
            logger.debug("[SightEngine] Skipping AI detection (service not configured)")
            return None

        log_prefix = f"[SightEngine] [{filename[:30]}]"
        logger.info(f"{log_prefix} Checking AI-generated probability ({len(image_bytes)} bytes)")

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    SIGHTENGINE_API_URL,
                    data={
                        "models": "genai",
                        "api_user": self.api_user,
                        "api_secret": self.api_secret,
                    },
                    files={
                        "media": (filename, image_bytes, "application/octet-stream"),
                    },
                )

            if resp.status_code != 200:
                logger.warning(
                    f"{log_prefix} API returned HTTP {resp.status_code}: {resp.text[:200]}"
                )
                return AIDetectionResult(
                    ai_generated=0.0,
                    error=f"API error {resp.status_code}",
                )

            data = resp.json()

            if data.get("status") != "success":
                error_msg = data.get("error", {}).get("message", "Unknown error")
                logger.warning(f"{log_prefix} API returned non-success: {error_msg}")
                return AIDetectionResult(ai_generated=0.0, error=error_msg)

            ai_generated = float(data.get("type", {}).get("ai_generated", 0.0))
            result = AIDetectionResult(ai_generated=ai_generated)

            logger.info(
                f"{log_prefix} AI detection complete: ai_generated={ai_generated:.3f}"
            )
            return result

        except httpx.TimeoutException as e:
            logger.warning(f"{log_prefix} SightEngine request timed out: {e}")
            return AIDetectionResult(ai_generated=0.0, error="timeout")
        except Exception as e:
            # Never block an upload because of a detection failure
            logger.error(f"{log_prefix} SightEngine check failed: {e}", exc_info=True)
            return AIDetectionResult(ai_generated=0.0, error=str(e))
