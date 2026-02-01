# backend/core/api/app/services/china_sensitivity.py
#
# Service for detecting China-sensitive content in user messages.
# Used to filter out Chinese-origin AI models when handling sensitive topics
# to ensure appropriate model selection and avoid potential issues.
#
# IMPORTANT: This is not censorship - it's about selecting appropriate models.
# Chinese-origin models may have different training data and behaviors on these topics,
# so for factual accuracy and user experience, we route such queries to non-CN models.

import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


# Keywords and phrases that indicate China-sensitive topics
# These are topics where Chinese-origin AI models may have different training
# or may provide different perspectives compared to non-Chinese models
CHINA_SENSITIVE_KEYWORDS = [
    # Geographic/political entities
    "china",
    "chinese",
    "taiwan",
    "taiwanese",
    "tibet",
    "tibetan",
    "xinjiang",
    "uyghur",
    "uighur",
    "hong kong",
    "hongkong",
    "macau",
    "macao",

    # Political terms
    "ccp",
    "chinese communist party",
    "communist party of china",
    "prc",
    "people's republic of china",
    "republic of china",
    "roc",
    "kuomintang",
    "kmt",
    "dpp",
    "democratic progressive party",

    # Historical events
    "tiananmen",
    "tiananmen square",
    "june 4th 1989",
    "june fourth",
    "tank man",
    "cultural revolution",
    "great leap forward",
    "falun gong",
    "falun dafa",

    # Political figures (historical and contemporary)
    "xi jinping",
    "mao zedong",
    "mao tse-tung",
    "deng xiaoping",
    "dalai lama",
    "tenzin gyatso",
    "liu xiaobo",
    "ai weiwei",

    # Sensitive topics
    "one china policy",
    "two systems",
    "one country two systems",
    "south china sea",
    "nine dash line",
    "nine-dash line",
    "senkaku",
    "diaoyu",
    "spratly",
    "paracel",

    # Human rights related
    "uyghur camps",
    "re-education camps",
    "forced labor china",
    "organ harvesting china",
    "great firewall",
    "internet censorship china",

    # Technology/security concerns
    "huawei ban",
    "tiktok ban",
    "china spy",
    "chinese espionage",
    "confucius institute",

    # Economic/trade
    "china trade war",
    "chip ban china",
    "semiconductor china",

    # Chinese characters for key terms (in case users type in Chinese)
    "中国",
    "中華人民共和國",
    "台湾",
    "台灣",
    "西藏",
    "新疆",
    "香港",
    "天安门",
    "六四",
    "共产党",
    "習近平",
    "习近平",
]

# Compiled regex patterns for efficient matching
# We use word boundaries where appropriate to avoid false positives
_COMPILED_PATTERNS: List[re.Pattern] = []


def _compile_patterns() -> List[re.Pattern]:
    """
    Compile regex patterns for efficient repeated matching.
    Uses word boundaries for English terms to avoid false positives.
    """
    global _COMPILED_PATTERNS
    if _COMPILED_PATTERNS:
        return _COMPILED_PATTERNS

    patterns = []
    for keyword in CHINA_SENSITIVE_KEYWORDS:
        # For ASCII keywords, use word boundaries to avoid false positives
        # e.g., "china" should match "China" but not "machinery"
        if keyword.isascii():
            # Escape special regex characters and add word boundaries
            escaped = re.escape(keyword)
            pattern = re.compile(rf'\b{escaped}\b', re.IGNORECASE)
        else:
            # For non-ASCII (Chinese characters), just use direct matching
            pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        patterns.append(pattern)

    _COMPILED_PATTERNS = patterns
    return patterns


def is_china_related(messages: List[Dict[str, Any]], log_prefix: str = "") -> bool:
    """
    Check if the conversation contains China-sensitive keywords.

    This function analyzes user messages in the conversation history to detect
    topics where Chinese-origin AI models may have different training or behaviors.
    When detected, the model selection system can prefer non-CN models for these queries.

    Args:
        messages: List of message dictionaries with 'role' and 'content' keys.
                  Typically from message_history in the request.
        log_prefix: Optional prefix for log messages (e.g., task_id)

    Returns:
        True if China-sensitive keywords are found in user messages, False otherwise.

    Example:
        >>> messages = [{"role": "user", "content": "What happened at Tiananmen Square?"}]
        >>> is_china_related(messages)
        True

        >>> messages = [{"role": "user", "content": "What's the weather like?"}]
        >>> is_china_related(messages)
        False
    """
    if not messages:
        return False

    patterns = _compile_patterns()

    # Check user messages (not assistant messages)
    for msg in messages:
        if msg.get("role") != "user":
            continue

        content = msg.get("content", "")
        if not content or not isinstance(content, str):
            continue

        # Check each pattern against the content
        for pattern in patterns:
            if pattern.search(content):
                matched_keyword = pattern.pattern.replace(r'\b', '').replace('\\', '')
                logger.info(
                    f"{log_prefix} China-sensitive content detected. "
                    f"Matched keyword pattern: '{matched_keyword}'"
                )
                return True

    return False


def get_matched_keywords(messages: List[Dict[str, Any]]) -> List[str]:
    """
    Get a list of all matched China-sensitive keywords in the messages.
    Useful for debugging and logging.

    Args:
        messages: List of message dictionaries with 'role' and 'content' keys.

    Returns:
        List of matched keywords (may contain duplicates if keyword appears multiple times).
    """
    if not messages:
        return []

    patterns = _compile_patterns()
    matched = []

    for msg in messages:
        if msg.get("role") != "user":
            continue

        content = msg.get("content", "")
        if not content or not isinstance(content, str):
            continue

        for pattern in patterns:
            if pattern.search(content):
                # Extract the readable keyword from the pattern
                keyword = pattern.pattern.replace(r'\b', '').replace('\\', '')
                matched.append(keyword)

    return matched


def check_and_log_sensitivity(
    messages: List[Dict[str, Any]],
    task_id: str,
    chat_id: str
) -> bool:
    """
    Convenience function that checks for China sensitivity and logs the result.

    Args:
        messages: List of message dictionaries
        task_id: Task ID for logging
        chat_id: Chat ID for logging

    Returns:
        True if China-sensitive content detected, False otherwise
    """
    log_prefix = f"[Task ID: {task_id}, Chat ID: {chat_id}]"

    is_sensitive = is_china_related(messages, log_prefix)

    if is_sensitive:
        matched = get_matched_keywords(messages)
        logger.info(
            f"{log_prefix} CHINA_SENSITIVITY: Detected sensitive content. "
            f"Matched keywords: {matched}. "
            f"CN-origin models will be deprioritized for this request."
        )
    else:
        logger.debug(f"{log_prefix} CHINA_SENSITIVITY: No sensitive content detected.")

    return is_sensitive
