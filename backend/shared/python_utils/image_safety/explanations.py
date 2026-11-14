# backend/shared/python_utils/image_safety/explanations.py
#
# Localized explanations for refused image and video requests: a category-level
# reason and, where one fits, the alternative that is allowed. Hard limits
# (child sexual abuse, intimate images of real people, safety-rule bypass) get a
# short, firm reason only. No explanation ever names the check, classifier,
# score or threshold that fired.
#
# Wording: frontend/packages/ui/src/i18n/sources/image_safety.yml
# Policy:  docs/architecture/image-safety-policy.md ("Category taxonomy")

from typing import Any, Dict, Optional, Tuple

from .messages import category_info

_NAMESPACE = "image_safety"

# category -> (reason key, alternative key or None)
_EXPLANATIONS: Dict[str, Tuple[str, Optional[str]]] = {
    "S1_csam": ("reason_child_sexual", None),
    "S2_ncii": ("reason_intimate_real_person", None),
    "S3_sexual_other": ("reason_sexual", "alternative_sexual"),
    "S4_violent_recontextualization": ("reason_violent", "alternative_violent"),
    "S5_minor_restricted_edit": ("reason_minor", "alternative_minor"),
    "S6_public_figure_blocked": ("reason_public_figure", "alternative_public_figure"),
    "S7_identity_replacement": ("reason_identity", "alternative_identity"),
    "S8_id_document": ("reason_id_document", None),
    "S9_hate_symbol": ("reason_hate", None),
    "S10_self_harm": ("reason_self_harm", "alternative_self_harm"),
    "S11_weapon_instruction": ("reason_weapons", None),
    "S12_adversarial_bypass": ("reason_bypass", None),
    # Rule-based media gate (media_generation_safety/pipeline.py)
    "G1_scam_or_fraud": ("reason_scam", "alternative_scam"),
    "G2_spam_or_slop": ("reason_spam", "alternative_spam"),
    "G3_public_figure_voice_or_persona": ("reason_public_figure", "alternative_public_figure"),
    "G4_deceptive_synthetic_media": ("reason_deceptive", "alternative_deceptive"),
    "unknown": ("reason_other", "alternative_other"),
}

# Refused under a hard limit: firm reason, no alternative, no hint how to rephrase.
HARD_LIMIT_CATEGORIES = frozenset({"S1_csam", "S2_ncii", "S12_adversarial_bypass"})

_INSTRUCTIONS = (
    "The safety rules refused this request. Do not retry or reformulate it "
    "yourself and do not call images-generate again in this response. Explain "
    "the reason to the user plainly, in their language, based on "
    "user_facing_message. If `alternative` is present, offer it as something the "
    "user can ask for next. Do not say which check, classifier or signal made "
    "the decision."
)
_HARD_LIMIT_INSTRUCTIONS = (
    "This request was refused under a hard safety limit. Do not call "
    "images-generate again in this response. Do not retry, reformulate, suggest "
    "alternatives or explain how the request could be changed to pass. State the "
    "reason from user_facing_message briefly and firmly in the user's language "
    "and add no details about the checks."
)


def has_explanation(category: str) -> bool:
    """True when the category has a localized reason (else the generic one is used)."""
    return category in _EXPLANATIONS


def _translate(key: str, language: str) -> str:
    from backend.core.api.app.services.translations import TranslationService

    service = TranslationService()
    full_key = f"{_NAMESPACE}.{key}"
    for lang in (language, "en"):
        text = service.get_nested_translation(full_key, lang)
        if text and text != full_key:
            return text
    raise LookupError(f"Missing translation source for {full_key}")


def explain(category: str, language: Optional[str]) -> Tuple[str, Optional[str]]:
    """Return (reason, alternative or None) for a category, in the user's language."""
    reason_key, alternative_key = _EXPLANATIONS.get(category, _EXPLANATIONS["unknown"])
    lang = language or "en"
    reason = _translate(reason_key, lang)
    alternative = _translate(alternative_key, lang) if alternative_key else None
    return reason, alternative


def localized_rejection_payload(
    category: str,
    language: Optional[str],
    *,
    severity: Optional[str] = None,
    error: str = "safety_rejection",
) -> Dict[str, Any]:
    """Tool response for the LLM and the error embed, explained in the user's language."""
    category = category or "unknown"
    reason, alternative = explain(category, language)
    hard_limit = category in HARD_LIMIT_CATEGORIES
    payload: Dict[str, Any] = {
        "error": error,
        "category": category,
        "severity": severity or category_info(category)["severity"],
        "reason": reason,
        "user_facing_message": f"{reason} {alternative}" if alternative else reason,
        "hard_limit": hard_limit,
        "instructions_to_llm": _HARD_LIMIT_INSTRUCTIONS if hard_limit else _INSTRUCTIONS,
        "do_not_retry": True,
    }
    if alternative:
        payload["alternative"] = alternative
    return payload
