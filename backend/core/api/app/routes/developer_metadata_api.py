# backend/core/api/app/routes/developer_metadata_api.py
#
# Developer-facing safe metadata endpoints for product objects whose full
# first-party APIs contain client-side encrypted payloads. These routes expose
# only owner-scoped aggregate/status metadata and never return ciphertext,
# decrypted plaintext, key wrappers, chat IDs, project IDs, or write operations.
#
# Spec: docs/specs/rest-api-security-hardening/spec.yml

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.routes.apps_api import get_session_or_api_key_info
from backend.core.api.app.services.api_key_authorization import ApiKeyAuthorizationService, ApiKeyScopeError
from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods
from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods
from backend.core.api.app.services.limiter import limiter


router = APIRouter(tags=["Developer Metadata"])

TASK_METADATA_SCOPE = "task:read_metadata"
PLAN_METADATA_SCOPE = "plan:read_metadata"


class MetadataSummaryResponse(BaseModel):
    total: int = Field(description="Number of owned records visible to the authenticated principal.")
    by_status: dict[str, int] = Field(description="Record counts grouped by non-encrypted status value.")


class UserTaskMetadataResponse(BaseModel):
    task_id: str = Field(description="Task identifier supplied by the client.")
    status: str = Field(description="Non-encrypted task status, such as todo, in_progress, blocked, or done.")
    updated_at: int | None = Field(default=None, description="Client-provided update timestamp, when available.")
    version: int | None = Field(default=None, description="Optimistic-concurrency version, when available.")


class UserPlanMetadataResponse(BaseModel):
    plan_id: str = Field(description="Plan identifier supplied by the client.")
    status: str = Field(description="Non-encrypted plan status, such as draft, active, blocked, or completed.")
    updated_at: int | None = Field(default=None, description="Client-provided update timestamp, when available.")
    version: int | None = Field(default=None, description="Optimistic-concurrency version, when available.")


def get_user_task_methods(request: Request) -> UserTaskMethods:
    return request.app.state.directus_service.user_task


def get_user_plan_methods(request: Request) -> UserPlanMethods:
    return request.app.state.directus_service.user_plan


def _require_api_key_scope(auth_info: dict[str, Any], group: str, scope: str) -> None:
    if not auth_info.get("api_key_hash"):
        return
    try:
        ApiKeyAuthorizationService().require_scope(auth_info.get("api_key_metadata") or {}, group, scope)
    except ApiKeyScopeError as exc:
        raise HTTPException(
            status_code=403,
            detail={"error": "missing_scope", "missing_scope": exc.missing_scope},
        ) from exc


@router.get(
    "/v1/user-tasks/metadata",
    response_model=MetadataSummaryResponse,
    summary="Get task status summary metadata",
    description=(
        "Returns only aggregate, non-encrypted task metadata for the authenticated "
        "user. Full task records remain official-client-only because they contain "
        "client-side encrypted fields. API keys require `task:read_metadata`."
    ),
)
@limiter.limit("60/minute")
async def get_user_task_metadata_summary(
    request: Request,
    auth_info: dict[str, Any] = Depends(get_session_or_api_key_info),
    task_methods: UserTaskMethods = Depends(get_user_task_methods),
) -> dict[str, Any]:
    _require_api_key_scope(auth_info, "tasks", TASK_METADATA_SCOPE)
    return await task_methods.summarize_task_metadata(auth_info["user_id"])


@router.get(
    "/v1/user-tasks/{task_id}/metadata",
    response_model=UserTaskMetadataResponse,
    summary="Get one task status metadata record",
    description=(
        "Returns only non-encrypted status metadata for one owned task. It never "
        "returns encrypted title, description, tags, key wrappers, chat IDs, or "
        "project IDs. API keys require `task:read_metadata`."
    ),
)
@limiter.limit("60/minute")
async def get_user_task_metadata(
    task_id: str,
    request: Request,
    auth_info: dict[str, Any] = Depends(get_session_or_api_key_info),
    task_methods: UserTaskMethods = Depends(get_user_task_methods),
) -> dict[str, Any]:
    _require_api_key_scope(auth_info, "tasks", TASK_METADATA_SCOPE)
    metadata = await task_methods.get_task_metadata(task_id, auth_info["user_id"])
    if not metadata:
        raise HTTPException(status_code=404, detail="Task not found")
    return metadata


@router.get(
    "/v1/user-plans/metadata",
    response_model=MetadataSummaryResponse,
    summary="Get plan status summary metadata",
    description=(
        "Returns only aggregate, non-encrypted plan metadata for the authenticated "
        "user. Full plan records remain official-client-only because they contain "
        "client-side encrypted fields. API keys require `plan:read_metadata`."
    ),
)
@limiter.limit("60/minute")
async def get_user_plan_metadata_summary(
    request: Request,
    auth_info: dict[str, Any] = Depends(get_session_or_api_key_info),
    plan_methods: UserPlanMethods = Depends(get_user_plan_methods),
) -> dict[str, Any]:
    _require_api_key_scope(auth_info, "plans", PLAN_METADATA_SCOPE)
    return await plan_methods.summarize_plan_metadata(auth_info["user_id"])


@router.get(
    "/v1/user-plans/{plan_id}/metadata",
    response_model=UserPlanMetadataResponse,
    summary="Get one plan status metadata record",
    description=(
        "Returns only non-encrypted status metadata for one owned plan. It never "
        "returns encrypted title, summary, goals, assumptions, risks, context, "
        "key wrappers, chat IDs, or project IDs. API keys require `plan:read_metadata`."
    ),
)
@limiter.limit("60/minute")
async def get_user_plan_metadata(
    plan_id: str,
    request: Request,
    auth_info: dict[str, Any] = Depends(get_session_or_api_key_info),
    plan_methods: UserPlanMethods = Depends(get_user_plan_methods),
) -> dict[str, Any]:
    _require_api_key_scope(auth_info, "plans", PLAN_METADATA_SCOPE)
    metadata = await plan_methods.get_plan_metadata(plan_id, auth_info["user_id"])
    if not metadata:
        raise HTTPException(status_code=404, detail="Plan not found")
    return metadata
