# backend/apps/ai/daily_inspiration/validator.py
# Post-generation adversarial content validator (Layer 6).
#
# Runs AFTER the generator LLM produces an inspiration, BEFORE it enters the pool.
# Uses a separate LLM call as a pure classifier — different role than the generator.
# The validator outputs standardized English tags regardless of content language,
# which are then checked against the hardcoded blocklist from content_filter.
#
# This is the "two-key" pattern: content only enters the pool if both the
# generator (Layer 5) AND the validator (Layer 6) agree it's appropriate.
#
# The validator solves the multilingual problem: a German bible video gets
# tags ["religion", "bible", "sermon"] in English, which hit the blocklist.

import logging
from typing import Any, Dict, List

from backend.apps.ai.daily_inspiration.content_filter import check_tags
from backend.apps.ai.utils.llm_utils import LLMPreprocessingCallResult, call_preprocessing_llm
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Use the same lightweight model as the generator for cost efficiency
VALIDATOR_MODEL_ID = "mistral/mistral-small-2506"


def _build_validator_tool() -> Dict[str, Any]:
    """Build the tool definition for the adversarial content validator."""
    return {
        "type": "function",
        "function": {
            "name": "validate_content",
            "description": (
                "Validate a daily inspiration entry against content policies. "
                "Determine if it violates any policy and output standardized English "
                "classification tags.\n\n"
                "POLICIES (any violation = REJECT):\n"
                "1. NO RELIGIOUS PROMOTION: Content that promotes, proselytizes, or "
                "advocates for a specific religion. Sermons, prayer guides, religious "
                "testimonials, faith-based motivational content, content from religious "
                "organizations. A video presenting religion as truth or urging devotion = REJECT.\n"
                "2. NO PRODUCT REVIEWS: Content reviewing, comparing, ranking, or recommending "
                "specific commercial products, devices, gadgets, apps. Unboxing, hands-on reviews, "
                "buying guides, 'best of' lists, deal alerts = REJECT.\n"
                "3. NO POLITICAL PROPAGANDA: Content promoting political parties, candidates, "
                "campaigns, or partisan ideologies = REJECT.\n"
                "4. NO CORPORATE PR: Content from corporate channels disguised as education = REJECT.\n"
                "5. NO PROHIBITED CONTENT: Drugs, explicit sexual content, graphic violence, "
                "self-harm, weapons manufacturing = REJECT.\n\n"
                "ACCEPTABLE: Education, science, history, how-things-work, documentaries, "
                "university lectures, independent creator explainers. Religion as academic "
                "study (history, architecture, philosophy) is OK if treated as study, not devotion.\n\n"
                "Be STRICT. When in doubt, REJECT."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["PASS", "REJECT"],
                        "description": "PASS if clean, REJECT if any policy violated.",
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "Brief reason for rejection (empty string for PASS). "
                            "Be specific: which policy and what content triggered it."
                        ),
                    },
                    "tags": {
                        "type": "array",
                        "description": (
                            "Standardized ENGLISH classification tags for this content. "
                            "ALWAYS output tags in English regardless of content language. "
                            "Include topic tags (e.g. 'science', 'history', 'cooking') AND "
                            "any violation tags (e.g. 'religion', 'product-review', 'sermon'). "
                            "Use lowercase with hyphens. Be thorough."
                        ),
                        "items": {"type": "string"},
                    },
                },
                "required": ["verdict", "reason", "tags"],
            },
        },
    }


def _build_validator_prompt(
    phrase: str,
    title: str,
    assistant_response: str,
    video_title: str,
    channel_name: str,
) -> List[Dict[str, str]]:
    """Build the message for the validator LLM call."""
    return [
        {
            "role": "user",
            "content": (
                "You are a strict content policy validator for a public daily inspiration feed. "
                "Your ONLY job is to catch content that should NEVER appear: religious promotion, "
                "product reviews, political propaganda, corporate PR, or prohibited content.\n\n"
                "IMPORTANT: Output ALL tags in English regardless of the content's language.\n\n"
                f"Entry to validate:\n"
                f"- Phrase: {phrase}\n"
                f"- Title: {title}\n"
                f"- Video title: {video_title}\n"
                f"- Channel: {channel_name}\n"
                f"- Assistant response: {assistant_response[:500]}\n\n"
                "Is this content appropriate for a public inspiration feed?"
            ),
        }
    ]


async def validate_inspiration(
    phrase: str,
    title: str,
    assistant_response: str,
    video_title: str,
    channel_name: str,
    secrets_manager: SecretsManager,
    task_id: str = "daily_inspiration",
) -> bool:
    """
    Validate a single inspiration entry via the adversarial LLM validator.

    Runs a separate LLM call to classify the content, then checks the returned
    English tags against the hardcoded blocklist. REJECT if either the LLM verdict
    or the tag check fires.

    Args:
        phrase: The curiosity phrase shown on the banner.
        title: The chat sidebar title.
        assistant_response: The first assistant message.
        video_title: The YouTube video title.
        channel_name: The YouTube channel name.
        secrets_manager: For API key retrieval.
        task_id: For logging context.

    Returns:
        True if the content passes validation, False if it should be rejected.
    """
    tool_def = _build_validator_tool()
    messages = _build_validator_prompt(
        phrase, title, assistant_response, video_title, channel_name,
    )

    try:
        result: LLMPreprocessingCallResult = await call_preprocessing_llm(
            task_id=f"{task_id}_validator",
            model_id=VALIDATOR_MODEL_ID,
            message_history=messages,
            tool_definition=tool_def,
            secrets_manager=secrets_manager,
        )

        if result.error_message or not result.arguments:
            logger.warning(
                f"[DailyInspiration][{task_id}] Validator LLM call failed: "
                f"{result.error_message} — keeping inspiration (fail-open)"
            )
            return True  # Fail open

        llm_verdict = result.arguments.get("verdict", "REJECT")
        reason = result.arguments.get("reason", "")
        tags = [t.lower().strip() for t in result.arguments.get("tags", [])]

        # Check tags against hardcoded blocklist
        blocked_tags, warning_tags = check_tags(tags)

        # REJECT if LLM says REJECT OR if any blocked tag matched
        if llm_verdict == "REJECT" or blocked_tags:
            reject_reason = reason if llm_verdict == "REJECT" else f"Blocked tags: {blocked_tags}"
            logger.info(
                f"[DailyInspiration][{task_id}] Validator REJECT: '{title}' — "
                f"llm_verdict={llm_verdict}, blocked_tags={blocked_tags}, "
                f"reason={reject_reason}, all_tags={tags}"
            )
            return False

        if warning_tags:
            logger.info(
                f"[DailyInspiration][{task_id}] Validator PASS with warnings: '{title}' — "
                f"warning_tags={warning_tags}, all_tags={tags}"
            )

        return True

    except Exception as e:
        logger.warning(
            f"[DailyInspiration][{task_id}] Validator exception: {e} — "
            "keeping inspiration (fail-open)",
            exc_info=True,
        )
        return True  # Fail open
