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
from dataclasses import replace
from typing import Optional

import httpx

from backend.upload.services.upload_safety_policy import (
    NUDITY_SIGNAL_AT,
    SecondOpinion,
    UploadSafetyScores,
    resolve_upload_safety,
)

logger = logging.getLogger(__name__)

SIGHTENGINE_API_URL = "https://api.sightengine.com/1.0/check.json"
# One request: nudity, gore and AI-generated detection.
SIGHTENGINE_UPLOAD_MODELS = "nudity-2.0,gore,genai"
# Second call, only when nudity signals are present: per-face minor probability.
SIGHTENGINE_FACE_MODELS = "face-attributes"


def create_http_client(_category: str, **httpx_kwargs) -> httpx.AsyncClient:
    """Return a plain HTTP client; upload server stays isolated from backend.shared."""
    return httpx.AsyncClient(**httpx_kwargs)


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
        counts_as_strike: bool = False,
    ) -> None:
        self.is_safe = is_safe
        self.reason = reason
        self.error = error
        # True only for a refusal the policy marks as a strike (minors + sexual).
        self.counts_as_strike = counts_as_strike

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
            "status": "failed" if self.error else "success",
            "error": self.error,
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

    async def _fetch_scores(
        self,
        image_bytes: bytes,
        filename: str,
        content_type: str,
    ) -> tuple[Optional[UploadSafetyScores], Optional[AIDetectionResult]]:
        """
        One Sightengine call (nudity-2.0, face-attributes, gore, genai).

        Returns (None, None) when the service is not configured or the call
        fails; the caller then falls back to the strict second opinion.
        """
        if not self._enabled:
            logger.info("[SightEngine] Not configured; safety falls back to the second opinion")
            return None, None

        log_prefix = f"[SightEngine] [{filename[:30]}]"
        try:
            async with create_http_client("sightengine", timeout=20) as client:
                resp = await client.post(
                    SIGHTENGINE_API_URL,
                    data={
                        "models": SIGHTENGINE_UPLOAD_MODELS,
                        "api_user": self.api_user,
                        "api_secret": self.api_secret,
                    },
                    files={"media": (filename, image_bytes, content_type)},
                )
            data = resp.json() if resp.status_code == 200 else {}
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(f"{log_prefix} Sightengine call failed ({type(exc).__name__}); using fallback")
            return None, None

        if resp.status_code != 200 or data.get("status") != "success":
            logger.warning(
                f"{log_prefix} Sightengine returned HTTP {resp.status_code} "
                f"status={data.get('status')!r}; using fallback"
            )
            return None, None

        nudity = data.get("nudity", {}) or {}
        gore = data.get("gore", {}) or {}
        weapon = data.get("weapon", {}) or {}
        weapon_classes = weapon.get("classes", {}) or {}
        scores = UploadSafetyScores(
            sexual_activity=float(nudity.get("sexual_activity", 0.0)),
            sexual_display=float(nudity.get("sexual_display", 0.0)),
            erotica=float(nudity.get("erotica", 0.0)),
            sextoy=float(nudity.get("sextoy", 0.0)),
            suggestive=float(nudity.get("suggestive", 0.0)),
            gore=float(gore.get("prob", gore.get("gore", 0.0))),
            weapon=max([0.0, *(float(v) for v in weapon_classes.values())]),
        )
        if scores.sexual_max >= NUDITY_SIGNAL_AT:
            minor = await self._fetch_minor_score(image_bytes, filename, content_type)
            if minor is None:
                return None, None
            scores = replace(scores, minor=minor)
        logger.info(f"{log_prefix} Safety scores: {scores}")
        ai_generated = float((data.get("type", {}) or {}).get("ai_generated", 0.0))
        return scores, AIDetectionResult(ai_generated=ai_generated)

    async def _fetch_minor_score(
        self, image_bytes: bytes, filename: str, content_type: str
    ) -> Optional[float]:
        """Highest per-face minor probability (face-attributes), None when the call fails."""
        try:
            async with create_http_client("sightengine", timeout=20) as client:
                resp = await client.post(
                    SIGHTENGINE_API_URL,
                    data={
                        "models": SIGHTENGINE_FACE_MODELS,
                        "api_user": self.api_user,
                        "api_secret": self.api_secret,
                    },
                    files={"media": (filename, image_bytes, content_type)},
                )
            data = resp.json() if resp.status_code == 200 else {}
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(f"[SightEngine] Face attributes failed ({type(exc).__name__}); using fallback")
            return None
        if data.get("status") != "success":
            logger.warning(f"[SightEngine] Face attributes HTTP {resp.status_code}; using fallback")
            return None
        minor = 0.0
        for face in data.get("faces", []) or []:
            if isinstance(face, dict):
                attrs = face.get("attributes", {}) or {}
                minor = max(minor, float(attrs.get("minor", 0.0) or face.get("minor", 0.0) or 0.0))
        return minor

    async def check_all(
        self,
        image_bytes: bytes,
        filename: str = "upload.jpg",
        content_type: str = "application/octet-stream",
        second_opinion: Optional[SecondOpinion] = None,
    ) -> tuple["ContentSafetyResult", "Optional[AIDetectionResult]"]:
        """
        Content safety (BLOCKING) + AI detection (non-blocking) from ONE call.

        The decision comes from upload_safety_policy: Sightengine scores first,
        the Jev second opinion for borderline scores or when Sightengine is
        unavailable (strict). When neither can judge, the result is a refusal
        with reason "safety_service_unavailable" (never a strike).
        """
        scores, ai_result = await self._fetch_scores(image_bytes, filename, content_type)
        decision = await resolve_upload_safety(scores, second_opinion)
        logger.info(
            f"[SightEngine] Upload safety decision={decision.kind} category={decision.category} "
            f"borderline={decision.borderline} reason={decision.reason}"
        )
        if decision.kind == "allow":
            return ContentSafetyResult(is_safe=True), ai_result
        return (
            ContentSafetyResult(
                is_safe=False,
                reason=decision.reason,
                counts_as_strike=decision.kind == "refuse_strike",
            ),
            ai_result,
        )

    async def check_content_safety(
        self,
        image_bytes: bytes,
        filename: str = "upload.jpg",
        content_type: str = "application/octet-stream",
        second_opinion: Optional[SecondOpinion] = None,
    ) -> ContentSafetyResult:
        """Content safety verdict only (same policy and single call as check_all)."""
        result, _ = await self.check_all(image_bytes, filename, content_type, second_opinion)
        return result

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
            async with create_http_client("sightengine", timeout=15) as client:
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
