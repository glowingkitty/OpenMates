"""Four-guard, isolated-CI voice routing fixtures; real permission/embed transport."""
from __future__ import annotations

from typing import Any

from backend.shared.testing.voice_call_fixture import isolated_voice_fixture_enabled

REQUEST = "Voice stage two fixture: apply memory and search the web"


def selection(data: dict, apps: dict) -> dict | None:
    """Only the exact admitted scenario bypasses paid external routing models."""
    if not isolated_voice_fixture_enabled() or data.get("request") != REQUEST:
        return None
    if "code" not in apps or not any(field.id == "preferred_tech" for field in apps["code"].memory_fields):
        raise RuntimeError("Fixture memory category is absent from canonical catalogue")
    return {"selected_app_ids": ["code", "web"],
            "load_app_settings_and_memories": ["code:preferred_tech"],
            "relevant_focus_modes": ["web-research"], "relevant_app_skills": ["web-search"]}


async def tool_stream(*, data: dict, **kwargs: Any):
    """Replace external argument generation, retaining real skill execution."""
    from types import SimpleNamespace
    from backend.apps.web.skills.search_fixture import E2E_WEB_FIXTURE_QUERY_TOKEN
    if not isolated_voice_fixture_enabled() or data.get("request") != REQUEST:
        raise PermissionError("Isolated voice generation fixture unavailable")
    yield SimpleNamespace(function_name="web__search", parsing_error=None,
        function_arguments_parsed={"requests": [{"query": E2E_WEB_FIXTURE_QUERY_TOKEN, "count": 2}]})
