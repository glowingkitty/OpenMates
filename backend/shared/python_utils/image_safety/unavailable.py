# backend/shared/python_utils/image_safety/unavailable.py
#
# Localized refusal for a request whose safety check could not reach a
# decision (provider error or missing configuration). Such a refusal is never
# a user violation: the caller records no strike, writes no violation audit
# entry and never starts an account deletion.
#
# Wording: frontend/packages/ui/src/i18n/sources/safety_strikes.yml (unavailable)

import logging
from typing import Any, Dict, Optional

from .messages import build_unavailable_payload

logger = logging.getLogger(__name__)

_KEY = "safety_strikes.unavailable"


def unavailable_message(language: Optional[str]) -> str:
    """The "safety check temporarily unavailable" text in the user's language."""
    from backend.core.api.app.services.translations import TranslationService

    service = TranslationService()
    for lang in (language or "en", "en"):
        text = service.get_nested_translation(_KEY, lang)
        if text and text != _KEY:
            return text
    raise LookupError(f"Missing translation source for {_KEY}")


async def user_language(cache_service: Any, user_id: str) -> str:
    """The user's interface language from the cached user record, English when unknown."""
    user = await cache_service.get_user_by_id(user_id)
    return (user or {}).get("language") or "en"


async def unavailable_tool_response(cache_service: Any, user_id: str) -> Dict[str, Any]:
    """Tool response for the LLM and the error embed, localized for the user."""
    language = await user_language(cache_service, user_id)
    return build_unavailable_payload(unavailable_message(language))
