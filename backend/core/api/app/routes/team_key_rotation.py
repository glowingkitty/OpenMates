"""Team key rotation routes: admin context and atomic upload of the rotated key set."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.teams import _current_user, _handle_team_error
from backend.core.api.app.services.directus.team_key_rotation_methods import (
    TeamKeyRotationError,
    TeamKeyRotationMethods,
)
from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


class TeamKeyWrapperUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hashed_user_id: str = Field(min_length=1, max_length=128)
    encrypted_team_key: str = Field(min_length=1, max_length=8192)


class ProjectKeyWrapperUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hashed_project_id: str = Field(min_length=1, max_length=128)
    encrypted_project_key: str = Field(min_length=1, max_length=8192)


class TeamProfileRotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: str = Field(min_length=1, max_length=65536)
    after: str = Field(min_length=1, max_length=65536)


TeamProfileField = Literal["encrypted_name", "encrypted_description", "encrypted_profile_image_metadata"]


class TeamKeyRotationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team_key_epoch: int = Field(ge=2)
    wrappers: list[TeamKeyWrapperUpload] = Field(max_length=2000)
    project_key_wrappers: list[ProjectKeyWrapperUpload] = Field(max_length=20000)
    encrypted_previous_team_keys: str = Field(min_length=1, max_length=65536)
    profile: dict[TeamProfileField, TeamProfileRotation] = Field(max_length=3)


def _rotation(request: Request) -> TeamKeyRotationMethods:
    return TeamKeyRotationMethods(request.app.state.directus_service.team)


@router.get("/{team_id}/key-rotation")
@limiter.limit("60/minute")
async def get_team_key_rotation_context(
    request: Request, team_id: str, current_user: User = Depends(_current_user)
) -> dict[str, Any]:
    try:
        return await _rotation(request).context(team_id, current_user.id)
    except Exception as exc:  # noqa: BLE001 - converted by the Teams typed handler
        _handle_team_error(exc)
        raise


@router.post("/{team_id}/key-rotation")
@limiter.limit("10/minute")
async def upload_team_key_rotation(
    request: Request,
    team_id: str,
    body: TeamKeyRotationRequest,
    current_user: User = Depends(_current_user),
) -> dict[str, Any]:
    try:
        epoch = await _rotation(request).apply(team_id, current_user.id, body.model_dump())
    except TeamKeyRotationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - converted by the Teams typed handler
        _handle_team_error(exc)
        raise
    return {"success": True, "team_key_epoch": epoch}


class TeamKeyClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team_key_epoch: int = Field(ge=1)
    encrypted_team_key: str = Field(min_length=1, max_length=8192)


@router.put("/{team_id}/key-rotation/claim")
@limiter.limit("30/minute")
async def claim_rotated_team_key(
    request: Request,
    team_id: str,
    body: TeamKeyClaimRequest,
    current_user: User = Depends(_current_user),
) -> dict[str, Any]:
    try:
        await _rotation(request).claim(team_id, current_user.id, body.team_key_epoch, body.encrypted_team_key)
    except TeamKeyRotationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - converted by the Teams typed handler
        _handle_team_error(exc)
        raise
    return {"success": True}
