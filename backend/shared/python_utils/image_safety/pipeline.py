# backend/shared/python_utils/image_safety/pipeline.py
#
# Image safety pipeline orchestrator — Steps 0-5 from the architecture doc.
#
# Architecture: docs/architecture/image-safety-pipeline.md §2, §3
#
# Two entry points:
#   validate_input(...)  → runs Step 1 + Step 2 on a reference image before
#                          we pay the generation provider
#   validate_output(...) → runs Step 4 on the provider's result before we
#                          store it in S3
#
# Both return a PipelineDecision. On block, the caller:
#   1. Writes the audit log entry (via write_audit_entry)
#   2. Records the strike (via StrikeCounter.record_strike)
#   3. Marks the assistant_response_id as rejected (handled by the caller —
#      see generate_task.py integration)
#   4. Returns the structured tool response to the LLM

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.google.vision_safety import (
    VisionSafetyFindings,
    analyze_image_gemini,
)
from backend.shared.providers.openai.vision_safety_fallback import (
    analyze_image_gpt5_mini,
)
from backend.shared.providers.groq.safeguard import (
    get_safeguard_client,
)
from backend.shared.providers.sightengine.client import (
    SightengineFindings,
    get_sightengine_safety_client,
)

from .messages import build_rejection_payload, category_info
from .policy import get_policy_markdown

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class SafetyRejection:
    """A structured rejection returned by the pipeline."""

    category: str
    severity: str
    reason: str  # short machine-readable reason (for audit log)
    user_facing_message: str
    tool_response: Dict[str, Any]
    stage: str  # "input" | "output"
    sightengine_audit: Dict[str, Any] = field(default_factory=dict)
    vlm_audit: Dict[str, Any] = field(default_factory=dict)
    safeguard_audit: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineDecision:
    """Result of validate_input / validate_output."""

    allowed: bool
    rejection: Optional[SafetyRejection] = None
    # Kept for audit logging on the allow path
    sightengine_audit: Dict[str, Any] = field(default_factory=dict)
    vlm_audit: Dict[str, Any] = field(default_factory=dict)
    safeguard_audit: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class ImageSafetyPipeline:
    """
    Orchestrates the dual-classifier + reasoner safety pipeline.

    Stateless — one instance per process. The caller is responsible for
    passing the SecretsManager (used to load Sightengine / Gemini / OpenAI /
    Groq credentials lazily).
    """

    def __init__(self) -> None:
        self._initialized = False

    async def initialize(self, secrets_manager: SecretsManager) -> None:
        if self._initialized:
            return
        await get_sightengine_safety_client().initialize(secrets_manager)
        await get_safeguard_client().initialize(secrets_manager)
        # Preload the policy into memory so we don't do disk I/O per request
        get_policy_markdown()
        self._initialized = True

    # -----------------------------------------------------------------------
    # Input stage — called before provider generation
    # -----------------------------------------------------------------------

    async def validate_input(
        self,
        *,
        prompt: str,
        reference_images: List[Tuple[bytes, str]],  # [(bytes, mime_type), ...]
        secrets_manager: SecretsManager,
    ) -> PipelineDecision:
        """
        Run Step 1 (Sightengine + Gemini parallel) and Step 2 (safeguard).

        If there are no reference images, we only run the text-level safeguard
        check on the prompt alone. See pipeline doc §3 Step 0 / Step 2.
        """
        await self.initialize(secrets_manager)

        # Text-to-image path: skip image classifiers entirely, only run safeguard
        # on the prompt if it is non-empty. Step 1 only runs when we have images.
        if not reference_images:
            return await self._validate_text_to_image(
                prompt=prompt, secrets_manager=secrets_manager
            )

        # Image-to-image: analyze every reference image. We reject as soon as
        # any image trips a hard-block in Step 1 OR the safeguard returns block.
        for idx, (image_bytes, mime_type) in enumerate(reference_images):
            decision = await self._validate_single_image(
                prompt=prompt,
                image_bytes=image_bytes,
                mime_type=mime_type,
                stage="input",
                secrets_manager=secrets_manager,
                image_index=idx,
            )
            if not decision.allowed:
                return decision

        # All images passed — final allow decision
        return PipelineDecision(allowed=True)

    async def _validate_text_to_image(
        self,
        *,
        prompt: str,
        secrets_manager: SecretsManager,
    ) -> PipelineDecision:
        """
        Text-only intent classification. We still run the safeguard reasoner
        on the prompt against the policy so named public figures / named
        minors / explicit requests get caught before the provider is called.
        """
        safeguard = get_safeguard_client()
        if not safeguard.is_enabled:
            # No reasoner → we cannot do intent classification on text. Allow
            # the provider call and rely on Step 4 (output scan) to catch
            # anything that materializes. This matches the "degraded mode" in
            # the fallback chain §4.
            logger.warning(
                "[ImageSafety] Text-to-image fallback: safeguard unavailable, "
                "allowing provider call (output scan will still run)"
            )
            return PipelineDecision(allowed=True)

        verdict = await safeguard.reason(
            policy_markdown=get_policy_markdown(),
            stage="INPUT_VALIDATION_TEXT_ONLY",
            user_prompt=prompt,
            sightengine_json={},
            vlm_json={},
        )

        if verdict.decision == "allow":
            return PipelineDecision(
                allowed=True, safeguard_audit=verdict.to_audit_dict()
            )

        # block or escalate — treat escalate as block in P0
        info = category_info(verdict.category or "unknown")
        rejection = SafetyRejection(
            category=verdict.category or "unknown",
            severity=verdict.severity or info["severity"],
            reason=f"safeguard:{verdict.decision}",
            user_facing_message=info["message"],
            tool_response=build_rejection_payload(
                verdict.category or "unknown"
            ),
            stage="input",
            safeguard_audit=verdict.to_audit_dict(),
        )
        return PipelineDecision(allowed=False, rejection=rejection)

    async def _validate_single_image(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        mime_type: str,
        stage: str,  # "input" | "output"
        secrets_manager: SecretsManager,
        image_index: int = 0,
    ) -> PipelineDecision:
        """
        Core dual-classifier flow used for both input and output stages.

        Step 1: Sightengine + Gemini in parallel (VLM fallback chain on error)
        Step 2: If ambiguous, run gpt-oss-safeguard reasoner
        """
        sightengine = get_sightengine_safety_client()

        # --- Step 1: parallel classifier calls ---
        se_task = asyncio.create_task(
            sightengine.analyze(
                image_bytes, stage=stage, filename=f"image_{image_index}.webp"
            )
        )
        vlm_task = asyncio.create_task(
            self._run_vlm_with_fallback(
                image_bytes=image_bytes,
                mime_type=mime_type,
                secrets_manager=secrets_manager,
            )
        )
        se_findings, vlm_findings = await asyncio.gather(se_task, vlm_task)

        se_audit = se_findings.to_audit_dict()
        vlm_audit = vlm_findings.to_audit_dict()

        # Short-circuit if either classifier returned hard_block
        if se_findings.hard_block:
            category = se_findings.category_hint or "unknown"
            info = category_info(category)
            return PipelineDecision(
                allowed=False,
                sightengine_audit=se_audit,
                vlm_audit=vlm_audit,
                rejection=SafetyRejection(
                    category=category,
                    severity=info["severity"],
                    reason=f"sightengine:{se_findings.hard_block_reason}",
                    user_facing_message=info["message"],
                    tool_response=build_rejection_payload(category),
                    stage=stage,
                    sightengine_audit=se_audit,
                    vlm_audit=vlm_audit,
                ),
            )

        if vlm_findings.hard_block:
            category = vlm_findings.category_hint or "unknown"
            info = category_info(category)
            return PipelineDecision(
                allowed=False,
                sightengine_audit=se_audit,
                vlm_audit=vlm_audit,
                rejection=SafetyRejection(
                    category=category,
                    severity=info["severity"],
                    reason=f"vlm:{vlm_findings.hard_block_reason}",
                    user_facing_message=info["message"],
                    tool_response=build_rejection_payload(category),
                    stage=stage,
                    sightengine_audit=se_audit,
                    vlm_audit=vlm_audit,
                ),
            )

        # --- Step 2: safeguard reasoner when ambiguous ---
        if self._should_run_safeguard(se_findings, vlm_findings, stage=stage):
            safeguard = get_safeguard_client()
            if not safeguard.is_enabled:
                logger.warning(
                    "[ImageSafety] Safeguard unavailable at stage=%s — "
                    "fail-closed reject",
                    stage,
                )
                info = category_info("safeguard_not_configured")
                return PipelineDecision(
                    allowed=False,
                    sightengine_audit=se_audit,
                    vlm_audit=vlm_audit,
                    rejection=SafetyRejection(
                        category="safeguard_not_configured",
                        severity=info["severity"],
                        reason="safeguard_not_configured",
                        user_facing_message=info["message"],
                        tool_response=build_rejection_payload(
                            "safeguard_not_configured"
                        ),
                        stage=stage,
                        sightengine_audit=se_audit,
                        vlm_audit=vlm_audit,
                    ),
                )

            verdict = await safeguard.reason(
                policy_markdown=get_policy_markdown(),
                stage="INPUT_VALIDATION" if stage == "input" else "OUTPUT_VALIDATION",
                user_prompt=prompt,
                sightengine_json=se_audit,
                vlm_json=vlm_audit,
            )
            safeguard_audit = verdict.to_audit_dict()

            if verdict.decision != "allow":
                category = verdict.category or "unknown"
                info = category_info(category)
                return PipelineDecision(
                    allowed=False,
                    sightengine_audit=se_audit,
                    vlm_audit=vlm_audit,
                    safeguard_audit=safeguard_audit,
                    rejection=SafetyRejection(
                        category=category,
                        severity=verdict.severity or info["severity"],
                        reason=f"safeguard:{verdict.decision}",
                        user_facing_message=info["message"],
                        tool_response=build_rejection_payload(category),
                        stage=stage,
                        sightengine_audit=se_audit,
                        vlm_audit=vlm_audit,
                        safeguard_audit=safeguard_audit,
                    ),
                )

            return PipelineDecision(
                allowed=True,
                sightengine_audit=se_audit,
                vlm_audit=vlm_audit,
                safeguard_audit=safeguard_audit,
            )

        # No ambiguity → allow without safeguard call
        return PipelineDecision(
            allowed=True, sightengine_audit=se_audit, vlm_audit=vlm_audit
        )

    @staticmethod
    def _should_run_safeguard(
        se: SightengineFindings, vlm: VisionSafetyFindings, *, stage: str
    ) -> bool:
        """
        Trigger conditions for Step 2.

        Skip safeguard only when Step 1 was completely clean AND no people
        are present. Otherwise, ask the reasoner to tie-break / apply policy
        nuances (benign edit whitelist, minor-safe edits, etc.).
        """
        # Any soft signal triggers reasoning
        if se.face_count > 0 or se.minor_detected:
            return True
        if se.celebrity_match or se.deepfake_score > 0.3:
            return True
        if se.suggestive > 0.3 or se.weapon > 0.3:
            return True
        if vlm.people:
            return True
        if vlm.concerning_elements:
            return True
        if vlm.photorealistic and stage == "input":
            # Photorealistic reference images always get policy review
            return True
        return False

    async def _run_vlm_with_fallback(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        secrets_manager: SecretsManager,
    ) -> VisionSafetyFindings:
        """Primary: Gemini. Fallback: GPT-5 mini. Logs both on failure."""
        try:
            findings = await analyze_image_gemini(
                image_bytes=image_bytes,
                mime_type=mime_type,
                secrets_manager=secrets_manager,
            )
        except Exception as e:
            logger.error(f"[ImageSafety] Gemini VLM crashed: {e}", exc_info=True)
            findings = VisionSafetyFindings(
                provider="gemini",
                error=f"crash:{e}",
                hard_block=True,
                hard_block_reason="gemini_crash",
            )

        # Success condition: no error AND not a provider-infra hard_block
        is_infra_error = findings.error and findings.hard_block_reason in {
            "gemini_api_error",
            "gemini_parse_error",
            "gemini_not_configured",
            "gemini_crash",
        }
        if not is_infra_error:
            return findings

        logger.warning(
            "[ImageSafety] Gemini VLM unavailable (%s) — trying GPT-5 mini fallback",
            findings.hard_block_reason,
        )
        try:
            fb = await analyze_image_gpt5_mini(
                image_bytes=image_bytes,
                mime_type=mime_type,
                secrets_manager=secrets_manager,
            )
        except Exception as e:
            logger.error(
                f"[ImageSafety] GPT-5 mini fallback crashed: {e}", exc_info=True
            )
            fb = VisionSafetyFindings(
                provider="openai",
                error=f"crash:{e}",
                hard_block=True,
                hard_block_reason="gpt5_mini_crash",
            )
        return fb

    # -----------------------------------------------------------------------
    # Output stage — called after provider generation, before S3 write
    # -----------------------------------------------------------------------

    async def validate_output(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        mime_type: str,
        secrets_manager: SecretsManager,
    ) -> PipelineDecision:
        """Run Step 4 (output stage) on a single generated image."""
        await self.initialize(secrets_manager)
        return await self._validate_single_image(
            prompt=prompt,
            image_bytes=image_bytes,
            mime_type=mime_type,
            stage="output",
            secrets_manager=secrets_manager,
        )


_singleton: Optional[ImageSafetyPipeline] = None


def get_pipeline() -> ImageSafetyPipeline:
    """Return the process-wide pipeline singleton."""
    global _singleton
    if _singleton is None:
        _singleton = ImageSafetyPipeline()
    return _singleton
