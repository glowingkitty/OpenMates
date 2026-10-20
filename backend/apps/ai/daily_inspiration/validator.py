"""Final Jev editorial review shared by video and Wikipedia inspirations."""
from typing import Any

from backend.apps.ai.daily_inspiration.decisions import review_candidates


async def validate_inspiration(
    phrase: str, title: str, assistant_response: str, video_title: str,
    channel_name: str, secrets_manager: Any, task_id: str = "daily_inspiration",
    *, source_description: str = "", follow_up_suggestions: list[str] | None = None,
    language: str = "",
) -> bool:
    reviewed = await review_candidates([{
        "title": video_title, "channel_name": channel_name,
        "description": source_description, "phrase": phrase,
        "assistant_response": assistant_response, "card_title": title,
        "follow_up_suggestions": follow_up_suggestions or [],
        **({"language": language} if language else {}),
    }], secrets_manager, task_id=task_id)
    return bool(reviewed)
