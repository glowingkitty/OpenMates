# backend/apps/ai/daily_inspiration/content_filter.py
# Shared content policy filter for the Daily Inspiration pipeline.
#
# Loads the canonical blocked_content_keywords.yml and provides word-boundary
# regex matching functions used at every filtering layer:
#   - Layer 1: topic suggestion filtering (generator.py)
#   - Layer 3: video metadata filtering (video_processor.py)
#   - Layer 6: post-generation validator tag checking (generator.py)
#   - Layer 7: scheduled pool audit (audit_inspiration_pool.py)
#
# Word-boundary matching prevents false positives like "amen" matching inside
# "Aktienbewertament" or "vs" matching inside "canvas".

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

logger = logging.getLogger(__name__)

# Path to the canonical keyword blocklist
_KEYWORDS_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "shared" / "config" / "blocked_content_keywords.yml"
)

# Cached loaded data — parsed once, reused across calls
_loaded_keywords: Optional[Dict[str, List[str]]] = None
_compiled_patterns: Optional[Dict[str, List[re.Pattern]]] = None


def _load_keywords() -> Dict[str, List[str]]:
    """
    Load and cache keyword categories from the YAML blocklist.

    Returns a dict mapping category names (e.g. 'religious', 'product_review')
    to lists of lowercase keyword strings.
    """
    global _loaded_keywords
    if _loaded_keywords is not None:
        return _loaded_keywords

    try:
        with open(_KEYWORDS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        keywords: Dict[str, List[str]] = {}
        for category, entries in data.items():
            if isinstance(entries, list):
                keywords[category] = [
                    str(entry).lower() for entry in entries if isinstance(entry, str)
                ]

        total = sum(len(v) for v in keywords.values())
        logger.info(
            f"[ContentFilter] Loaded {total} keywords across {len(keywords)} categories "
            f"from {_KEYWORDS_PATH.name}"
        )
        _loaded_keywords = keywords
        return keywords
    except Exception as e:
        logger.error(
            f"[ContentFilter] Failed to load keywords from {_KEYWORDS_PATH}: {e}",
            exc_info=True,
        )
        _loaded_keywords = {}
        return {}


def _compile_patterns() -> Dict[str, List[re.Pattern]]:
    """
    Compile regex patterns for all keywords with word-boundary matching.

    Short keywords (<=5 chars) and single-word keywords use \\b word boundaries
    to prevent false positives. Multi-word phrases use simple substring matching
    via a looser pattern (they're naturally specific enough).

    Company names always use word-boundary matching regardless of length.
    """
    global _compiled_patterns
    if _compiled_patterns is not None:
        return _compiled_patterns

    keywords = _load_keywords()
    patterns: Dict[str, List[re.Pattern]] = {}

    for category, keyword_list in keywords.items():
        category_patterns: List[re.Pattern] = []
        for kw in keyword_list:
            escaped = re.escape(kw)
            # Company names: always word-boundary (they're proper nouns)
            # Short single-word keywords (<=5 chars): word-boundary to prevent
            #   substring matches (e.g. "god" shouldn't match "godfather")
            # Keywords with non-alphanumeric chars (e.g. "review:"): substring
            #   matching since \b doesn't work at punctuation boundaries
            # Multi-word phrases (contain spaces): substring is fine (naturally specific)
            is_purely_alpha = kw.replace("-", "").replace(" ", "").isalpha()
            if category == "company_names":
                pattern = re.compile(rf"\b{escaped}\b", re.IGNORECASE)
            elif " " in kw:
                # Multi-word phrase — substring match
                pattern = re.compile(escaped, re.IGNORECASE)
            elif not is_purely_alpha:
                # Contains special chars like ":" — substring match
                pattern = re.compile(escaped, re.IGNORECASE)
            elif len(kw) <= 8:
                # Short single word — word-boundary to prevent false positives
                pattern = re.compile(rf"\b{escaped}\b", re.IGNORECASE)
            else:
                # Long single word (e.g. "methamphetamine") — substring is safe
                pattern = re.compile(escaped, re.IGNORECASE)
            category_patterns.append(pattern)
        patterns[category] = category_patterns

    _compiled_patterns = patterns
    return patterns


def check_text(
    text: str,
    categories: Optional[List[str]] = None,
) -> Dict[str, List[str]]:
    """
    Check a text string against the keyword blocklist.

    Args:
        text: The text to check (will be matched case-insensitively).
        categories: Optional list of category names to check. If None, checks all.

    Returns:
        Dict mapping category names to lists of matched keywords.
        Empty dict if no matches found.
    """
    if not text:
        return {}

    patterns = _compile_patterns()
    keywords = _load_keywords()
    violations: Dict[str, List[str]] = {}

    for category, category_patterns in patterns.items():
        if categories and category not in categories:
            continue
        matched = []
        for i, pattern in enumerate(category_patterns):
            if pattern.search(text):
                matched.append(keywords[category][i])
        if matched:
            violations[category] = matched

    return violations


def is_blocked(
    text: str,
    categories: Optional[List[str]] = None,
) -> bool:
    """
    Return True if the text matches any blocked keyword.

    Args:
        text: The text to check.
        categories: Optional list of category names to check. If None, checks all.
    """
    return bool(check_text(text, categories))


def check_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check a pool/defaults entry against all keyword categories.

    Concatenates all text fields and checks against the full blocklist.
    Used by the pool audit script (Layer 7).

    Args:
        entry: A dict with keys like 'title', 'phrase', 'assistant_response',
               'video_title', 'video_channel_name', 'category'.

    Returns:
        A result dict with 'verdict' ('PASS' or 'REJECT'), 'violations',
        and summary 'entry' metadata.
    """
    text_fields = [
        "title", "phrase", "assistant_response",
        "video_title", "video_channel_name", "category",
    ]
    text_parts = []
    for field in text_fields:
        value = entry.get(field, "")
        if value:
            text_parts.append(str(value))
    full_text = " ".join(text_parts)

    violations = check_text(full_text)
    verdict = "REJECT" if violations else "PASS"

    return {
        "entry_id": str(entry.get("id", "")),
        "verdict": verdict,
        "violations": violations,
        "entry": {
            "id": entry.get("id"),
            "language": entry.get("language"),
            "title": entry.get("title"),
            "phrase": entry.get("phrase"),
            "video_title": entry.get("video_title"),
            "video_channel_name": entry.get("video_channel_name"),
            "youtube_id": entry.get("youtube_id"),
            "category": entry.get("category"),
            "assistant_response": (entry.get("assistant_response") or "")[:200],
        },
    }


def check_tags(tags: List[str]) -> Tuple[Set[str], Set[str]]:
    """
    Check LLM-generated English tags against the blocklist.

    Used by the post-generation validator (Layer 6) and the extended channel
    classifier (Layer 4). The tags are expected to be in English regardless
    of the content language.

    Args:
        tags: List of English classification tags from the LLM.

    Returns:
        Tuple of (blocked_tags, warning_tags). blocked_tags trigger a REJECT;
        warning_tags are logged but don't auto-reject.
    """
    keywords = _load_keywords()
    all_blocked: Set[str] = set()

    # Build a flat set of all blocked keywords for fast lookup
    for category, keyword_list in keywords.items():
        if category == "company_names":
            continue  # Company names don't apply to tag checking
        for kw in keyword_list:
            all_blocked.add(kw.lower())

    tag_set = {t.lower().strip() for t in tags}
    blocked = tag_set.intersection(all_blocked)

    # Warning tags: borderline academic content
    warning_keywords = {
        "religious-history", "religious-architecture", "comparative-religion",
        "political-analysis", "political-science", "governance",
    }
    warnings = tag_set.intersection(warning_keywords)

    return blocked, warnings


def get_all_categories() -> List[str]:
    """Return list of all available category names."""
    return list(_load_keywords().keys())


# ── Topic-level convenience functions (used by generator.py Layer 1) ─────────
# These replace the old hardcoded _is_openmates_topic, _is_sensitive_topic, and
# _is_corporate_greenwashing_topic functions with a single unified check.

# Categories to check for topic suggestion filtering
_TOPIC_FILTER_CATEGORIES = [
    "religious", "product_review", "political", "corporate_pr",
    "sensitive", "openmates",
]


def is_blocked_topic(phrase: str) -> bool:
    """
    Return True if a topic suggestion should be excluded from inspiration generation.

    Checks against all content policy categories (religious, product review,
    political, corporate PR, sensitive, OpenMates self-reference).
    """
    return is_blocked(phrase, categories=_TOPIC_FILTER_CATEGORIES)


def check_video_metadata(
    title: str,
    channel_name: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, List[str]]:
    """
    Check video metadata against the keyword blocklist (Layer 3).

    Checks video title, channel name, and description against all categories
    including company names. This runs BEFORE the LLM sees the video.

    Args:
        title: Video title from Brave/YouTube.
        channel_name: YouTube channel name (optional).
        description: Video description (optional, may not be available from Brave).

    Returns:
        Dict of violations (empty if clean).
    """
    parts = [title or ""]
    if channel_name:
        parts.append(channel_name)
    if description:
        parts.append(description)
    combined = " ".join(parts)
    return check_text(combined)
