# backend/shared/python_utils/image_safety/strike_policy.py
#
# What happens after a safety violation is counted (StrikeCounter owns the count):
#   - strike 1 and 2: the user gets a warning in their language that names what
#     was rejected, the category-level reason with the allowed alternative
#     (explanations.py; none for hard limits) and "This is strike N of 3."
#   - strike 3: the account is deleted through the regular account-deletion task
#     (delete_user_account), which refunds eligible purchases like a
#     user-requested deletion.
#
# Wording lives in frontend/packages/ui/src/i18n/sources/safety_strikes.yml; the
# reasons and alternatives in image_safety.yml.

"""
Strike wording and the strike ladder shared by every source of safety strikes.

Ladder (accounts are never deleted automatically): strike 1 is a warning,
strike 2 suspends the account for 7 days, strike 3 suspends it until an admin
review that ends in restore or deletion. Strikes expire after 90 days. The
suspension itself lives in `account_suspension.py`; this module only builds the
localized warning or suspension notice shown with the rejected request.
"""

import logging
from typing import Any, Optional

from .explanations import explain
from .strike_counter import BAN_THRESHOLD

logger = logging.getLogger(__name__)

SUBJECTS = ("image_generate", "image_edit", "video", "upload")

# Results where the classifier itself failed or is unavailable. They refuse the
# request (fail closed) but are never a violation: no strike, no ban, no violation audit.
TECHNICAL_CATEGORIES = frozenset({
    "safeguard_error",
    "safeguard_not_configured",
    "safeguard_parse_error",
    "sightengine_not_configured",
})


def is_technical_failure(category: str) -> bool:
    """True when a rejection comes from an unavailable or failing safety check."""
    return category in TECHNICAL_CATEGORIES


def unavailable_message(language: Optional[str]) -> str:
    """Retry message for a refused request whose safety check was unavailable."""
    return _translate("unavailable", language or "en")


def _translate(key: str, language: str) -> str:
    from backend.core.api.app.services.translations import TranslationService

    service = TranslationService()
    for lang in (language, "en"):
        text = service.get_nested_translation(f"safety_strikes.{key}", lang)
        if text != f"safety_strikes.{key}":
            return text
    raise LookupError(f"Missing translation source for safety_strikes.{key}")


def strike_warning(category: str, subject: str, strike_number: int, language: Optional[str]) -> str:
    """Warning on strike 1; the suspension notice from strike 2 on."""
    lang = language or "en"
    if strike_number >= BAN_THRESHOLD:
        return _translate("suspended_pending_review", lang)
    if strike_number == 2:
        from datetime import datetime, timedelta, timezone

        until = datetime.now(timezone.utc) + timedelta(days=7)
        return _translate("suspended_until", lang).replace("{date}", until.strftime("%Y-%m-%d"))
    what = _translate(f"what_{subject if subject in SUBJECTS else 'image_generate'}", lang)
    # Category-level reason plus the allowed alternative (none for hard limits).
    reason, alternative = explain(category, lang)
    if alternative:
        reason = f"{reason} {alternative}"
    return (
        _translate("warning", lang)
        .replace("{what}", what)
        .replace("{reason}", reason)
        .replace("{strike}", str(strike_number))
        .replace("{max}", str(BAN_THRESHOLD))
    )


async def user_language(cache_service: Any, user_id: str) -> str:
    """The user's interface language from the cached user record, English when unknown."""
    user = await cache_service.get_user_by_id(user_id)
    return (user or {}).get("language") or "en"
