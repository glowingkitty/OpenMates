"""Server-owned, turn-bound preprocessing decisions for internal continuations."""

from __future__ import annotations

import secrets
import hashlib
import time
from typing import Any

from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.skills.ask_skill import AskSkillRequest


PREPROCESSING_RESUME_TTL_SECONDS = 24 * 60 * 60
_KEY_PREFIX = "ai_preprocessing_resume"
_DECISION_FIELDS = frozenset({
    "can_proceed", "enable_subchats", "ai_model_topics", "harmful_or_illegal_score",
    "category", "topic_area", "topic_shift", "llm_response_temp", "complexity",
    "misuse_risk_score", "load_app_settings_and_memories", "relevant_embedded_previews",
    "icon_names", "relevant_app_skills",
    "relevant_focus_modes", "selected_mate_id", "selected_main_llm_model_id",
    "selected_main_llm_model_name", "selected_main_llm_thinking_level", "selected_secondary_model_id",
    "selected_fallback_model_id", "filtered_cn_models",
    "output_language", "requires_advice_disclaimer", "user_requested_skills_only",
    "user_requested_focus_only",
})


def _key(ref: str) -> str:
    return f"{_KEY_PREFIX}:{ref}"


def _turn_id(request: AskSkillRequest) -> str:
    return request.original_user_message_id or request.message_id


