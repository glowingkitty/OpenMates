# backend/core/api/app/utils/override_parser.py
#
# Parser for user override syntax in messages.
# Allows users to override automatic model selection, mate selection,
# skill usage, and focus modes by using @ mentions in their messages.
#
# Supported syntax:
#   @ai-model:{model_id}              - Force a specific AI model
#   @ai-model:{model_id}:{provider}   - Force a specific AI model with provider
#   @best-model:{category}            - Use top-ranked model in a leaderboard category
#   @mate:{mate_id}                   - Force a specific mate/persona
#   @skill:{app_id}:{skill_id}        - Force using a specific skill
#   @focus:{app_id}:{focus_id}        - Force a specific focus mode
#
# Examples:
#   "What is 2+2? @ai-model:claude-opus-4-5" -> Uses Claude Opus 4.5 for this request
#   "Write code @best-model:coding" -> Uses the top coding model from leaderboard

import re
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class UserOverrides:
    """
    Container for parsed user overrides from message content.

    Attributes:
        model_id: Overridden AI model ID (e.g., "claude-opus-4-5-20251101")
        model_provider: Overridden model provider (e.g., "anthropic", "openrouter")
        best_model_category: Category for dynamic best-model resolution (e.g., "coding", "math")
        mate_id: Overridden mate/persona ID (e.g., "coder", "researcher")
        skills: List of (app_id, skill_id) tuples for forced skill usage
        focus_modes: List of (app_id, focus_id) tuples for forced focus modes
        cleaned_message: Original message with all override syntax removed
        has_overrides: True if any overrides were parsed
    """
    model_id: Optional[str] = None
    model_provider: Optional[str] = None
    best_model_category: Optional[str] = None
    mate_id: Optional[str] = None
    skills: List[Tuple[str, str]] = field(default_factory=list)
    focus_modes: List[Tuple[str, str]] = field(default_factory=list)
    cleaned_message: str = ""
    has_overrides: bool = False


# Regex patterns for parsing override syntax
# Each pattern captures the relevant parts in groups

# @ai-model:{model_id} or @ai-model:{model_id}:{provider}
# Examples: @ai-model:claude-opus-4-5, @ai-model:gpt-5.2:openrouter
_MODEL_PATTERN = re.compile(
    r'@ai-model:([a-zA-Z0-9._-]+)(?::([a-zA-Z0-9_-]+))?',
    re.IGNORECASE
)

# @best-model:{category}
# Examples: @best-model:coding, @best-model:math, @best-model:reasoning
# Dynamically resolves to the top-ranked model in that leaderboard category
_BEST_MODEL_PATTERN = re.compile(
    r'@best-model:([a-zA-Z0-9_-]+)',
    re.IGNORECASE
)

# @mate:{mate_id}
# Examples: @mate:coder, @mate:researcher, @mate:creative_writer
_MATE_PATTERN = re.compile(
    r'@mate:([a-zA-Z0-9_-]+)',
    re.IGNORECASE
)

# @skill:{app_id}:{skill_id}
# Examples: @skill:web:search, @skill:code:get_docs, @skill:images:generate
_SKILL_PATTERN = re.compile(
    r'@skill:([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+)',
    re.IGNORECASE
)

# @focus:{app_id}:{focus_id}
# Examples: @focus:web:research, @focus:code:review, @focus:ai:deep_think
_FOCUS_PATTERN = re.compile(
    r'@focus:([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+)',
    re.IGNORECASE
)


