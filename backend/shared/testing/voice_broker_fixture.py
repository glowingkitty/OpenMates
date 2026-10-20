"""Four-guard, isolated-CI voice routing fixtures; real permission/embed transport."""
from __future__ import annotations

from typing import Any

from backend.shared.testing.voice_call_fixture import isolated_voice_fixture_enabled

REQUEST = "Voice stage two fixture: apply memory and search the web"
CAMERA_SEARCH_REQUEST = "Voice camera fixture: search current frame"
CAMERA_VIDEO_REQUEST = "Voice camera fixture: animate current frame"
FAILED_REQUEST = "Voice stage two fixture: fail one tool operation"


def chat_metadata_fixture(data: dict) -> dict | None:
    """External metadata model substitute, retaining real admission and storage."""
    if not isolated_voice_fixture_enabled():
        return None
    title = data.get("current_title", "")
    users = " ".join(row["content"] for row in data["context"]["messages"] if row["role"] == "user")
    if "ramen" in users.lower():
        return {"updated_chat_title": None if "ramen" in title.lower() else "Making vegetarian ramen",
                "chat_summary": "Discussed ramen. Latest request: " + next(row["content"] for row in reversed(data["context"]["messages"]) if row["role"] == "user")[:120]}
    return {"updated_chat_title": title or "Voice conversation planning",
            "chat_summary": "Continued the conversation with the latest finalized voice requests and replies."}


def selection(data: dict, apps: dict) -> dict | None:
    """Only the exact admitted scenario bypasses paid external routing models."""
    if not isolated_voice_fixture_enabled():
        return None
    if data.get("request") in {CAMERA_SEARCH_REQUEST, CAMERA_VIDEO_REQUEST}:
        if not data.get("visual_source") or not data.get("input_embed_ids"):
            raise ValueError("Camera fixture requires an authorized saved source")
        app_id, skill_id = ("web", "search") if data["request"] == CAMERA_SEARCH_REQUEST else ("videos", "generate")
        return {"selected_app_ids": [app_id], "load_app_settings_and_memories": [],
            "relevant_focus_modes": [], "relevant_app_skills": [f"{app_id}-{skill_id}"]}
    if data.get("request") == FAILED_REQUEST:
        raise TypeError("Isolated voice tool operation failure")
    if data.get("request") != REQUEST:
        return None
    if "code" not in apps or not any(field.id == "preferred_tech" for field in apps["code"].memory_fields):
        raise RuntimeError("Fixture memory category is absent from canonical catalogue")
    return {"selected_app_ids": ["code", "web"],
            "load_app_settings_and_memories": ["code:preferred_tech"],
            "relevant_focus_modes": ["web-research"], "relevant_app_skills": ["web-search"]}


async def tool_stream(*, data: dict, **kwargs: Any):
    """Replace external argument generation, retaining real skill execution."""
    from types import SimpleNamespace
    from backend.apps.web.skills.search_fixture import E2E_WEB_FIXTURE_QUERY_TOKEN, E2E_CAMERA_SEARCH_QUERY
    if not isolated_voice_fixture_enabled() or data.get("request") not in {REQUEST, CAMERA_SEARCH_REQUEST, CAMERA_VIDEO_REQUEST}:
        raise PermissionError("Isolated voice generation fixture unavailable")
    admission = kwargs.get("pre_dispatch_admission")
    if admission is not None:
        await admission("google_ai_studio", kwargs.get("max_tokens"), tariff_snapshot=None, region=None)
    if data["request"] == CAMERA_VIDEO_REQUEST:
        yield SimpleNamespace(function_name="videos__generate", parsing_error=None,
            function_arguments_parsed={"requests": [{
                "prompt": "Animate the exact saved camera image with a gentle camera movement.",
                "input_embed_ids": list(data["input_embed_ids"])}]})
        return
    query = E2E_CAMERA_SEARCH_QUERY if data["request"] == CAMERA_SEARCH_REQUEST else E2E_WEB_FIXTURE_QUERY_TOKEN
    yield SimpleNamespace(function_name="web__search", parsing_error=None,
        function_arguments_parsed={"requests": [{"query": query, "count": 2}]})
