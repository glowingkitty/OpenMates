"""Fail-closed eligibility for anonymous app-skill execution.

The app metadata declares the positive allowlist. These exclusions protect the
anonymous boundary if an app is accidentally classified as inline later.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from backend.shared.python_utils.connected_account_registry import is_connected_account_skill


ACCOUNT_STATE_APPS = frozenset({
    "calendar", "finance", "mail", "plans", "projects", "reminder", "tasks", "workflows",
})
BACKGROUND_OR_FILE_SKILLS = frozenset({
    ("audio", "generate"), ("audio", "speak"), ("audio", "transcribe"),
    ("code", "run"), ("code", "image_to_html"),
    ("images", "generate"), ("images", "generate_draft"), ("images", "vectorize"),
    ("models3d", "generate"), ("music", "generate"),
    ("social_media", "search"), ("social_media", "get-posts"),
    ("videos", "generate"), ("videos", "create"),
    ("videos", "get_transcript"),
    ("weather", "rain_radar"),
    ("web", "read"),
})


def _field(skill: Any, name: str) -> Any:
    return skill.get(name) if isinstance(skill, dict) else getattr(skill, name, None)


def is_anonymous_inline_skill(app_id: str, skill: Any) -> bool:
    """True only for an explicitly reviewed, account-free inline skill."""
    skill_id = _field(skill, "id")
    if not isinstance(skill_id, str) or _field(skill, "anonymous_access") != "inline":
        return False
    if _field(skill, "internal") is True:
        return False
    if app_id in ACCOUNT_STATE_APPS or (app_id, skill_id) in BACKGROUND_OR_FILE_SKILLS:
        return False
    if is_connected_account_skill(app_id, skill_id):
        return False
    api_config = _field(skill, "api_config")
    if api_config is not None and _field(api_config, "expose_post") is False:
        return False
    return True


def filter_anonymous_tools(
    tools: list[dict[str, Any]],
    apps_metadata: Mapping[str, Any],
    canonicalize: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Remove non-inline app and system tools before anonymous inference."""
    allowed = {
        canonicalize(f"{app_id}-{_field(skill, 'id')}")
        for app_id, app_metadata in apps_metadata.items()
        for skill in (_field(app_metadata, "skills") or [])
        if is_anonymous_inline_skill(app_id, skill)
    }
    return [
        tool for tool in tools
        if canonicalize(str(tool.get("function", {}).get("name") or "")) in allowed
    ]
