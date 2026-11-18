# backend/apps/ai/processing/request_purpose_policy.py
#
# Purpose-based chat request policy, answered inside the existing preprocessing
# decision call (no extra batch):
#   - harmful_purpose: propaganda, hate, disinformation or manipulative tabloid
#     content is declined and counts as one strike.
#   - illegal_category: sexual content involving minors, non-consensual intimate
#     images, sexual deepfakes of real people and mass-harm weapons are declined
#     and count as one strike.
#   - live_site_abuse: a mass or abusive action OpenMates itself would take against
#     a live third-party site is declined politely, without a strike.
#   - live_site_abuse_repeated_across_sites: clear signs of repeated attempts against
#     several sites that are obviously not the user's own count as one strike.
# Explaining, analysing or reporting on these topics, writing code the user runs
# themselves and plausible ownership claims never count.

"""Questions, outcome rules and strike recording for purpose-based request safety."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional

HARMFUL_PURPOSES = ("propaganda", "hate", "disinformation", "manipulative_tabloid")
ILLEGAL_CATEGORIES = ("minor_sexual_content", "non_consensual_intimate_image", "sexual_deepfake", "mass_harm_weapon")
QUESTION_IDS = ("harmful_purpose", "illegal_category", "live_site_abuse", "live_site_abuse_repeated_across_sites")
LIVE_SITE_THRESHOLD = 0.65
REQUEST_PURPOSE_REJECTION = "request_purpose_declined"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PurposeOutcome:
    """Result of judging a request: allow, decline, or decline with one strike."""

    action: str  # "allow" | "decline" | "decline_strike"
    category: str = ""
    message_key: str = ""

    @property
    def strike(self) -> bool:
        return self.action == "decline_strike"


ALLOW = PurposeOutcome("allow")

_ANALYSIS = (" Explaining, analysing, fact-checking, reporting, history, education, criticism and clearly "
             "labelled satire are none; judge the content the user asks to be produced, not who asks.")


def request_purpose_questions() -> dict[str, dict[str, Any]]:
    """Decision question definitions added to the public decision set."""
    return {
        "harmful_purpose": {
            "type": "choice",
            "instructions": "Does the latest request ask OpenMates to produce content whose purpose is harmful?" + _ANALYSIS,
            "criteria": {
                "propaganda": "Persuasive political or ideological propaganda meant to manipulate people",
                "hate": "Content that demeans or incites hatred against people for who they are",
                "disinformation": "False or misleading content made to be believed and spread as true",
                "manipulative_tabloid": "Sensational manipulative tabloid content built to deceive or exploit",
                "none": "Anything else, including explanation, analysis and labelled satire",
            },
        },
        "illegal_category": {
            "type": "choice",
            "instructions": "Does the latest request seek one of these illegal categories? Discussion, prevention, "
                            "law and research about them are none.",
            "criteria": {
                "minor_sexual_content": "Sexual content involving minors",
                "non_consensual_intimate_image": "Intimate images of a person without their consent",
                "sexual_deepfake": "Sexual deepfakes of real people",
                "mass_harm_weapon": "Operational help to build or use mass-harm weapons",
                "none": "Anything else",
            },
        },
        "live_site_abuse": {
            "type": "noul",
            "instructions": "Does the user ask OpenMates itself to take a mass or abusive action against a live website, "
                            "such as mass comments or sign-ups, password guessing, flooding or large-scale scraping? "
                            "Writing code or scripts for the user to run, explaining attacks, CTFs and a single normal "
                            "action at human speed are no.",
            "criteria": {"true": "Mass or abusive action by OpenMates against a live site", "false": "Anything else"},
        },
        "live_site_abuse_repeated_across_sites": {
            "type": "noul",
            "instructions": "Does the conversation clearly show repeated mass or abusive attempts against several "
                            "different live sites that are obviously not the user's own? A single plausible ownership "
                            "claim is no.",
            "criteria": {"true": "Clear repeated abuse across several unrelated sites", "false": "Anything else"},
        },
    }


def extract_purpose_decisions(response: Any, choice_value: Any, noul_value: Any) -> dict[str, Any]:
    """Read the four answers from a decision response; raises ValueError when malformed."""
    decisions = {
        "harmful_purpose": choice_value(response, "harmful_purpose"),
        "illegal_category": choice_value(response, "illegal_category"),
        "live_site_abuse": round(noul_value(response, "live_site_abuse"), 2),
        "live_site_abuse_repeated_across_sites": round(noul_value(response, "live_site_abuse_repeated_across_sites"), 2),
    }
    if not valid_purpose_decisions(decisions):
        raise ValueError("malformed request purpose decisions")
    return decisions


def valid_purpose_decisions(value: Any) -> bool:
    """True for a complete, in-range decision mapping."""
    if not isinstance(value, Mapping) or set(value) != set(QUESTION_IDS):
        return False
    return (
        value["harmful_purpose"] in (*HARMFUL_PURPOSES, "none")
        and value["illegal_category"] in (*ILLEGAL_CATEGORIES, "none")
        and all(type(value[key]) in {int, float} and 0 <= value[key] <= 1
                for key in ("live_site_abuse", "live_site_abuse_repeated_across_sites"))
    )


def evaluate_request_purpose(decisions: Optional[Mapping[str, Any]]) -> PurposeOutcome:
    """Map decisions to an outcome. Missing or malformed decisions allow (the other safety paths still apply)."""
    if not valid_purpose_decisions(decisions):
        return ALLOW
    if decisions["illegal_category"] != "none":
        return PurposeOutcome("decline_strike", decisions["illegal_category"], "illegal_category")
    if decisions["harmful_purpose"] != "none":
        return PurposeOutcome("decline_strike", decisions["harmful_purpose"], "harmful_purpose")
    if decisions["live_site_abuse_repeated_across_sites"] >= LIVE_SITE_THRESHOLD:
        return PurposeOutcome("decline_strike", "live_site_abuse", "live_site_abuse")
    if decisions["live_site_abuse"] >= LIVE_SITE_THRESHOLD:
        return PurposeOutcome("decline", "live_site_abuse", "live_site_abuse")
    return ALLOW


def _translate(key: str, language: str) -> str:
    from backend.core.api.app.services.translations import TranslationService

    service = TranslationService()
    for lang in (language, "en"):
        text = service.get_nested_translation(f"request_purpose.{key}", lang)
        if text != f"request_purpose.{key}":
            return text
    raise LookupError(f"Missing translation source for request_purpose.{key}")


async def record_request_strike(
    outcome: PurposeOutcome, *, user_id: str, assistant_response_id: str, language: str,
    cache_service: Any, directus_service: Any,
) -> str:
    """Count one strike (debounced per assistant turn) and return the localized user message."""
    from backend.shared.python_utils.image_safety import strike_policy
    from backend.shared.python_utils.image_safety.account_suspension import suspend_account_for_strikes
    from backend.shared.python_utils.image_safety.strike_counter import BAN_THRESHOLD, get_strike_counter

    reason = _translate(outcome.message_key, language)
    result = await get_strike_counter(cache_service).record_strike(
        user_id=user_id, severity=outcome.category, assistant_response_id=assistant_response_id)
    if result.error is not None:
        logger.error("[RequestPurpose] strike not recorded: %s", result.error)
        return reason
    count = max(result.new_count, 1)
    if count == 1:
        notice = _translate("strike_notice", language).replace("{strike}", "1").replace("{max}", str(BAN_THRESHOLD))
    else:
        notice = strike_policy.strike_warning(outcome.category, "image_generate", count, language)
    if count >= 2 and result.recorded and not result.debounced:
        await suspend_account_for_strikes(
            user_id=user_id, strike_count=count, category=outcome.category,
            directus_service=directus_service, cache_service=cache_service,
        )
    return f"{reason} {notice}"


def decline_message(outcome: PurposeOutcome, language: str) -> str:
    """Localized polite decline without a strike."""
    return _translate(outcome.message_key, language)
