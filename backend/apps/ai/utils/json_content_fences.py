"""Shared streaming dispatch for explicit assistant-authored JSON artifacts."""

from backend.apps.ai.utils.calendar_event_fences import is_calendar_event_fence
from backend.apps.ai.utils.mindmap_fences import is_mindmap_fence


def json_content_embed_type(language: str | None) -> str | None:
    if language and language.strip().lower() == "openmates_embeds":
        return "authored_results"
    if is_calendar_event_fence(language):
        return "calendar_event"
    if is_mindmap_fence(language):
        return "mindmap"
    return None


def is_json_content_fence(language: str | None) -> bool:
    return json_content_embed_type(language) is not None