def _source_message(request: AskSkillRequest, source_index: int | None = None) -> tuple[int, str] | None:
    candidates = [
        (index, message) for index, message in enumerate(request.message_history)
        if message.role == "user" and message.sender_name != "async_tool_result"
    ]
    if source_index is not None:
        matched = next((item for item in candidates if item[0] == source_index), None)
    else:
        matched = next((item for item in reversed(candidates)
                        if item[1].message_id == _turn_id(request)), None)
        matched = matched or (candidates[-1] if candidates else None)
    source = matched[1] if matched is not None else None
    content = source.content if source is not None else request.current_user_content
    if not isinstance(content, str):
        return None
    return (
        matched[0] if matched is not None else -1,
        hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _focus_scope(request: AskSkillRequest) -> tuple[str | None, str | None, str | None]:
    project = request.active_project_focus or {}
    return (
        request.active_focus_id,
        project.get("project_id") or project.get("id"),
        project.get("activation_id"),
    )


async def store_preprocessing_resume(
    cache_service: Any, request: AskSkillRequest, result: PreprocessingResult,
) -> str | None:
    """Save only routing decisions; private rule and document bodies stay transient."""
    if (not cache_service or request.is_incognito or request.is_external or request.is_anonymous
            or not result.can_proceed or not result.selected_main_llm_model_id):
        return None
    source_message = _source_message(request)
    if not source_message:
        return None
    ref = secrets.token_urlsafe(32)
    focus_id, project_id, project_activation_id = _focus_scope(request)
    decisions = result.model_dump(mode="json", include=_DECISION_FIELDS)
    selected_apps = getattr(result, "selected_app_ids", None)
    record = {
        "version": 1,
        "user_id": request.user_id,
        "chat_id": request.chat_id,
        "turn_id": _turn_id(request),
        "source_message_index": source_message[0],
        "source_message_hash": source_message[1],
        "team_id": request.team_id,
        "is_incognito": request.is_incognito,
        "is_external": request.is_external,
        "is_anonymous": request.is_anonymous,
        "focus_id": focus_id,
        "project_id": project_id,
        "project_activation_id": project_activation_id,
        "decisions": decisions,
        "selected_app_ids": (
            [app for app in selected_apps[:64]
             if isinstance(app, str) and 0 < len(app) <= 100]
            if selected_apps is not None else None
        ),
        "selected_rules": [
            {"id": row["id"], "revision": row["revision"]}
            for row in (result.relevant_rules or [])[:24]
            if isinstance(row, dict) and isinstance(row.get("id"), str)
            and isinstance(row.get("revision"), str)
            and len(row["id"]) <= 256 and len(row["revision"]) <= 128
        ],
        "selected_workflows": [
            {"workflow_id": row["workflow_id"], "current_version_id": row["current_version_id"]}
            for row in (result.relevant_workflows or [])[:3]
            if isinstance(row, dict) and isinstance(row.get("workflow_id"), str)
            and isinstance(row.get("current_version_id"), str)
            and len(row["workflow_id"]) <= 256 and len(row["current_version_id"]) <= 128
        ],
        "stored_at": int(time.time()),
    }
    try:
        stored = await cache_service.set(_key(ref), record, ttl=PREPROCESSING_RESUME_TTL_SECONDS)
    except Exception:
        return None
    if not stored:
        return None
    return ref


async def load_preprocessing_resume(
    cache_service: Any, request: AskSkillRequest,
) -> tuple[PreprocessingResult, list[str] | None, bool] | None:
    """Load a decision only for the same current user turn and internal continuation."""
    ref = request.preprocessing_resume_ref
    if not (cache_service and isinstance(ref, str) and len(ref) >= 32):
        return None
    if not (request.is_async_skill_continuation or request.is_focus_mode_continuation
            or request.is_app_settings_memories_continuation
            or request.is_connected_account_permission_continuation
            or request.is_sub_chat_continuation):
        return None
    try:
        record = await cache_service.get(_key(ref))
    except Exception:
        return None
    if not isinstance(record, dict) or record.get("version") != 1:
        return None
    source_index = record.get("source_message_index")
    source_message = _source_message(
        request, source_index=source_index if isinstance(source_index, int) else None,
    )
    expected = {
        "user_id": request.user_id,
        "chat_id": request.chat_id,
        "turn_id": _turn_id(request),
        "source_message_index": source_message[0] if source_message else None,
        "source_message_hash": source_message[1] if source_message else None,
        "team_id": request.team_id,
        "is_incognito": request.is_incognito,
        "is_external": request.is_external,
        "is_anonymous": request.is_anonymous,
    }
    if any(record.get(key) != value for key, value in expected.items()):
        return None
    try:
        latest = await cache_service.get(
            f"async_skill_latest_user_turn:{request.user_id}:{request.chat_id}"
        )
    except Exception:
        return None
    if latest != _turn_id(request):
        return None
    decisions = record.get("decisions")
    selected_apps = record.get("selected_app_ids")
    if not isinstance(decisions, dict) or not (
        selected_apps is None or isinstance(selected_apps, list)
    ):
        return None
    if not set(decisions).issubset(_DECISION_FIELDS):
        return None
    if selected_apps is not None and any(
        not isinstance(app, str) or not app or len(app) > 100 for app in selected_apps
    ):
        return None
    try:
        result = PreprocessingResult.model_validate(decisions)
    except Exception:
        return None
    if not result.can_proceed or not result.selected_main_llm_model_id:
        return None
    result.selected_app_ids = list(selected_apps) if selected_apps is not None else None
    rules = record.get("selected_rules")
    workflows = record.get("selected_workflows")
    if isinstance(rules, list) and all(
        isinstance(row, dict) and set(row) == {"id", "revision"}
        and all(isinstance(value, str) for value in row.values()) for row in rules
    ):
        result.relevant_rules = rules
    if isinstance(workflows, list) and all(
        isinstance(row, dict) and set(row) == {"workflow_id", "current_version_id"}
        and all(isinstance(value, str) for value in row.values()) for row in workflows
    ):
        result.relevant_workflows = workflows
    old_focus_id = record.get("focus_id")
    old_project_id = record.get("project_id")
    old_project_activation_id = record.get("project_activation_id")
    new_focus_id, new_project_id, new_project_activation_id = _focus_scope(request)
    project_context_changed = (
        old_project_id != new_project_id
        or old_project_activation_id != new_project_activation_id
    ) or (
        old_focus_id != new_focus_id
        and any(
            (focus_id or "").startswith(("project-", "project-focus:"))
            for focus_id in (old_focus_id, new_focus_id)
        )
    )
    return result, selected_apps, project_context_changed
