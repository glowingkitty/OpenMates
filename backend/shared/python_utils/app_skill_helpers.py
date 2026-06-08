"""Shared helper imports for backend app skills.

This module gives non-AI apps an app-neutral import path for helper functions
that are currently implemented in the AI processing package. It keeps this
contract-audit cleanup behavior-preserving while the larger prompt-injection
and rate-limit helper extraction can be handled separately.

Architecture context: docs/architecture/apps/app_skills.md
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.apps.ai.processing.rate_limiting import RateLimitScheduledException as RateLimitScheduledException


def __getattr__(name: str) -> Any:
    if name == "RateLimitScheduledException":
        from backend.apps.ai.processing.rate_limiting import RateLimitScheduledException

        return RateLimitScheduledException
    raise AttributeError(name)


async def check_rate_limit(*args: Any, **kwargs: Any) -> Any:
    """Check provider rate limits without importing cache dependencies at module load."""
    from backend.apps.ai.processing.rate_limiting import check_rate_limit as _check_rate_limit

    return await _check_rate_limit(*args, **kwargs)


async def execute_skill_via_celery(*args: Any, **kwargs: Any) -> str:
    """Dispatch a skill task without importing Celery helpers at module load."""
    from backend.apps.ai.processing.celery_helpers import execute_skill_via_celery as _execute_skill_via_celery

    return await _execute_skill_via_celery(*args, **kwargs)


async def get_celery_task_status(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Read a skill task status without importing Celery helpers at module load."""
    from backend.apps.ai.processing.celery_helpers import get_celery_task_status as _get_celery_task_status

    return await _get_celery_task_status(*args, **kwargs)


async def wait_for_rate_limit(*args: Any, **kwargs: Any) -> None:
    """Wait for provider rate limits without importing cache dependencies at module load."""
    from backend.apps.ai.processing.rate_limiting import wait_for_rate_limit as _wait_for_rate_limit

    await _wait_for_rate_limit(*args, **kwargs)


async def sanitize_external_content(
    content: str,
    content_type: str = "text",
    task_id: str = "sanitization",
    secrets_manager: Optional[Any] = None,
    cache_service: Optional[Any] = None,
) -> str:
    """Sanitize external content without importing AI LLM dependencies at module load."""
    from backend.apps.ai.processing.content_sanitization import sanitize_external_content as _sanitize_external_content

    return await _sanitize_external_content(
        content=content,
        content_type=content_type,
        task_id=task_id,
        secrets_manager=secrets_manager,
        cache_service=cache_service,
    )


async def sanitize_long_text_fields_in_payload(
    payload: Any,
    task_id: str,
    secrets_manager: Optional[Any],
    cache_service: Optional[Any] = None,
    min_chars: int = 120,
    max_parallel: int = 4,
    always_sanitize_field_names: Optional[set[str]] = None,
) -> Any:
    """Sanitize nested text fields without importing AI LLM dependencies at module load."""
    from backend.apps.ai.processing.external_result_sanitizer import (
        sanitize_long_text_fields_in_payload as _sanitize_long_text_fields_in_payload,
    )

    return await _sanitize_long_text_fields_in_payload(
        payload=payload,
        task_id=task_id,
        secrets_manager=secrets_manager,
        cache_service=cache_service,
        min_chars=min_chars,
        max_parallel=max_parallel,
        always_sanitize_field_names=always_sanitize_field_names,
    )


__all__ = [
    "RateLimitScheduledException",
    "check_rate_limit",
    "execute_skill_via_celery",
    "get_celery_task_status",
    "sanitize_external_content",
    "sanitize_long_text_fields_in_payload",
    "wait_for_rate_limit",
]
