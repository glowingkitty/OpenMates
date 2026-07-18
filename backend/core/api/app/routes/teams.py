# backend/core/api/app/routes/teams.py
#
# Teams V1 authenticated API. The route layer is intentionally thin: Directus
# team helpers enforce membership/role checks before returning encrypted team
# records, team key wrappers, membership data, or billing-related metadata.
#
# Spec: docs/specs/teams-v1/spec.yml

import hashlib
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.services.directus.team_methods import PENDING_ACCESS_APPROVAL_STATUS, TeamPermissionError
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.team_billing_service import TeamBillingService, TeamInsufficientCreditsError
from backend.core.api.app.services.team_data_portability_service import TeamDataPortabilityError, TeamDataPortabilityService
from backend.core.api.app.services.team_invite_email_service import TeamInviteEmailService

if TYPE_CHECKING:
    from backend.core.api.app.services.directus import DirectusService


router = APIRouter(prefix="/v1/teams", tags=["Teams"])

TeamRole = Literal["owner", "admin", "member", "viewer"]
InviteRole = Literal["admin", "member", "viewer"]


class TeamCreateRequest(BaseModel):
    team_id: str = Field(min_length=1)
    slug: str | None = None
    encrypted_name: str = Field(min_length=1)
    encrypted_description: str | None = None
    encrypted_billing_profile: str | None = None
    encrypted_team_key: str = Field(min_length=1)
    encrypted_zero_balance: str | None = None
    created_at: int
    updated_at: int | None = None


class TeamUpdateRequest(BaseModel):
    slug: str | None = None
    encrypted_name: str | None = None
    encrypted_description: str | None = None
    encrypted_billing_profile: str | None = None
    updated_at: int


class TeamInviteCreateRequest(BaseModel):
    invite_id: str = Field(min_length=1)
    role: InviteRole = "member"
    recipient_email: str | None = None
    hashed_recipient_email: str | None = None
    encrypted_recipient_hint: str | None = None
    encrypted_invite_team_key: str | None = None
    invite_key_kdf_context: dict[str, Any] | None = None
    one_time_token_hash: str | None = None
    sent_at: int | None = None
    expires_at: int | None = None
    created_at: int


class TeamInviteAcceptRequest(BaseModel):
    encrypted_team_key: str | None = None
    accepted_at: int | None = None


class TeamAccessApproveRequest(BaseModel):
    encrypted_team_key: str | None = Field(default=None, min_length=1)
    approved_at: int | None = None


class TeamAccessRejectRequest(BaseModel):
    rejected_at: int | None = None


class TeamInviteDeclineRequest(BaseModel):
    declined_at: int | None = None


class TeamRoleUpdateRequest(BaseModel):
    role: InviteRole
    updated_at: int | None = None


class TeamMemberRemoveRequest(BaseModel):
    removed_at: int | None = None


class TeamCreditAddRequest(BaseModel):
    event_id: str = Field(min_length=1)
    credits: int = Field(gt=0)
    encrypted_balance: str = Field(min_length=1)
    event_type: Literal["purchase", "personal_transfer_in"] = "purchase"
    encrypted_metadata: str | None = None
    occurred_at: int | None = None


class TeamCreditChargeRequest(BaseModel):
    event_id: str = Field(min_length=1)
    credits: int = Field(gt=0)
    encrypted_balance: str = Field(min_length=1)
    workspace_type: str = Field(min_length=1)
    object_id_hash: str | None = None
    encrypted_metadata: str | None = None
    occurred_at: int | None = None


class TeamExportRequest(BaseModel):
    export_id: str | None = None
    created_at: int | None = None


class TeamImportRequest(BaseModel):
    destination_team_id: str = Field(min_length=1)
    artifact: dict[str, Any]
    imported_at: int | None = None


def get_directus_service(request: Request) -> "DirectusService":
    if not hasattr(request.app.state, "directus_service"):
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service


