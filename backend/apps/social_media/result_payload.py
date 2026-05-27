# backend/apps/social_media/result_payload.py
#
# Shared plain-result serializers for Social Media async tasks.
# Chat execution stores the same normalized post dictionaries in encrypted embeds;
# REST and CLI execution return these dictionaries directly through /v1/tasks.
# Keeping the grouping logic here avoids drift between search and get-posts tasks.
#
# Architecture: docs/architecture/apps/social-media.md

from __future__ import annotations

from typing import Any, Protocol


class _PostLike(Protocol):
    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Pydantic post models expose model_dump()."""


def build_social_media_task_result(
    *,
    app_id: str,
    skill_id: str,
    result_type: str,
    status: str,
    results: list[Any],
    post_results: list[dict[str, Any]],
    request_metadata: dict[str, Any],
    elapsed_seconds: float,
    task_id: str,
    continuation_task_id: str | None = None,
    embed_id: str | None = None,
) -> dict[str, Any]:
    """Build the public Celery task result for REST/CLI and chat callers."""
    payload: dict[str, Any] = {
        "app_id": app_id,
        "skill_id": skill_id,
        "type": result_type,
        "status": status,
        "task_id": task_id,
        "results": [_serialize_group(group) for group in results],
        "items": post_results,
        "provider": request_metadata.get("provider", "Social Media"),
        "query": request_metadata.get("query"),
        "elapsed_seconds": round(elapsed_seconds, 2),
        "request_count": request_metadata.get("request_count", 0),
        "result_count": len(results),
        "post_count": len(post_results),
    }
    if embed_id:
        payload["embed_id"] = embed_id
    if continuation_task_id:
        payload["continuation_task_id"] = continuation_task_id
    return payload


def _serialize_group(group: Any) -> dict[str, Any]:
    posts = getattr(group, "posts", []) or []
    payload: dict[str, Any] = {
        "id": getattr(group, "id", None),
        "platform": getattr(group, "platform", None),
        "provider": getattr(group, "provider", None),
        "request_count": getattr(group, "request_count", 0),
        "warnings": list(getattr(group, "warnings", []) or []),
        "errors": list(getattr(group, "errors", []) or []),
        "results": [_serialize_post(post) for post in posts],
    }
    page = getattr(group, "page", None)
    query = getattr(group, "query", None)
    sort = getattr(group, "sort", None)
    if page is not None:
        payload["page"] = page
    if query is not None:
        payload["query"] = query
    if sort is not None:
        payload["sort"] = sort
    return payload


def _serialize_post(post: _PostLike | dict[str, Any]) -> dict[str, Any]:
    if hasattr(post, "model_dump"):
        return post.model_dump(mode="json")
    if isinstance(post, dict):
        return post
    return dict(post)
