# backend/shared/python_utils/media_generation_safety/named_person_review.py
#
# Second step of the media safety gate for picture prompts that name someone.
# The fixed rules refuse every such prompt; they cannot tell a public figure from
# the user's own relative or a fictional character. For those prompts only, the
# safeguard model decides. Any error, missing key or unclear answer keeps the refusal.

from __future__ import annotations

import logging
from typing import Any, Optional

from backend.shared.providers.groq.safeguard import get_safeguard_client

from .pipeline import MediaGenerationDecision, validate_media_generation_request

logger = logging.getLogger(__name__)


async def check_image_generation_request(
    *, prompt: str, style: Optional[str] = None, secrets_manager: Any = None,
) -> MediaGenerationDecision:
    """Fixed rules first; a named-person refusal marked ``needs_review`` goes to the safeguard model."""
    decision = validate_media_generation_request(media_type="image", prompt=prompt, request_count=1, style=style)
    if decision.allowed or not decision.needs_review:
        return decision
    safeguard = get_safeguard_client()
    if secrets_manager is None and not safeguard.is_enabled:
        from backend.core.api.app.utils.secrets_manager import SecretsManager

        secrets_manager = SecretsManager()
        await secrets_manager.initialize()
    if secrets_manager is not None:
        await safeguard.initialize(secrets_manager)
    text = prompt if not style else f"{prompt}\nStyle: {style}"
    verdict = await safeguard.classify_named_person_image(prompt=text)
    logger.info("[MediaSafety] named-person review approved=%s category=%s", verdict.approved, verdict.category)
    if not verdict.approved:
        return decision
    return MediaGenerationDecision(allowed=True, reason="named_person_reviewed")
