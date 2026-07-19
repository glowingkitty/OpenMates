# backend/shared/python_utils/app_skill_output_safety.py
#
# Shared app-skill output safety enforcement. This module is intentionally
# app-neutral so REST, assistant tool calls, SDK/CLI calls, and Workflow nodes
# can all use the same output-protection contract.
#
# Spec: docs/specs/app-skill-output-safety/spec.yml

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Mapping, Optional

from backend.core.api.app.utils.text_sanitization import sanitize_text_payload_for_ascii_smuggling

logger = logging.getLogger(__name__)

APP_SKILL_SURFACE_ASSISTANT = "assistant"
APP_SKILL_SURFACE_REST = "rest"
APP_SKILL_SURFACE_WORKFLOW = "workflow"

PROMPT_INJECTION_DISABLED = "disabled"
PROMPT_INJECTION_ENABLED = "enabled"

SECURITY_FIELD = "security"
PROMPT_INJECTION_PROTECTION_FIELD = "prompt_injection_protection"

OPENMATES_PROVIDER_NAME = "openmates"

ALWAYS_EXTERNAL_DATA_SKILLS: set[tuple[str, str]] = {
    ("audio", "transcribe"),
    ("code", "get_docs"),
    ("code", "search_repos"),
    ("design", "search_icons"),
    ("electronics", "search_components"),
    ("events", "search"),
    ("fitness", "search_classes"),
    ("fitness", "search_locations"),
    ("health", "search_appointments"),
    ("home", "search"),
    ("images", "search"),
    ("mail", "search"),
    ("maps", "search"),
    ("models3d", "search"),
    ("news", "search"),
    ("nutrition", "search_recipes"),
    ("pdf", "read"),
    ("pdf", "search"),
    ("shopping", "search_products"),
    ("social_media", "get-posts"),
    ("social_media", "search"),
    ("travel", "get_flight"),
    ("travel", "search_connections"),
    ("travel", "search_stays"),
    ("videos", "get_transcript"),
    ("videos", "search"),
    ("weather", "forecast"),
    ("weather", "rain_radar"),
    ("web", "read"),
    ("web", "search"),
}

ALWAYS_SEMANTIC_FIELD_NAMES: set[str] = {
    "answer",
    "author",
    "body",
    "comments",
    "content",
    "description",
    "details",
    "documentation",
    "markdown",
    "name",
    "notes",
    "review",
    "reviews",
    "snippet",
    "snippets",
    "summary",
    "text",
    "title",
    "transcript",
}


@dataclass(frozen=True)
class AppSkillOutputSafetyContext:
    app_id: str
    skill_id: str
    surface: str
    request_body: Mapping[str, Any]
    external_data: bool
    secrets_manager: Optional[Any] = None
    cache_service: Optional[Any] = None
    log_prefix: str = ""


async def sanitize_long_text_fields_in_payload(*args: Any, **kwargs: Any) -> Any:
    """Lazy bridge so tests and non-AI apps can patch/import without eager AI deps."""
    from backend.apps.ai.processing.external_result_sanitizer import (
        sanitize_long_text_fields_in_payload as _sanitize_long_text_fields_in_payload,
    )

    return await _sanitize_long_text_fields_in_payload(*args, **kwargs)


def strip_request_security_controls(request_body: Any) -> Any:
    """Remove public safety-control metadata before a skill validates input."""
    if not isinstance(request_body, dict) or SECURITY_FIELD not in request_body:
        return request_body
    stripped = dict(request_body)
    stripped.pop(SECURITY_FIELD, None)
    return stripped


def prompt_injection_protection_disabled_for_surface(
    request_body: Mapping[str, Any] | None,
    surface: str,
) -> bool:
    """Only direct REST/CLI/SDK calls can opt out of semantic scanning."""
    if surface != APP_SKILL_SURFACE_REST:
        return False
    if not isinstance(request_body, Mapping):
        return False
    security = request_body.get(SECURITY_FIELD)
    if not isinstance(security, Mapping):
        return False
    return security.get(PROMPT_INJECTION_PROTECTION_FIELD) == PROMPT_INJECTION_DISABLED


def is_external_data_skill(app_metadata: Any, app_id: str, skill_id: str) -> bool:
    """Classify whether a skill output can contain untrusted external text."""
    if (app_id, skill_id) in ALWAYS_EXTERNAL_DATA_SKILLS:
        return True
    skill = _find_skill_metadata(app_metadata, skill_id)
    if skill is None:
        return False

    explicit_external = _read_attr(skill, "external_data")
    if isinstance(explicit_external, bool):
        return explicit_external

    output_safety = _read_attr(skill, "output_safety")
    if isinstance(output_safety, Mapping) and isinstance(output_safety.get("external_data"), bool):
        return bool(output_safety["external_data"])

    providers = _read_attr(skill, "providers") or []
    for provider in providers:
        name = _provider_name(provider)
        if name and name.lower() != OPENMATES_PROVIDER_NAME:
            return True
    return False


async def sanitize_app_skill_output(
    result: Any,
    context: AppSkillOutputSafetyContext,
) -> Any:
    """Apply mandatory ASCII cleanup and default-on semantic output scanning."""
    log_prefix = context.log_prefix or f"[AppSkillOutputSafety {context.app_id}/{context.skill_id}] "
    ascii_sanitized, ascii_stats = sanitize_text_payload_for_ascii_smuggling(
        result,
        log_prefix=log_prefix,
        include_stats=True,
    )
    if ascii_stats.get("removed_count", 0) > 0:
        logger.warning(
            "%sRemoved %s ASCII-smuggling characters from app-skill output across %s field(s)",
            log_prefix,
            ascii_stats.get("removed_count", 0),
            ascii_stats.get("fields_sanitized", 0),
        )

    if not context.external_data:
        return ascii_sanitized

    if prompt_injection_protection_disabled_for_surface(context.request_body, context.surface):
        logger.warning(
            "%sPrompt-injection semantic scanning disabled by direct programmatic caller",
            log_prefix,
        )
        return ascii_sanitized

    try:
        return await sanitize_long_text_fields_in_payload(
            payload=ascii_sanitized,
            task_id=f"app_skill_output_{context.app_id}_{context.skill_id}",
            secrets_manager=context.secrets_manager,
            cache_service=context.cache_service,
            min_chars=1,
            max_parallel=4,
            always_sanitize_field_names=ALWAYS_SEMANTIC_FIELD_NAMES,
        )
    except Exception as exc:
        logger.error(
            "%sPrompt-injection protection failed for app-skill output; failing closed: %s",
            log_prefix,
            exc,
            exc_info=True,
        )
        raise RuntimeError("Prompt-injection protection failed for app-skill output") from exc


def _find_skill_metadata(app_metadata: Any, skill_id: str) -> Any:
    skills = _read_attr(app_metadata, "skills") or []
    for skill in skills:
        if _read_attr(skill, "id") == skill_id:
            return skill
    return None


def _read_attr(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _provider_name(provider: Any) -> str:
    if isinstance(provider, str):
        return provider
    value = _read_attr(provider, "name")
    return str(value) if value is not None else ""
