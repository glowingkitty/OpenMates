# backend/upload/services/sightengine_service.py
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
#
# Credentials are loaded from the LOCAL Vault KV at startup (not env vars).
# The local Vault is populated by vault-setup from SECRET__SIGHTENGINE__*
# env vars. This service never contacts the main Vault.

import logging
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

    Credentials are loaded from the local Vault KV at startup via
    initialize_from_vault(). If credentials are not available,
    detection is automatically skipped for all uploads.
    """

    def __init__(self) -> None:
        self.api_user: str = ""
        self.api_secret: str = ""
        self._enabled: bool = False

    async def initialize_from_vault(
        self,
        vault_url: str = "http://vault:8200",
        vault_token_path: str = "/vault-data/api.token",
    ) -> None:
        """
        Load SightEngine credentials from the local Vault KV.

        Reads from kv/data/providers/sightengine:
          - api_user
          - api_secret

        If credentials are not found or Vault is unavailable, the service
        is disabled (detection skipped) — uploads still succeed.

        Args:
            vault_url: URL of the local Vault instance.
            vault_token_path: Path to the Vault API token file.
        """
        try:
            # Load token from shared volume
            with open(vault_token_path, "r") as f:
                token = f.read().strip()
            if not token:
                logger.warning(
                    "[SightEngine] Vault token file is empty — "
                    "AI detection will be skipped"
                )
                return

            # Fetch credentials from local Vault KV
            url = f"{vault_url}/v1/kv/data/providers/sightengine"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers={"X-Vault-Token": token})

            if resp.status_code == 404:
                logger.warning(
                    "[SightEngine] No sightengine credentials in local Vault — "
                    "AI detection will be skipped. "
                    "Set SECRET__SIGHTENGINE__API_USER and SECRET__SIGHTENGINE__API_SECRET "
                    "in .env to enable."
                )
                return

            resp.raise_for_status()
            data = resp.json().get("data", {}).get("data", {})

            self.api_user = data.get("api_user", "")
            self.api_secret = data.get("api_secret", "")
            self._enabled = bool(self.api_user and self.api_secret)

            if self._enabled:
                logger.info("[SightEngine] AI detection service enabled (credentials from local Vault)")
            else:
                logger.warning(
                    "[SightEngine] api_user or api_secret missing in Vault KV — "
                    "AI detection will be skipped"
                )

        except FileNotFoundError:
            logger.warning(
                "[SightEngine] Vault token file not found — "
                "AI detection will be skipped"
            )
        except Exception as e:
            logger.warning(
                f"[SightEngine] Failed to load credentials from local Vault: {e} — "
                f"AI detection will be skipped"
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
