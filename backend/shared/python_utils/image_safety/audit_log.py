# backend/shared/python_utils/image_safety/audit_log.py
#
# Writes per-request audit log entries to the safety_audit_log Directus
# collection (see backend/core/directus/schemas/safety_audit_log.yml).
#
# Entries are encrypted at rest via Directus' standard storage but NOT
# client-encrypted — the audit log must be readable for compliance review
# (48h takedown responses under the TAKE IT DOWN Act, EU AI Act reviews, etc.)
#
# Architecture: docs/architecture/image-safety-pipeline.md §5 "Audit log structure"

import hashlib
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def hash_prompt(prompt: str) -> str:
    """Hash a prompt for storage — never store plaintext prompts in the audit log."""
    if not prompt:
        return ""
    return hashlib.sha256(prompt.encode("utf-8", errors="replace")).hexdigest()


async def write_audit_entry(
    *,
    directus_service,
    user_id: str,
    stage: str,  # "input" | "output"
    decision: str,  # "allow" | "block" | "escalate"
    category: str,
    severity: str,
    strike_weight: int,
    sightengine_json: Optional[Dict[str, Any]] = None,
    vlm_json: Optional[Dict[str, Any]] = None,
    safeguard_reasoning: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    source_embed_id: Optional[str] = None,
    output_embed_id: Optional[str] = None,
    prompt: Optional[str] = None,
    prompt_language: Optional[str] = None,
    assistant_response_id: Optional[str] = None,
) -> None:
    """
    Write an audit entry to the safety_audit_log collection.

    Best-effort: never raises. Failures are logged because audit logging must
    not block the safety pipeline itself.
    """
    entry = {
        "timestamp": int(time.time()),
        "user_id": user_id,
        "stage": stage,
        "decision": decision,
        "category": category,
        "severity": severity,
        "strike_weight": strike_weight,
        "sightengine_json": sightengine_json or {},
        "vlm_json": vlm_json or {},
        "safeguard_reasoning": (safeguard_reasoning or "")[:4000],
        "provider": provider,
        "model": model,
        "source_embed_id": source_embed_id,
        "output_embed_id": output_embed_id,
        "prompt_hash": hash_prompt(prompt or ""),
        "prompt_language": prompt_language,
        "assistant_response_id": assistant_response_id,
    }

    try:
        # Directus REST call via the shared directus_service
        # Use create_item if available, else fall back to raw HTTP helper.
        create = getattr(directus_service, "create_item", None)
        if callable(create):
            await create("safety_audit_log", entry)
            return

        # Fallback path: many directus services expose a generic post helper
        post = getattr(directus_service, "_post", None) or getattr(
            directus_service, "post", None
        )
        if callable(post):
            await post("/items/safety_audit_log", json=entry)
            return

        logger.warning(
            "[SafetyAudit] DirectusService has no create_item/_post helper; "
            "audit entry dropped (stage=%s decision=%s category=%s)",
            stage,
            decision,
            category,
        )
    except Exception as e:
        logger.error(
            f"[SafetyAudit] Failed to write audit entry: {e} "
            f"(stage={stage} decision={decision} category={category})",
            exc_info=True,
        )
