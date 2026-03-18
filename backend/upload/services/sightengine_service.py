# backend/upload/services/sightengine_service.py
#
# SightEngine image scanning service for the uploads microservice.
#
# Performs a SINGLE API call per upload using combined models:
#   models=nudity-2.0,offensive,gore,genai
#
# This single call covers:
#
# 1. Content safety scan ('nudity-2.0,offensive,gore') — BLOCKING
#    - Checks for nudity, sexual content, violence, gore, offensive imagery
#    - Rejects the upload if any threshold is exceeded (HTTP 422)
#    - This is the canonical content safety implementation (ImageSafetyService in the core API was dead code and has been removed)
#    - Applied to ALL image uploads (chat images AND profile images)
#    - API docs: https://sightengine.com/docs/nudity-detection
#
# 2. AI-generated content detection ('genai' model) — NON-BLOCKING
#    - Determines probability that an image was AI-generated
#    - Result stored as metadata in the embed TOON content
#    - Never rejects an upload regardless of result
#    - API docs: https://sightengine.com/docs/ai-generated-image-detection
#
# Previously these were two sequential HTTP calls. Combining into one request
# eliminates a full round-trip to the SightEngine API, saving ~500–1500ms per
# upload. The SightEngine /check.json endpoint natively supports multiple models
# in a single request, returning all scores in one response.
#
# Both checks use the same SightEngine credentials loaded from the LOCAL
# Vault KV at startup (kv/data/providers/sightengine → api_user, api_secret).
# If credentials are unavailable, BOTH checks are skipped (uploads allowed).
#
# We post raw image bytes directly to avoid exposing S3 URLs before
# encryption/storage. Credentials never come from env vars.

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SIGHTENGINE_API_URL = "https://api.sightengine.com/1.0/check.json"


# ---------------------------------------------------------------------------
# Content safety check result
# ---------------------------------------------------------------------------