def get_team_billing_service(
    request: Request,
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> TeamBillingService:
    if hasattr(request.app.state, "team_billing_service"):
        return request.app.state.team_billing_service
    return TeamBillingService(directus_service)


async def _current_user(request: Request, response: Response) -> User:
    from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key

    return await get_current_user_or_api_key(
        request=request,
        response=response,
        directus_service=request.app.state.directus_service,
        cache_service=request.app.state.cache_service,
        refresh_token=request.cookies.get("auth_refresh_token"),
    )


def _handle_team_error(exc: Exception) -> None:
    if isinstance(exc, TeamPermissionError):
        raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED") from exc
    if isinstance(exc, TeamInsufficientCreditsError):
        raise HTTPException(status_code=402, detail="INSUFFICIENT_TEAM_CREDITS") from exc
    if isinstance(exc, TeamDataPortabilityError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


@router.get("")
@limiter.limit("60/minute")
async def list_teams(
    request: Request,
    response: Response,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del response
    return {"teams": await directus_service.team.list_teams(current_user.id)}


@router.post("")
@limiter.limit("20/minute")
async def create_team(
    request: Request,
    response: Response,
    body: TeamCreateRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del response
    try:
        created = await directus_service.team.create_team(current_user.id, body.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create team")
    return {"team": created}


@router.get("/{team_id}")
@limiter.limit("60/minute")
async def get_team(
    request: Request,
    response: Response,
    team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del response
    team = await directus_service.team.get_team(team_id, current_user.id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"team": team}


@router.patch("/{team_id}")
@limiter.limit("30/minute")
async def update_team(
    request: Request,
    response: Response,
    team_id: str,
    body: TeamUpdateRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del response
    try:
        updated = await directus_service.team.update_team(team_id, current_user.id, body.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not updated:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"team": updated}


@router.delete("/{team_id}")
@limiter.limit("10/minute")
async def delete_team(
    request: Request,
    response: Response,
    team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    try:
        deleted = await directus_service.team.delete_team(team_id, current_user.id)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not deleted:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"success": True}


@router.post("/{team_id}/export")
@limiter.limit("10/minute")
async def export_team_data(
    request: Request,
    response: Response,
    team_id: str,
    body: TeamExportRequest | None = None,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    try:
        return await TeamDataPortabilityService(directus_service).export_team_data(
            team_id,
            current_user.id,
            export_id=body.export_id if body else None,
            created_at=body.created_at if body else None,
        )
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)


@router.get("/{team_id}/export/{export_id}")
@limiter.limit("30/minute")
async def get_team_export(
    request: Request,
    response: Response,
    team_id: str,
    export_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    try:
        return await TeamDataPortabilityService(directus_service).get_team_export(team_id, current_user.id, export_id)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)


@router.post("/import")
@limiter.limit("10/minute")
async def import_team_data(
    request: Request,
    response: Response,
    body: TeamImportRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    try:
        return await TeamDataPortabilityService(directus_service).import_team_data(
            body.destination_team_id,
            current_user.id,
            body.artifact,
            imported_at=body.imported_at,
        )
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)


@router.post("/{team_id}/invites")
@limiter.limit("30/minute")
async def create_team_invite(
    request: Request,
    response: Response,
    team_id: str,
    body: TeamInviteCreateRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del response
    try:
        if body.recipient_email:
            domain = str(getattr(request.app.state, "public_web_url", None) or getattr(request.app.state, "public_api_url", None) or "https://openmates.org")
            email_sender = getattr(request.app.state, "team_invite_email_sender", None)
            invite = await TeamInviteEmailService(directus_service.team, email_sender=email_sender).create_email_invite(
                team_id=team_id,
                inviter_user_id=current_user.id,
                recipient_email=body.recipient_email,
                invite_id=body.invite_id,
                role=body.role,
                domain=domain,
                encrypted_recipient_hint=body.encrypted_recipient_hint,
                encrypted_invite_team_key=body.encrypted_invite_team_key,
                invite_key_kdf_context=body.invite_key_kdf_context,
                expires_at=body.expires_at,
                created_at=body.created_at,
            )
        else:
            invite = await directus_service.team.create_invite(team_id, current_user.id, body.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not invite:
        raise HTTPException(status_code=500, detail="Failed to create invite")
    return {"invite": invite}


@router.get("/invites/{invite_id}")
@limiter.limit("30/minute")
async def get_team_invite(
    request: Request,
    response: Response,
    invite_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    if not hasattr(directus_service, "get_user_fields_direct"):
        raise HTTPException(status_code=404, detail="Invite not found")
    user_fields = await directus_service.get_user_fields_direct(current_user.id, ["hashed_email"])
    invite = await directus_service.team.get_invite_for_recipient(invite_id, user_fields.get("hashed_email") if isinstance(user_fields, dict) else None)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"invite": invite}


@router.post("/invites/{invite_id}/accept")
@limiter.limit("20/minute")
async def accept_team_invite(
    request: Request,
    response: Response,
    invite_id: str,
    body: TeamInviteAcceptRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    user_fields = None
    if body.encrypted_team_key and hasattr(directus_service, "get_user_fields_direct"):
        user_fields = await directus_service.get_user_fields_direct(current_user.id, ["hashed_email"])
    if body.encrypted_team_key:
        result = await directus_service.team.accept_invite(
            invite_id,
            current_user.id,
            accepted_at=body.accepted_at,
            encrypted_team_key=body.encrypted_team_key,
            recipient_email_hash=user_fields.get("hashed_email") if isinstance(user_fields, dict) else None,
        )
    else:
        result = await directus_service.team.accept_invite(invite_id, current_user.id, accepted_at=body.accepted_at)
    if not result:
        raise HTTPException(status_code=404, detail="Invite not found")
    if result.get("membership"):
        return {"membership": result.get("membership"), "status": "accepted"}
    return {"access_request": result, "status_label": "Waiting for team access approval"}


@router.post("/invites/{invite_id}/decline")
@limiter.limit("20/minute")
async def decline_team_invite(
    request: Request,
    response: Response,
    invite_id: str,
    body: TeamInviteDeclineRequest | None = None,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response, current_user
    declined = await directus_service.team.decline_invite(invite_id, declined_at=body.declined_at if body else None)
    if not declined:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"success": True}


@router.post("/{team_id}/access-requests/{access_request_id}/approve")
@limiter.limit("20/minute")
async def approve_team_access_request(
    request: Request,
    response: Response,
    team_id: str,
    access_request_id: str,
    body: TeamAccessApproveRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    try:
        membership = await directus_service.team.approve_access_request(
            team_id,
            current_user.id,
            access_request_id,
            body.encrypted_team_key,
            approved_at=body.approved_at,
        )
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not membership:
        raise HTTPException(status_code=404, detail="Access request not found")
    return {"membership": membership}


@router.get("/{team_id}/access-requests")
@limiter.limit("30/minute")
async def list_team_access_requests(
    request: Request,
    response: Response,
    team_id: str,
    status: str | None = Query(default=PENDING_ACCESS_APPROVAL_STATUS),
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    try:
        access_requests = await directus_service.team.list_access_requests(team_id, current_user.id, status=status)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    return {"access_requests": access_requests}


@router.post("/{team_id}/access-requests/{access_request_id}/reject")
@limiter.limit("20/minute")
async def reject_team_access_request(
    request: Request,
    response: Response,
    team_id: str,
    access_request_id: str,
    body: TeamAccessRejectRequest | None = None,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    try:
        rejected = await directus_service.team.reject_access_request(
            team_id,
            current_user.id,
            access_request_id,
            rejected_at=body.rejected_at if body else None,
        )
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not rejected:
        raise HTTPException(status_code=404, detail="Access request not found")
    return {"success": True}


@router.post("/{team_id}/members/{member_user_id}/remove")
@limiter.limit("20/minute")
async def remove_team_member(
    request: Request,
    response: Response,
    team_id: str,
    member_user_id: str,
    body: TeamMemberRemoveRequest | None = None,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    try:
        removed = await directus_service.team.remove_member(team_id, current_user.id, member_user_id, removed_at=body.removed_at if body else None)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not removed:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"success": True}


@router.patch("/{team_id}/members/{member_user_id}")
@limiter.limit("20/minute")
async def update_team_member_role(
    request: Request,
    response: Response,
    team_id: str,
    member_user_id: str,
    body: TeamRoleUpdateRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    try:
        membership = await directus_service.team.set_member_role(team_id, current_user.id, member_user_id, body.role, updated_at=body.updated_at)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"membership": membership}


@router.get("/{team_id}/memories")
@limiter.limit("60/minute")
async def list_team_memories(
    request: Request,
    response: Response,
    team_id: str,
    app_id: str | None = Query(default=None),
    item_type: str | None = Query(default=None),
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del response
    try:
        await directus_service.team.require_team_role(team_id, current_user.id, {"owner", "admin", "member", "viewer"})
        filters: dict[str, Any] = {
            "hashed_team_id": {"_eq": hashlib.sha256(team_id.encode()).hexdigest()}
        }
        if app_id:
            filters["app_id"] = {"_eq": app_id}
        if item_type:
            filters["item_type"] = {"_eq": item_type}
        memories = await directus_service.get_items(
            "user_app_settings_and_memories",
            params={"filter": filters, "limit": -1, "sort": "-updated_at"},
        )
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    return {"memories": memories or []}


@router.get("/{team_id}/billing")
@limiter.limit("30/minute")
async def get_team_billing(
    request: Request,
    response: Response,
    team_id: str,
    current_user: User = Depends(_current_user),
    team_billing_service: TeamBillingService = Depends(get_team_billing_service),
) -> dict[str, Any]:
    del request, response
    try:
        billing = await team_billing_service.get_billing_summary(team_id, current_user.id)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    return {"billing": billing}


@router.post("/{team_id}/billing/credits")
@limiter.limit("20/minute")
async def add_team_credits(
    request: Request,
    response: Response,
    team_id: str,
    body: TeamCreditAddRequest,
    current_user: User = Depends(_current_user),
    team_billing_service: TeamBillingService = Depends(get_team_billing_service),
) -> dict[str, Any]:
    del request, response
    try:
        result = await team_billing_service.add_credits(
            team_id=team_id,
            actor_user_id=current_user.id,
            event_id=body.event_id,
            credits=body.credits,
            encrypted_balance=body.encrypted_balance,
            event_type=body.event_type,
            encrypted_metadata=body.encrypted_metadata,
            occurred_at=body.occurred_at,
        )
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    return {"billing": result}


@router.post("/{team_id}/billing/charge")
@limiter.limit("60/minute")
async def charge_team_credits(
    request: Request,
    response: Response,
    team_id: str,
    body: TeamCreditChargeRequest,
    current_user: User = Depends(_current_user),
    team_billing_service: TeamBillingService = Depends(get_team_billing_service),
) -> dict[str, Any]:
    del request, response
    try:
        result = await team_billing_service.charge_team_credits(
            team_id=team_id,
            actor_user_id=current_user.id,
            event_id=body.event_id,
            credits=body.credits,
            encrypted_balance=body.encrypted_balance,
            workspace_type=body.workspace_type,
            object_id_hash=body.object_id_hash,
            encrypted_metadata=body.encrypted_metadata,
            occurred_at=body.occurred_at,
        )
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    return {"charge": result}


@router.get("/{team_id}/billing/usage")
@limiter.limit("30/minute")
async def list_team_usage(
    request: Request,
    response: Response,
    team_id: str,
    member_user_id: str | None = Query(default=None),
    current_user: User = Depends(_current_user),
    team_billing_service: TeamBillingService = Depends(get_team_billing_service),
) -> dict[str, Any]:
    del request, response
    try:
        usage = await team_billing_service.list_usage(team_id, current_user.id, member_user_id=member_user_id)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    return {"usage": usage}
