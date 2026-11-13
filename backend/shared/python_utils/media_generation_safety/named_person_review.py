from __future__ import annotations

import logging
from typing import Any, Optional

from backend.shared.providers.groq.safeguard import get_safeguard_client

from .pipeline import MediaGenerationDecision, validate_media_generation_request

logger = logging.getLogger(__name__)

_SAFEGUARD_MEDIA = {"image": "picture", "video": "video"}


async def check_image_generation_request(
    *, prompt: str, style: Optional[str] = None, secrets_manager: Any = None,
) -> MediaGenerationDecision:
    """Fixed rules first; a named-person refusal marked ``needs_review`` goes to the safeguard model."""
    return await check_named_person_media_request(
        media_type="image", prompt=prompt, style=style, secrets_manager=secrets_manager,
    )


async def check_named_person_media_request(
    *, media_type: str, prompt: str, style: Optional[str] = None, secrets_manager: Any = None,
) -> MediaGenerationDecision:
    """Fixed rules first; a picture or video refusal marked ``needs_review`` goes to the safeguard model.

    The fixed rules read any run of capitalised words as a possible name, so a video
    titled "How Bees Make Honey" with a voice-over looks like a named voice. The
    safeguard model decides those; explicit imitation is refused by the rules alone.
    """
    media = _SAFEGUARD_MEDIA.get(media_type)
    if media is None:
        raise ValueError(f"No named-person review for media type {media_type!r}")
    decision = validate_media_generation_request(media_type=media_type, prompt=prompt, request_count=1, style=style)
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
    verdict = await safeguard.classify_named_person_image(prompt=text, media=media)
    logger.info("[MediaSafety] named-person %s review approved=%s category=%s", media, verdict.approved,
                verdict.category)
    if not verdict.approved:
        return decision
    return MediaGenerationDecision(allowed=True, reason="named_person_reviewed")