class ContentSafetyResult:
    """
    Result of the SightEngine content safety scan (nudity/violence/gore).

    is_safe=True  → image passed all thresholds, upload may proceed.
    is_safe=False → image failed one or more thresholds, upload must be rejected.
    reason        → human-readable explanation of the rejection (or None if safe).
    error         → set if the API call itself failed (non-blocking in this case).
    """

    def __init__(
        self,
        is_safe: bool,
        reason: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        self.is_safe = is_safe
        self.reason = reason
        self.error = error

    def __repr__(self) -> str:
        return (
            f"ContentSafetyResult(is_safe={self.is_safe}, "
            f"reason={self.reason!r}, error={self.error!r})"
        )


# ---------------------------------------------------------------------------
# AI detection result
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# SightEngine service
# ---------------------------------------------------------------------------

class SightEngineService:
    """
    Async wrapper for the SightEngine image analysis API.

    Primary method (use this for all image uploads):
      - check_all(): Single API call with models=nudity-2.0,offensive,gore,genai.
        Returns (ContentSafetyResult, Optional[AIDetectionResult]) in one round-trip.
        Saves ~500–1500ms vs the previous two-call approach.

    Legacy methods (kept for reference, no longer called by upload_route.py):
      - check_content_safety(): BLOCKING content moderation only.
      - check_image(): NON-BLOCKING AI detection only.

    Credentials are loaded from the local Vault KV at startup via
    initialize_from_vault(). If credentials are not available, both
    checks are skipped and uploads are allowed through.
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

        If credentials are not found or Vault is unavailable, both content
        safety scanning and AI detection are disabled — uploads still succeed.

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
                    "content safety scanning and AI detection will be skipped"
                )
                return

            # Fetch credentials from local Vault KV
            url = f"{vault_url}/v1/kv/data/providers/sightengine"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers={"X-Vault-Token": token})

            if resp.status_code == 404:
                logger.warning(
                    "[SightEngine] No sightengine credentials in local Vault — "
                    "content safety scanning and AI detection will be skipped. "
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
                logger.info(
                    "[SightEngine] Service enabled: content safety + AI detection "
                    "(credentials from local Vault)"
                )
            else:
                logger.warning(
                    "[SightEngine] api_user or api_secret missing in Vault KV — "
                    "content safety scanning and AI detection will be skipped"
                )

        except FileNotFoundError:
            logger.warning(
                "[SightEngine] Vault token file not found — "
                "content safety scanning and AI detection will be skipped"
            )
        except Exception as e:
            logger.warning(
                f"[SightEngine] Failed to load credentials from local Vault: {e} — "
                f"content safety scanning and AI detection will be skipped"
            )

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def check_all(
        self, image_bytes: bytes, filename: str = "upload.jpg"
    ) -> tuple["ContentSafetyResult", "Optional[AIDetectionResult]"]:
        """
        Run content safety + AI detection in a SINGLE SightEngine API call.

        Uses models=nudity-2.0,offensive,gore,genai — the response contains all
        scores for both checks. This replaces the previous two-call approach and
        saves one full HTTP round-trip to the SightEngine API per upload.

        Returns a tuple of (ContentSafetyResult, Optional[AIDetectionResult]).

        Safety check is BLOCKING: caller must reject the upload if is_safe=False.
        AI detection is NON-BLOCKING: result is metadata only, never rejects.

        If the service is disabled, returns (safe=True, None).
        If the API call fails, fails-open on safety (upload allowed) and returns
        None for AI detection — both failures are logged as warnings.
        """
        if not self._enabled:
            logger.debug("[SightEngine] Skipping all checks (service not configured)")
            return ContentSafetyResult(is_safe=True), None

        log_prefix = f"[SightEngine] [{filename[:30]}]"
        logger.info(
            f"{log_prefix} Running combined check "
            f"(models: nudity-2.0,offensive,gore,genai, {len(image_bytes)} bytes)"
        )

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    SIGHTENGINE_API_URL,
                    data={
                        "models": "nudity-2.0,offensive,gore,genai",
                        "api_user": self.api_user,
                        "api_secret": self.api_secret,
                    },
                    files={
                        "media": (filename, image_bytes, "application/octet-stream"),
                    },
                )

            if resp.status_code != 200:
                logger.error(
                    f"{log_prefix} Combined check API returned HTTP {resp.status_code}: "
                    f"{resp.text[:200]} — failing CLOSED (upload rejected, service down)"
                )
                return ContentSafetyResult(
                    is_safe=False,
                    reason="safety_service_unavailable",
                    error=f"API error {resp.status_code}",
                ), None

            data = resp.json()

            if data.get("status") != "success":
                error_msg = data.get("error", {}).get("message", "Unknown error")
                logger.error(
                    f"{log_prefix} Combined check API returned non-success: "
                    f"{error_msg} — failing CLOSED (upload rejected, service error)"
                )
                return ContentSafetyResult(
                    is_safe=False,
                    reason="safety_service_unavailable",
                    error=error_msg,
                ), None

            # --- Extract content safety scores ---
            nudity = data.get("nudity", {})
            offensive = data.get("offensive", {})
            gore = data.get("gore", {})

            sexual_activity = float(nudity.get("sexual_activity", 0.0))
            sexual_display = float(nudity.get("sexual_display", 0.0))
            erotica = float(nudity.get("erotica", 0.0))
            sextoy = float(nudity.get("sextoy", 0.0))
            suggestive = float(nudity.get("suggestive", 0.0))
            weapon = float(offensive.get("weapon", 0.0))
            gore_score = float(gore.get("gore", 0.0))
            blood = float(gore.get("blood", 0.0))

            logger.info(
                f"{log_prefix} Content safety scores — "
                f"sexual_activity={sexual_activity:.3f} sexual_display={sexual_display:.3f} "
                f"erotica={erotica:.3f} sextoy={sextoy:.3f} suggestive={suggestive:.3f} "
                f"weapon={weapon:.3f} gore={gore_score:.3f} blood={blood:.3f}"
            )

            # --- Apply safety thresholds ---
            safety_reason: Optional[str] = None
            if sexual_activity > 0.3:
                safety_reason = f"sexual_activity={sexual_activity:.2f}"
            elif sexual_display > 0.3:
                safety_reason = f"sexual_display={sexual_display:.2f}"
            elif erotica > 0.4:
                safety_reason = f"erotica={erotica:.2f}"
            elif sextoy > 0.3:
                safety_reason = f"sextoy={sextoy:.2f}"
            elif suggestive > 0.6:
                safety_reason = f"suggestive={suggestive:.2f}"
            elif weapon > 0.5:
                safety_reason = f"weapon={weapon:.2f}"
            elif gore_score > 0.3:
                safety_reason = f"gore={gore_score:.2f}"
            elif blood > 0.4:
                safety_reason = f"blood={blood:.2f}"

            if safety_reason:
                logger.warning(f"{log_prefix} Content safety REJECTED — {safety_reason}")
                safety_result = ContentSafetyResult(is_safe=False, reason=safety_reason)
                # Still parse AI detection even on rejection (caller may log it)
            else:
                logger.info(f"{log_prefix} Content safety: PASSED ✓")
                safety_result = ContentSafetyResult(is_safe=True)

            # --- Extract AI detection score ---
            ai_generated = float(data.get("type", {}).get("ai_generated", 0.0))
            label = (
                "LIKELY AI-GENERATED" if ai_generated > 0.7
                else ("possibly AI" if ai_generated > 0.4 else "likely real/photo")
            )
            logger.info(
                f"{log_prefix} AI detection: score={ai_generated:.3f} → {label}"
            )
            ai_result = AIDetectionResult(ai_generated=ai_generated)

            return safety_result, ai_result

        except httpx.TimeoutException as e:
            logger.error(
                f"{log_prefix} Combined check request timed out: {e} — "
                f"failing CLOSED (upload rejected, service timeout)"
            )
            return ContentSafetyResult(
                is_safe=False,
                reason="safety_service_unavailable",
                error="timeout",
            ), None
        except Exception as e:
            logger.error(
                f"{log_prefix} Combined check failed: {e} — "
                f"failing CLOSED (upload rejected, service error)",
                exc_info=True,
            )
            return ContentSafetyResult(
                is_safe=False,
                reason="safety_service_unavailable",
                error=str(e),
            ), None

    async def check_content_safety(
        self, image_bytes: bytes, filename: str = "upload.jpg"
    ) -> ContentSafetyResult:
        """
        Check an image for nudity, sexual content, violence, and gore.

        Uses SightEngine models: nudity-2.0, offensive, gore.
        This is the canonical content safety threshold implementation.

        BLOCKING: if is_safe=False on the result, the upload MUST be rejected.

        If the service is disabled (no credentials) the check is SKIPPED and
        is_safe=True is returned so uploads continue — do not block uploads
        just because SightEngine credentials are missing.

        If the API call itself fails, we err on the side of ALLOWING the upload
        (fail-open) to avoid blocking legitimate uploads when the external API
        has an outage. This is logged as a warning.

        Args:
            image_bytes: Raw image file bytes (plaintext, before encryption).
            filename: Original filename (used for multipart form Content-Disposition).

        Returns:
            ContentSafetyResult with is_safe flag and optional rejection reason.
        """
        if not self._enabled:
            logger.debug("[SightEngine] Skipping content safety check (service not configured)")
            return ContentSafetyResult(is_safe=True)

        log_prefix = f"[SightEngine] [{filename[:30]}]"
        logger.info(
            f"{log_prefix} Running content safety check "
            f"(models: nudity-2.0,offensive,gore, {len(image_bytes)} bytes)"
        )

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    SIGHTENGINE_API_URL,
                    data={
                        "models": "nudity-2.0,offensive,gore",
                        "api_user": self.api_user,
                        "api_secret": self.api_secret,
                    },
                    files={
                        "media": (filename, image_bytes, "application/octet-stream"),
                    },
                )

            if resp.status_code != 200:
                logger.warning(
                    f"{log_prefix} Content safety API returned HTTP {resp.status_code}: "
                    f"{resp.text[:200]} — failing open (upload allowed)"
                )
                return ContentSafetyResult(
                    is_safe=True,
                    error=f"API error {resp.status_code}",
                )

            data = resp.json()

            if data.get("status") != "success":
                error_msg = data.get("error", {}).get("message", "Unknown error")
                logger.warning(
                    f"{log_prefix} Content safety API returned non-success: "
                    f"{error_msg} — failing open (upload allowed)"
                )
                return ContentSafetyResult(is_safe=True, error=error_msg)

            # --- Extract scores ---
            nudity = data.get("nudity", {})
            offensive = data.get("offensive", {})
            gore = data.get("gore", {})

            # Content safety thresholds (canonical — previously also defined in the now-removed ImageSafetyService):
            sexual_activity = float(nudity.get("sexual_activity", 0.0))
            sexual_display = float(nudity.get("sexual_display", 0.0))
            erotica = float(nudity.get("erotica", 0.0))
            sextoy = float(nudity.get("sextoy", 0.0))
            suggestive = float(nudity.get("suggestive", 0.0))
            weapon = float(offensive.get("weapon", 0.0))
            gore_score = float(gore.get("gore", 0.0))
            blood = float(gore.get("blood", 0.0))

            logger.info(
                f"{log_prefix} Content safety scores — "
                f"sexual_activity={sexual_activity:.3f} sexual_display={sexual_display:.3f} "
                f"erotica={erotica:.3f} sextoy={sextoy:.3f} suggestive={suggestive:.3f} "
                f"weapon={weapon:.3f} gore={gore_score:.3f} blood={blood:.3f}"
            )

            # --- Apply thresholds ---
            reason: Optional[str] = None

            if sexual_activity > 0.3:
                reason = f"sexual_activity={sexual_activity:.2f}"
            elif sexual_display > 0.3:
                reason = f"sexual_display={sexual_display:.2f}"
            elif erotica > 0.4:
                reason = f"erotica={erotica:.2f}"
            elif sextoy > 0.3:
                reason = f"sextoy={sextoy:.2f}"
            elif suggestive > 0.6:
                reason = f"suggestive={suggestive:.2f}"
            elif weapon > 0.5:
                reason = f"weapon={weapon:.2f}"
            elif gore_score > 0.3:
                reason = f"gore={gore_score:.2f}"
            elif blood > 0.4:
                reason = f"blood={blood:.2f}"

            if reason:
                logger.warning(
                    f"{log_prefix} Content safety REJECTED — {reason}"
                )
                return ContentSafetyResult(is_safe=False, reason=reason)

            logger.info(f"{log_prefix} Content safety: PASSED ✓")
            return ContentSafetyResult(is_safe=True)

        except httpx.TimeoutException as e:
            logger.warning(
                f"{log_prefix} Content safety request timed out: {e} — "
                f"failing open (upload allowed)"
            )
            return ContentSafetyResult(is_safe=True, error="timeout")
        except Exception as e:
            # Fail-open: do not block legitimate uploads because of an API outage
            logger.error(
                f"{log_prefix} Content safety check failed: {e} — "
                f"failing open (upload allowed)",
                exc_info=True,
            )
            return ContentSafetyResult(is_safe=True, error=str(e))

    async def check_image(
        self, image_bytes: bytes, filename: str = "upload.jpg"
    ) -> Optional[AIDetectionResult]:
        """
        Check whether an image was AI-generated using SightEngine's 'genai' model.

        NON-BLOCKING: never rejects an upload regardless of result.
        Returns None if the service is disabled or the API call fails non-fatally.

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
                    f"{log_prefix} AI detection API returned HTTP {resp.status_code}: {resp.text[:200]}"
                )
                return AIDetectionResult(
                    ai_generated=0.0,
                    error=f"API error {resp.status_code}",
                )

            data = resp.json()

            if data.get("status") != "success":
                error_msg = data.get("error", {}).get("message", "Unknown error")
                logger.warning(f"{log_prefix} AI detection API returned non-success: {error_msg}")
                return AIDetectionResult(ai_generated=0.0, error=error_msg)

            ai_generated = float(data.get("type", {}).get("ai_generated", 0.0))
            result = AIDetectionResult(ai_generated=ai_generated)

            logger.info(
                f"{log_prefix} AI detection complete: ai_generated={ai_generated:.3f}"
            )
            return result

        except httpx.TimeoutException as e:
            logger.warning(f"{log_prefix} AI detection request timed out: {e}")
            return AIDetectionResult(ai_generated=0.0, error="timeout")
        except Exception as e:
            # Never block an upload because of a detection failure
            logger.error(f"{log_prefix} AI detection check failed: {e}", exc_info=True)
            return AIDetectionResult(ai_generated=0.0, error=str(e))
