"""Authenticated Learning Mode account-policy endpoints.

Learning Mode is stored as account-wide user metadata so all clients and all
chats share the same policy. The passcode is hashed before persistence, and
deactivation attempts are counted server-side to prevent client-side bypasses.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_cache_service,
    get_current_user,
    get_directus_service,
)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.shared.python_utils.learning_mode import (
    VALID_AGE_GROUPS,
    LearningModeError,
    activate_learning_mode_policy,
    build_learning_mode_context,
    deactivate_learning_mode_policy,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/learning-mode", tags=["Learning Mode"])

LEARNING_MODE_USER_FIELDS = [
    "learning_mode_enabled",
    "learning_mode_age_group",
    "learning_mode_passcode_hash",
    "learning_mode_failed_attempts",
    "learning_mode_deactivation_blocked_until",
    "learning_mode_activated_at",
]


class LearningModeStatusResponse(BaseModel):
    enabled: bool
    age_group: Optional[str] = None
    failed_attempts: int = 0
    deactivation_blocked_until: Optional[int] = None


class LearningModeActivateRequest(BaseModel):
    passcode: str = Field(min_length=4, max_length=128)
    age_group: str


class LearningModeDeactivateRequest(BaseModel):
    passcode: str = Field(min_length=4, max_length=128)


async def _load_learning_mode_policy(
    user_id: str,
    cache_service: CacheService,
    directus_service: DirectusService,
) -> Dict[str, Any]:
    cached_user = await cache_service.get_user_by_id(user_id)
    if isinstance(cached_user, dict) and any(field in cached_user for field in LEARNING_MODE_USER_FIELDS):
        return {field: cached_user.get(field) for field in LEARNING_MODE_USER_FIELDS}

    directus_data = await directus_service.get_user_fields_direct(user_id, LEARNING_MODE_USER_FIELDS)
    if directus_data:
        await cache_service.update_user(user_id, directus_data)
        return {field: directus_data.get(field) for field in LEARNING_MODE_USER_FIELDS}
    return {"learning_mode_enabled": False, "learning_mode_failed_attempts": 0}


async def _persist_learning_mode_policy(
    user_id: str,
    update_data: Dict[str, Any],
    cache_service: CacheService,
    directus_service: DirectusService,
) -> None:
    if not await directus_service.update_user(user_id, update_data):
        raise HTTPException(status_code=500, detail="Failed to save Learning Mode settings")
    await cache_service.update_user(user_id, update_data)


def _status_from_policy(policy: Dict[str, Any]) -> LearningModeStatusResponse:
    context = build_learning_mode_context(policy)
    return LearningModeStatusResponse(
        enabled=bool(context.get("enabled")),
        age_group=context.get("age_group"),
        failed_attempts=int(policy.get("learning_mode_failed_attempts") or 0),
        deactivation_blocked_until=context.get("deactivation_blocked_until"),
    )


@router.get("", response_model=LearningModeStatusResponse, include_in_schema=False)
async def get_learning_mode_status(
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
) -> LearningModeStatusResponse:
    policy = await _load_learning_mode_policy(current_user.id, cache_service, directus_service)
    return _status_from_policy(policy)


@router.post("/activate", response_model=LearningModeStatusResponse, include_in_schema=False)
async def activate_learning_mode(
    request: Request,
    request_data: LearningModeActivateRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
) -> LearningModeStatusResponse:
    del request
    if request_data.age_group not in VALID_AGE_GROUPS:
        raise HTTPException(status_code=400, detail="Invalid age group")

    try:
        policy = activate_learning_mode_policy(
            passcode=request_data.passcode,
            age_group=request_data.age_group,
            now=int(time.time()),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _persist_learning_mode_policy(current_user.id, policy, cache_service, directus_service)
    logger.info("Learning Mode activated for user %s", current_user.id)
    return _status_from_policy(policy)


@router.post("/deactivate", response_model=LearningModeStatusResponse, include_in_schema=False)
async def deactivate_learning_mode(
    request: Request,
    request_data: LearningModeDeactivateRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
) -> LearningModeStatusResponse:
    del request
    policy = await _load_learning_mode_policy(current_user.id, cache_service, directus_service)
    try:
        updated_policy = deactivate_learning_mode_policy(
            policy,
            passcode=request_data.passcode,
            now=int(time.time()),
        )
    except LearningModeError as exc:
        await _persist_learning_mode_policy(current_user.id, exc.updated_policy, cache_service, directus_service)
        status = _status_from_policy(exc.updated_policy)
        detail = status.model_dump()
        detail["reason"] = exc.reason
        raise HTTPException(status_code=403, detail=detail) from exc

    await _persist_learning_mode_policy(current_user.id, updated_policy, cache_service, directus_service)
    logger.info("Learning Mode deactivated for user %s", current_user.id)
    return _status_from_policy(updated_policy)
