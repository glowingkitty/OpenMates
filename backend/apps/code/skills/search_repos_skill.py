# backend/apps/code/skills/search_repos_skill.py
#
# Search Repos skill implementation for the Code app.
# Searches public GitHub repositories and returns normalized repo embed payloads
# so the existing GitHub repository embed renderer can display the results.
#
# External repository names, descriptions, and topics are sanitized before they
# enter LLM context. URLs and numeric metadata are preserved for embed rendering.

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.github import search_github_repositories

logger = logging.getLogger(__name__)

DEFAULT_RESULT_COUNT = 6
MAX_RESULT_COUNT = 10


async def _sanitize_external_content(**kwargs: Any) -> str | None:
    from backend.apps.ai.processing.content_sanitization import sanitize_external_content

    return await sanitize_external_content(**kwargs)


class RepoSearchRequestItem(BaseModel):
    """A single GitHub repository search request."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests.",
    )
    query: str = Field(description="Repository search query, e.g. 'svelte markdown editor'.")
    count: int = Field(default=DEFAULT_RESULT_COUNT, description="Number of repositories to return, max 10.")


class SearchReposRequest(BaseModel):
    """Request model for repository searches."""

    requests: List[RepoSearchRequestItem] = Field(
        ...,
        description="Array of repository search requests. Each request must include a query.",
    )


class SearchReposResponse(BaseModel):
    """Response model for repository searches."""

    results: List[Dict[str, Any]] = Field(default_factory=list)
    provider: str = Field(default="GitHub")
    suggestions_follow_up_requests: Optional[List[str]] = None
    error: Optional[str] = None
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "owner_avatar_url",
            "contributors.avatar_url",
            "contributors.html_url",
            "fetched_at",
            "latest_commit_sha",
        ]
    )


class SearchReposSkill(BaseSkill):
    """Search public licensed GitHub repositories for coding tasks."""

    suggestions_follow_up_requests = [
        "Show only TypeScript repositories",
        "Find smaller starter-friendly repositories",
        "Compare the top repositories",
        "Open the most relevant repository",
    ]

    async def _sanitize_repo_results(
        self,
        repos: List[Dict[str, Any]],
        task_id: str,
        secrets_manager: Optional[SecretsManager],
    ) -> List[Dict[str, Any]]:
        if not repos:
            return []

        text_payload = [
            {
                "full_name": repo.get("full_name", ""),
                "name": repo.get("name", ""),
                "description": repo.get("description", ""),
                "topics": repo.get("topics", []),
                "primary_language": repo.get("primary_language", ""),
                "license_name": repo.get("license_name", ""),
            }
            for repo in repos
        ]
        sanitized_json = await _sanitize_external_content(
            content=json.dumps(text_payload, ensure_ascii=False),
            content_type="text",
            task_id=task_id,
            secrets_manager=secrets_manager,
        )
        if not sanitized_json or not sanitized_json.strip():
            logger.warning("[%s] Repository search results blocked by prompt-injection protection", task_id)
            return []

        try:
            sanitized_rows = json.loads(sanitized_json)
        except json.JSONDecodeError:
            logger.error("[%s] Sanitized repository search payload was not valid JSON", task_id)
            return []
        if not isinstance(sanitized_rows, list):
            return []

        cleaned: List[Dict[str, Any]] = []
        for idx, repo in enumerate(repos):
            row = sanitized_rows[idx] if idx < len(sanitized_rows) and isinstance(sanitized_rows[idx], dict) else {}
            updated = dict(repo)
            for field in ("full_name", "name", "description", "primary_language", "license_name"):
                value = row.get(field)
                if isinstance(value, str):
                    updated[field] = value.strip()

            topics = row.get("topics")
            if isinstance(topics, list):
                updated["topics"] = [topic.strip() for topic in topics if isinstance(topic, str) and topic.strip()]
            if updated.get("full_name") and updated.get("url"):
                cleaned.append(updated)
        return cleaned

    async def _process_single_repo_search_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        secrets_manager: Optional[SecretsManager] = None,
    ) -> tuple[Any, List[Dict[str, Any]], Optional[str]]:
        query = str(req.get("query", "")).strip()
        count = req.get("count", DEFAULT_RESULT_COUNT)
        try:
            count_int = max(1, min(int(count), MAX_RESULT_COUNT))
        except (TypeError, ValueError):
            count_int = DEFAULT_RESULT_COUNT

        task_id = f"github_repo_search_{request_id}"
        try:
            repos = await search_github_repositories(query=query, count=count_int)
            sanitized = await self._sanitize_repo_results(repos, task_id, secrets_manager)
            return request_id, sanitized, None
        except Exception as exc:
            logger.error("GitHub repository search failed for %r: %s", query, exc, exc_info=True)
            return request_id, [], f"Query '{query}': GitHub repository search failed"

    async def execute(
        self,
        request: SearchReposRequest,
        secrets_manager: Optional[SecretsManager] = None,
        **kwargs: Any,
    ) -> SearchReposResponse:
        """Execute one or more GitHub repository searches."""
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="SearchReposSkill",
            error_response_factory=lambda msg: SearchReposResponse(results=[], error=msg),
            logger=logger,
        )
        if error_response:
            return error_response

        requests = [item.model_dump() if hasattr(item, "model_dump") else item for item in request.requests]
        validated_requests, error = self._validate_requests_array(
            requests=requests,
            required_field="query",
            field_display_name="query",
            empty_error_message="No repository search requests provided. 'requests' must contain at least one request with a query.",
            logger=logger,
        )
        if error or not validated_requests:
            return SearchReposResponse(results=[], error=error)

        results = await self._process_requests_in_parallel(
            requests=validated_requests,
            process_single_request_func=self._process_single_repo_search_request,
            logger=logger,
            secrets_manager=secrets_manager,
        )
        grouped_results, errors = self._group_results_by_request_id(results, validated_requests, logger)
        return self._build_response_with_errors(
            response_class=SearchReposResponse,
            grouped_results=grouped_results,
            errors=errors,
            provider="GitHub",
            suggestions=self.suggestions_follow_up_requests,
            logger=logger,
        )
