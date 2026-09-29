"""Complete bounded AI model topic classification for explicit family requests."""

from __future__ import annotations

import re
from typing import Any

FAMILIES = ("llm", "image", "video", "audio")
FAMILY_TERMS = {
    "llm": r"\b(?:llms?|language models?|text models?|gpt|claude|gemini|codex)\b",
    "image": r"\b(?:images?|pictures?|text.to.image|image.to.image)\b",
    "video": r"\b(?:videos?|text.to.video|video.to.video)\b",
    "audio": r"\b(?:audios?|speech|voice|text.to.speech|tts|transcription|music)\b",
}
MODEL_DISCUSSION = re.compile(r"\b(?:ai|artificial intelligence|language|image|video|audio)?\s*models?\b|\bllms?\b", re.I)


def complete_ai_model_topics(raw_topics: Any, latest_user_text: str | None) -> list[str]:
    """Preserve valid LLM classifications and recover families named in model questions."""
    topics = [
        topic for topic in raw_topics
        if isinstance(topic, str) and topic in FAMILIES
    ] if isinstance(raw_topics, list) else []
    if not isinstance(latest_user_text, str) or not MODEL_DISCUSSION.search(latest_user_text):
        return list(dict.fromkeys(topics))
    for family, expression in FAMILY_TERMS.items():
        if re.search(expression, latest_user_text, re.I):
            topics.append(family)
    return list(dict.fromkeys(topics))