def parse_overrides(message: str, log_prefix: str = "") -> UserOverrides:
    """
    Parse user override syntax from a message.

    Extracts @ai-model, @mate, @skill, and @focus directives from the message
    and returns a UserOverrides dataclass with the parsed values and cleaned message.

    Args:
        message: The raw user message that may contain override syntax
        log_prefix: Optional prefix for log messages (e.g., "[Task ID: xxx]")

    Returns:
        UserOverrides dataclass with parsed values and cleaned message

    Example:
        >>> result = parse_overrides("What is AI? @ai-model:claude-opus-4-5")
        >>> result.model_id
        'claude-opus-4-5'
        >>> result.cleaned_message
        'What is AI?'
    """
    if not message:
        return UserOverrides(cleaned_message="")

    overrides = UserOverrides(cleaned_message=message)
    cleaned = message

    # Parse @ai-model override
    model_match = _MODEL_PATTERN.search(message)
    if model_match:
        overrides.model_id = model_match.group(1)
        overrides.model_provider = model_match.group(2)  # May be None
        overrides.has_overrides = True
        cleaned = _MODEL_PATTERN.sub('', cleaned)
        logger.info(
            f"{log_prefix} USER_OVERRIDE: Model override detected. "
            f"model_id={overrides.model_id}, provider={overrides.model_provider}"
        )

    # Parse @best-model override (mutually exclusive with @ai-model)
    # Only parse if no direct model_id was specified
    if not overrides.model_id:
        best_model_match = _BEST_MODEL_PATTERN.search(message)
        if best_model_match:
            overrides.best_model_category = best_model_match.group(1).lower()
            overrides.has_overrides = True
            cleaned = _BEST_MODEL_PATTERN.sub('', cleaned)
            logger.info(
                f"{log_prefix} USER_OVERRIDE: Best-model category override detected. "
                f"category={overrides.best_model_category}"
            )

    # Parse @mate override
    mate_match = _MATE_PATTERN.search(message)
    if mate_match:
        overrides.mate_id = mate_match.group(1)
        overrides.has_overrides = True
        cleaned = _MATE_PATTERN.sub('', cleaned)
        logger.info(
            f"{log_prefix} USER_OVERRIDE: Mate override detected. "
            f"mate_id={overrides.mate_id}"
        )

    # Parse all @skill overrides (can have multiple)
    for skill_match in _SKILL_PATTERN.finditer(message):
        app_id = skill_match.group(1)
        skill_id = skill_match.group(2)
        overrides.skills.append((app_id, skill_id))
        overrides.has_overrides = True
        logger.info(
            f"{log_prefix} USER_OVERRIDE: Skill override detected. "
            f"app_id={app_id}, skill_id={skill_id}"
        )
    cleaned = _SKILL_PATTERN.sub('', cleaned)

    # Parse all @focus overrides (can have multiple)
    for focus_match in _FOCUS_PATTERN.finditer(message):
        app_id = focus_match.group(1)
        focus_id = focus_match.group(2)
        overrides.focus_modes.append((app_id, focus_id))
        overrides.has_overrides = True
        logger.info(
            f"{log_prefix} USER_OVERRIDE: Focus mode override detected. "
            f"app_id={app_id}, focus_id={focus_id}"
        )
    cleaned = _FOCUS_PATTERN.sub('', cleaned)

    # Clean up extra whitespace from removed override patterns
    overrides.cleaned_message = ' '.join(cleaned.split())

    if overrides.has_overrides:
        logger.info(
            f"{log_prefix} USER_OVERRIDE: Total overrides parsed. "
            f"model={overrides.model_id}, mate={overrides.mate_id}, "
            f"skills={len(overrides.skills)}, focus_modes={len(overrides.focus_modes)}"
        )

    return overrides


def parse_overrides_from_messages(
    messages: List[dict],
    log_prefix: str = ""
) -> Tuple[UserOverrides, List[dict]]:
    """
    Parse overrides from the last user message in a message history.

    This is a convenience function that extracts overrides from the most recent
    user message and returns both the parsed overrides and an updated message
    history with the cleaned message.

    Args:
        messages: List of message dicts with 'role' and 'content' keys
        log_prefix: Optional prefix for log messages

    Returns:
        Tuple of (UserOverrides, updated_messages_list)
        The updated messages list has the last user message's content cleaned

    Example:
        >>> messages = [
        ...     {"role": "user", "content": "Hello @ai-model:gpt-5.2"}
        ... ]
        >>> overrides, cleaned_messages = parse_overrides_from_messages(messages)
        >>> overrides.model_id
        'gpt-5.2'
        >>> cleaned_messages[0]["content"]
        'Hello'
    """
    if not messages:
        return UserOverrides(cleaned_message=""), []

    # Find the last user message
    last_user_msg_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_msg_idx = i
            break

    if last_user_msg_idx is None:
        return UserOverrides(cleaned_message=""), messages

    # Parse overrides from the last user message
    last_user_content = messages[last_user_msg_idx].get("content", "")
    overrides = parse_overrides(last_user_content, log_prefix)

    # Create updated messages list with cleaned content
    updated_messages = messages.copy()
    updated_messages[last_user_msg_idx] = {
        **messages[last_user_msg_idx],
        "content": overrides.cleaned_message
    }

    return overrides, updated_messages


def validate_model_override(
    model_id: str,
    provider_id: Optional[str],
    available_models: dict,
    log_prefix: str = ""
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validate that a user-specified model override is available.

    Args:
        model_id: The model ID specified by the user
        provider_id: Optional provider ID specified by the user
        available_models: Dict mapping model_id -> model config from provider YAMLs
        log_prefix: Optional prefix for log messages

    Returns:
        Tuple of (is_valid, resolved_model_id, resolved_provider_id)
        If invalid, resolved values will be None
    """
    if not model_id:
        return False, None, None

    # Check if model exists
    if model_id not in available_models:
        # Try case-insensitive match
        for available_id in available_models.keys():
            if available_id.lower() == model_id.lower():
                model_id = available_id
                break
        else:
            logger.warning(
                f"{log_prefix} USER_OVERRIDE: Invalid model override. "
                f"Model '{model_id}' not found in available models."
            )
            return False, None, None

    model_config = available_models[model_id]

    # Validate provider if specified
    if provider_id:
        servers = model_config.get("servers", [])
        valid_providers = [s.get("id") for s in servers]
        if provider_id.lower() not in [p.lower() for p in valid_providers]:
            logger.warning(
                f"{log_prefix} USER_OVERRIDE: Invalid provider override. "
                f"Provider '{provider_id}' not available for model '{model_id}'. "
                f"Available providers: {valid_providers}"
            )
            return False, None, None
        # Normalize provider ID to match config
        for vp in valid_providers:
            if vp.lower() == provider_id.lower():
                provider_id = vp
                break
    else:
        # Use default provider for the model
        provider_id = model_config.get("default_server")

    logger.info(
        f"{log_prefix} USER_OVERRIDE: Model override validated. "
        f"model_id={model_id}, provider_id={provider_id}"
    )
    return True, model_id, provider_id
