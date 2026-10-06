# backend/core/api/app/routes/teams.py
#
# Teams V1 first-party API (session or approved device auth through _current_user).
# Caddy forwards /v1/teams/*; Team membership and role checks scope every
# private Team record. The route layer is intentionally thin: Directus
# team helpers enforce membership/role checks before returning encrypted team
# records, team key wrappers, membership data, or billing-related metadata.
#
# Spec: docs/specs/teams-v1/spec.yml

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import io
import logging
import os
import re
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field
import yaml

from backend.core.api.app.models.user import User
from backend.core.api.app.services.directus.team_methods import PENDING_ACCESS_APPROVAL_STATUS, TeamPermissionError, hash_id
from backend.core.api.app.services.feature_availability_guards import ensure_teams_enabled
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.project_remote_access_service import ProjectRemoteAccessService
from backend.core.api.app.services.team_billing_service import TEAM_BILLING_ROLES, TeamBillingService, TeamInsufficientCreditsError
from backend.core.api.app.services.billing_profile_service import BillingProfileService
from backend.core.api.app.schemas.billing_address import BuyerAddress, BuyerAddressRequest
from backend.core.api.app.services.team_data_portability_service import TeamDataPortabilityError, TeamDataPortabilityService
from backend.core.api.app.services.team_invite_email_service import TeamInviteEmailService
from backend.core.api.app.services.team_invite_email_service import hash_invite_email
from backend.core.api.app.services.team_name_validation import consume_name_approval, issue_name_approval, validate_team_name
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.services.storage_usage_metering import StorageUsageIncompleteError, StorageUsageMeteringService
from backend.core.api.app.services.sub_chat_orchestration_service import SubChatOrchestrationService
from backend.core.api.app.utils.bank_transfer_references import generate_bank_transfer_reference

if TYPE_CHECKING:
    from backend.core.api.app.services.directus import DirectusService


router = APIRouter(prefix="/v1/teams", tags=["Teams"], dependencies=[Depends(ensure_teams_enabled)])
logger = logging.getLogger(__name__)

TeamRole = Literal["owner", "admin", "member", "viewer"]
InviteRole = Literal["admin", "member", "viewer"]
TEAM_BANK_TRANSFER_ORDER_TYPE = "team_credit_purchase"
CLIENT_AES_GCM_IV_BYTES = 12
CLIENT_AES_GCM_TAG_BYTES = 16
CLIENT_CIPHERTEXT_HEADER_BYTES = 6
TEAM_ENCRYPTED_FIELDS = {
    "encrypted_name",
    "encrypted_description",
    "encrypted_profile_image_metadata",
    "encrypted_billing_profile",
    "encrypted_balance",
    "encrypted_metadata",
    "encrypted_team_key",
    "encrypted_zero_balance",
    "encrypted_recipient_hint",
    "encrypted_invite_team_key",
    "encrypted_member_profile",
}
PRICING_CONFIG_PATH = Path("/shared/config/pricing.yml")


def get_price_for_credits(credits_amount: int, currency: str) -> int | None:
    try:
        pricing_data = yaml.safe_load(PRICING_CONFIG_PATH.read_text()) or {}
    except Exception:
        return None
    for tier in pricing_data.get("pricingTiers", []):
        if tier.get("credits") == credits_amount:
            price = (tier.get("price") or {}).get(currency.lower())
            return int(price) if price is not None else None
    return None


def get_team_monthly_tier(credits_amount: int, currency: str) -> dict[str, int] | None:
    try:
        pricing_data = yaml.safe_load(PRICING_CONFIG_PATH.read_text()) or {}
    except Exception:
        return None
    for tier in pricing_data.get("pricingTiers", []):
        if tier.get("credits") == credits_amount and (tier.get("price") or {}).get(currency.lower()) is not None:
            bonus = int(tier.get("monthly_auto_top_up_extra_credits") or 0)
            if bonus > 0:
                return {"price": int(tier["price"][currency.lower()]), "bonus_credits": bonus}
    return None


class TeamCreateRequest(BaseModel):
    team_id: str = Field(min_length=1)
    slug: str | None = None
    encrypted_name: str = Field(min_length=1)
    name_approval_token: str = Field(min_length=1)
    encrypted_description: str | None = None
    encrypted_profile_image_metadata: str = Field(min_length=1)
    encrypted_billing_profile: str | None = None
    encrypted_team_key: str = Field(min_length=1)
    encrypted_member_profile: str | None = None
    encrypted_zero_balance: str | None = None
    created_at: int
    updated_at: int | None = None


class TeamUpdateRequest(BaseModel):
    slug: str | None = None
    encrypted_name: str | None = None
    name_approval_token: str | None = None
    encrypted_description: str | None = None
    encrypted_profile_image_metadata: str | None = None
    encrypted_billing_profile: str | None = None
    updated_at: int


class TeamInviteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invite_id: str = Field(min_length=1)
    role: InviteRole = "member"
    recipient_email: str | None = None
    encrypted_recipient_hint: str | None = None
    encrypted_invite_team_key: str | None = None
    invite_key_kdf_context: dict[str, Any] | None = None
    expires_at: int | None = None
    created_at: int


class TeamInviteAcceptRequest(BaseModel):
    encrypted_team_key: str | None = None
    encrypted_member_profile: str | None = None
    verified_email: str = Field(min_length=3)
    accepted_at: int | None = None


class TeamInvitePreviewRequest(BaseModel):
    verified_email: str = Field(min_length=3)


class TeamNameApprovalRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TeamSecurityPolicyRequest(BaseModel):
    restrict_email_domains: bool = False
    allowed_email_domains: list[str] = Field(default_factory=list, max_length=50)
    require_invite_link_approval: bool = True
    require_strong_auth: bool = False


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


class TeamMemberProfileUpdateRequest(BaseModel):
    encrypted_member_profile: str = Field(min_length=1)


class CreateBankTransferOrderRequest(BaseModel):
    credits_amount: int
    currency: str = "eur"
    email_encryption_key: str
    is_signup: bool = False
    is_gift_card: bool = False
    buyer_address: BuyerAddress | None = None


class CreateBankTransferOrderResponse(BaseModel):
    order_id: str
    reference: str
    iban: str
    bic: str
    bank_name: str
    account_holder_name: str
    account_holder_address_line1: str = ""
    account_holder_address_line2: str = ""
    account_holder_postal_code: str = ""
    account_holder_city: str = ""
    account_holder_country: str = ""
    amount_eur: str
    credits_amount: int
    expires_at: str


class BankTransferStatusResponse(BaseModel):
    order_id: str
    status: str
    credits_amount: int
    amount_eur: str
    reference: str
    expires_at: str
    created_at: str


class PendingBankTransferSummary(BaseModel):
    order_id: str
    credits_amount: int
    amount_eur: str
    reference: str
    status: str
    expires_at: str


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


def get_cache_service(request: Request) -> Any:
    if not hasattr(request.app.state, "cache_service"):
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.cache_service


def get_encryption_service(request: Request) -> Any:
    if not hasattr(request.app.state, "encryption_service"):
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.encryption_service


def get_s3_service(request: Request) -> Any:
    if not hasattr(request.app.state, "s3_service"):
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.s3_service


def get_payment_service(request: Request) -> Any:
    from backend.core.api.app.utils.server_mode import is_cloud_billing_enabled

    if not is_cloud_billing_enabled():
        raise HTTPException(status_code=404, detail="Feature not available on this server edition")
    payment_service = getattr(request.app.state, "payment_service", None)
    if payment_service is None:
        raise HTTPException(status_code=503, detail="Payment service unavailable")
    return payment_service


def get_lifecycle_payment_service(request: Request) -> Any | None:
    """Lifecycle remains available when this server has no cloud billing."""
    return getattr(request.app.state, "payment_service", None)


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


def _queue_team_membership_email(user_id: str, team_id: str, change: str) -> None:
    try:
        from backend.core.api.app.tasks.email_tasks.team_membership_change_email_task import send_team_membership_change_email
        send_team_membership_change_email.delay(user_id, team_id, change)
    except Exception:
        logger.exception("Could not queue Team membership notification for user %s", user_id[:8])


def _is_client_aes_gcm_ciphertext(value: str) -> bool:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:
        return False
    if len(raw) >= CLIENT_CIPHERTEXT_HEADER_BYTES + CLIENT_AES_GCM_IV_BYTES + CLIENT_AES_GCM_TAG_BYTES + 1 and raw[:2] == b"OM":
        return True
    return len(raw) >= CLIENT_AES_GCM_IV_BYTES + CLIENT_AES_GCM_TAG_BYTES + 1


def _reject_cleartext_team_payload(payload: dict[str, Any]) -> None:
    invalid = sorted(
        field
        for field in TEAM_ENCRYPTED_FIELDS
        if isinstance(payload.get(field), str) and not _is_client_aes_gcm_ciphertext(payload[field])
    )
    if invalid:
        raise HTTPException(status_code=422, detail={"error": "team_cleartext_rejected", "fields": invalid})


def _email_domain(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
        raise HTTPException(status_code=422, detail="TEAM_VALID_EMAIL_REQUIRED")
    return normalized.rsplit("@", 1)[1]


def _validate_invite_kdf_context(context: dict[str, Any], *, team_id: str, invite_id: str) -> None:
    expected = {"v", "kdf", "cipher", "team_id", "invite_id", "origin"}
    if set(context) != expected or context.get("v") != 1 or context.get("kdf") != "HKDF-SHA256" or context.get("cipher") != "AES-256-GCM":
        raise HTTPException(status_code=422, detail="TEAM_INVITE_KDF_INVALID")
    if context.get("team_id") != team_id or context.get("invite_id") != invite_id or not isinstance(context.get("origin"), str) or len(context["origin"]) > 256 or not context["origin"].startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail="TEAM_INVITE_KDF_INVALID")


def _team_bank_transfer_response(order: dict[str, Any], bank_details: dict[str, str], price_cents: int) -> CreateBankTransferOrderResponse:
    return CreateBankTransferOrderResponse(
        order_id=order["order_id"],
        reference=order["reference"],
        iban=bank_details["iban"],
        bic=bank_details["bic"],
        bank_name=bank_details["bank_name"],
        account_holder_name=bank_details.get("account_holder_name", ""),
        account_holder_address_line1=bank_details.get("account_holder_address_line1", ""),
        account_holder_address_line2=bank_details.get("account_holder_address_line2", ""),
        account_holder_postal_code=bank_details.get("account_holder_postal_code", ""),
        account_holder_city=bank_details.get("account_holder_city", ""),
        account_holder_country=bank_details.get("account_holder_country", ""),
        amount_eur=f"{price_cents / 100:.2f}",
        credits_amount=int(order["credits_amount"]),
        expires_at=order.get("expires_at", ""),
    )


def _team_bank_transfer_status(order: dict[str, Any]) -> BankTransferStatusResponse:
    amount_cents = int(order.get("amount_expected_cents") or 0)
    return BankTransferStatusResponse(
        order_id=order.get("order_id", ""),
        status=order.get("status", "pending"),
        credits_amount=int(order.get("credits_amount") or 0),
        amount_eur=f"{amount_cents / 100:.2f}",
        reference=order.get("reference", ""),
        expires_at=order.get("expires_at", ""),
        created_at=order.get("created_at", ""),
    )


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


@router.post("/name-approval")
@limiter.limit("20/minute")
async def approve_team_name(
    request: Request,
    response: Response,
    body: TeamNameApprovalRequest,
    current_user: User = Depends(_current_user),
) -> dict[str, Any]:
    del response
    domain_security = getattr(request.app.state, "domain_security_service", None)
    if not domain_security or not validate_team_name(body.name, domain_security):
        raise HTTPException(status_code=422, detail="TEAM_NAME_BLOCKED")
    token, expires_at = await issue_name_approval(request.app.state.cache_service, current_user.id)
    return {"approval_token": token, "expires_at": expires_at}


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
    _reject_cleartext_team_payload(body.model_dump(exclude_none=True))
    if not await consume_name_approval(request.app.state.cache_service, current_user.id, body.name_approval_token):
        raise HTTPException(status_code=422, detail="TEAM_NAME_APPROVAL_REQUIRED")
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
    _reject_cleartext_team_payload(body.model_dump(exclude_none=True))
    if body.encrypted_name and not await consume_name_approval(request.app.state.cache_service, current_user.id, body.name_approval_token):
        raise HTTPException(status_code=422, detail="TEAM_NAME_APPROVAL_REQUIRED")
    try:
        updated = await directus_service.team.update_team(team_id, current_user.id, body.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not updated:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"team": updated}


@router.get("/{team_id}/security")
@limiter.limit("30/minute")
async def get_team_security(
    request: Request, response: Response, team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    team = await directus_service.team.get_team(team_id, current_user.id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"security_policy": team.get("security_policy") or {}}


@router.patch("/{team_id}/security")
@limiter.limit("20/minute")
async def update_team_security(
    request: Request, response: Response, team_id: str, body: TeamSecurityPolicyRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    try:
        policy = await directus_service.team.update_security_policy(team_id, current_user.id, body.model_dump(exclude_unset=True))
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if policy is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"security_policy": policy}


@router.get("/{team_id}/profile-image")
@limiter.limit("120/minute")
async def get_team_profile_image(
    request: Request,
    response: Response,
    team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
    s3_service: Any = Depends(get_s3_service),
) -> StreamingResponse:
    del request, response
    try:
        image_record = await directus_service.team.get_team_profile_image_private_record(team_id, current_user.id)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not image_record or not image_record.get("profile_image_s3_key"):
        raise HTTPException(status_code=404, detail="Team profile image not found")
    wrapped_aes_key = image_record.get("encrypted_profile_image_aes_key")
    nonce_b64 = image_record.get("profile_image_aes_nonce")
    vault_key_id = image_record.get("profile_image_vault_key_id")
    if not wrapped_aes_key or not nonce_b64 or not vault_key_id:
        raise HTTPException(status_code=500, detail="Team profile image encryption data incomplete")

    aes_key_b64 = await encryption_service.decrypt_with_user_key(wrapped_aes_key, vault_key_id)
    if not aes_key_b64:
        raise HTTPException(status_code=500, detail="Failed to unwrap team profile image key")
    bucket_name = get_bucket_name("profile_images_private", os.getenv("SERVER_ENVIRONMENT", "development"))
    encrypted_data = await s3_service.get_file(bucket_name=bucket_name, object_key=image_record["profile_image_s3_key"])
    if not encrypted_data:
        raise HTTPException(status_code=404, detail="Team profile image not found in storage")
    try:
        aesgcm = AESGCM(base64.b64decode(aes_key_b64))
        image_bytes = aesgcm.decrypt(base64.b64decode(nonce_b64), encrypted_data, None)
    except Exception as exc:  # noqa: BLE001 - avoid leaking crypto details
        raise HTTPException(status_code=500, detail="Failed to decrypt team profile image") from exc
    media_type = "image/png" if image_bytes.startswith(b"\x89PNG\r\n\x1a\n") else (
        "image/webp" if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP" else "image/jpeg"
    )
    return StreamingResponse(
        io.BytesIO(image_bytes),
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )


async def _stop_team_recurring_billing(
    directus_service: Any, encryption_service: Any, payment_service: Any,
    team_id: str, *, departing_payer_id: str | None = None,
) -> None:
    profiles = BillingProfileService(directus_service, encryption_service)
    profile = await profiles.get_profile("team", team_id)
    if not profile:
        return
    stop_monthly = departing_payer_id is None or profile.get("monthly_payer_user_id") == departing_payer_id
    stop_low_balance = departing_payer_id is None or profile.get("auto_topup_payer_user_id") == departing_payer_id
    changes: dict[str, Any] = {}
    subscription_id = profile.get("monthly_subscription_id")
    if stop_monthly and subscription_id and profile.get("monthly_subscription_status") != "canceled":
        if payment_service is None or getattr(payment_service, "_stripe_provider", None) is None:
            raise HTTPException(status_code=503, detail="Team subscription cancellation unavailable")
        canceled = await payment_service._stripe_provider.cancel_subscription(subscription_id)
        if not canceled:
            raise HTTPException(status_code=502, detail="Team subscription cancellation failed")
        changes["monthly_subscription_status"] = "canceled"
    if stop_low_balance:
        changes.update({
            "auto_topup_enabled": False,
            "encrypted_auto_topup_payment_method": None,
            "encrypted_auto_topup_email": None,
        })
    if changes:
        await profiles.update_profile("team", team_id, changes)


@router.delete("/{team_id}")
@limiter.limit("10/minute")
async def delete_team(
    request: Request,
    response: Response,
    team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
    payment_service: Any = Depends(get_lifecycle_payment_service),
) -> dict[str, Any]:
    del response
    try:
        await directus_service.team.require_team_role(team_id, current_user.id, {"owner"})
        await _stop_team_recurring_billing(directus_service, encryption_service, payment_service, team_id)
        await ProjectRemoteAccessService(request.app.state.cache_service).revoke_team(team_id=team_id)
        await directus_service.project.mark_team_sources_offline(
            team_id,
            updated_at=int(time.time()),
        )
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
    del response
    try:
        return await TeamDataPortabilityService(
            directus_service, s3_service=getattr(request.app.state, "s3_service", None),
        ).export_team_data(
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


@router.get("/{team_id}/members")
@limiter.limit("30/minute")
async def list_team_members(
    request: Request, response: Response, team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        members = await directus_service.team.list_members(team_id, current_user.id)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    return {"members": [_member_response(team_id, member) for member in members]}


def _member_response(team_id: str, member: dict[str, Any]) -> dict[str, Any]:
    result = dict(member)
    if member.get("user_id"):
        result["profile_image_url"] = f"/v1/teams/{team_id}/members/{member['user_id']}/profile-image"
    return result


@router.get("/{team_id}/members/{member_user_id}")
@limiter.limit("30/minute")
async def get_team_member(
    request: Request, response: Response, team_id: str, member_user_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        members = await directus_service.team.list_members(team_id, current_user.id)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    member = next((row for row in members if row.get("user_id") == member_user_id or row.get("hashed_user_id") == member_user_id), None)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"member": _member_response(team_id, member)}


@router.patch("/{team_id}/members/me/profile")
@limiter.limit("20/minute")
async def update_own_team_member_profile(
    request: Request, response: Response, team_id: str, body: TeamMemberProfileUpdateRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    _reject_cleartext_team_payload(body.model_dump())
    try:
        member = await directus_service.team.update_own_member_profile(team_id, current_user.id, body.encrypted_member_profile)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"member": member}


@router.get("/{team_id}/members/{member_user_id}/profile-image")
@limiter.limit("120/minute")
async def get_team_member_profile_image(
    request: Request, response: Response, team_id: str, member_user_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
    s3_service: Any = Depends(get_s3_service),
) -> StreamingResponse:
    del response
    try:
        await directus_service.team.require_team_role(team_id, current_user.id, {"owner", "admin", "member", "viewer"})
        target = await directus_service.team.get_membership(team_id, member_user_id)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")
    from backend.core.api.app.routes.profile_api import get_profile_image

    image = await get_profile_image.__wrapped__(
        user_id=member_user_id, request=request, current_user=current_user,
        directus_service=directus_service, encryption_service=encryption_service, s3_service=s3_service,
    )
    image.headers["Cache-Control"] = "private, no-store"
    return image


@router.get("/{team_id}/invites")
@limiter.limit("30/minute")
async def list_team_invites(
    request: Request, response: Response, team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    try:
        invites = await directus_service.team.list_invites(team_id, current_user.id)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    return {"invites": invites}


@router.post("/{team_id}/invites/{invite_id}/revoke")
@limiter.limit("20/minute")
async def revoke_team_invite(
    request: Request, response: Response, team_id: str, invite_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    try:
        revoked = await directus_service.team.revoke_invite(team_id, current_user.id, invite_id)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not revoked:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"success": True}


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
    _reject_cleartext_team_payload(body.model_dump(exclude_none=True))
    try:
        if not body.encrypted_invite_team_key or not body.invite_key_kdf_context:
            raise HTTPException(status_code=422, detail="TEAM_INVITE_KEY_REQUIRED")
        _validate_invite_kdf_context(body.invite_key_kdf_context, team_id=team_id, invite_id=body.invite_id)
        team = await directus_service.team.get_team(team_id, current_user.id)
        if not team or team.get("role") not in {"owner", "admin"}:
            raise TeamPermissionError("Team permission denied")
        policy = team.get("security_policy") or {}
        if body.recipient_email and policy.get("restrict_email_domains"):
            allowed = policy.get("allowed_email_domains") or []
            recipient_domain = _email_domain(body.recipient_email)
            if recipient_domain not in allowed:
                raise ValueError("TEAM_EMAIL_DOMAIN_NOT_ALLOWED")
        elif body.recipient_email:
            _email_domain(body.recipient_email)
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
    policy = await directus_service.team.get_security_policy_by_hash(invite["hashed_team_id"])
    if not policy or policy["restrict_email_domains"] or policy["require_strong_auth"]:
        raise HTTPException(status_code=409, detail="TEAM_INVITE_PREVIEW_REQUIRED")
    return {"invite": invite}


@router.post("/invites/{invite_id}/preview")
@limiter.limit("30/minute")
async def preview_team_invite(
    request: Request, response: Response, invite_id: str, body: TeamInvitePreviewRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    del request, response
    user_fields = await directus_service.get_user_fields_direct(current_user.id, ["hashed_email", "encrypted_tfa_secret"], no_cache=True)
    verified_domain = _email_domain(body.verified_email)
    raw_hash = base64.b64encode(hashlib.sha256(body.verified_email.encode()).digest()).decode("ascii")
    normalized_hash = hash_invite_email(body.verified_email)
    # Signup verifies the email before storing hashed_email. signup_completed tracks
    # later onboarding and can still be false for an already verified account.
    if not isinstance(user_fields, dict) or user_fields.get("hashed_email") not in {raw_hash, normalized_hash}:
        raise HTTPException(status_code=403, detail="TEAM_VERIFIED_EMAIL_REQUIRED")
    invite = await directus_service.team.get_invite_for_recipient(invite_id, normalized_hash)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    policy = await directus_service.team.get_security_policy_by_hash(invite["hashed_team_id"])
    if not policy:
        raise HTTPException(status_code=404, detail="Invite not found")
    if policy["restrict_email_domains"] and verified_domain not in policy["allowed_email_domains"]:
        raise HTTPException(status_code=403, detail="TEAM_EMAIL_DOMAIN_NOT_ALLOWED")
    if policy["require_strong_auth"] and not user_fields.get("encrypted_tfa_secret"):
        passkeys = await directus_service.get_items(
            "user_passkeys", params={"filter[user_id][_eq]": current_user.id, "fields": "id", "limit": 1},
            no_cache=True, admin_required=True,
        )
        if not isinstance(passkeys, list) or not passkeys:
            raise HTTPException(status_code=403, detail="TEAM_STRONG_AUTH_REQUIRED")
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
    del response
    _reject_cleartext_team_payload(body.model_dump(exclude_none=True))
    if not body.encrypted_team_key:
        raise HTTPException(status_code=422, detail="TEAM_KEY_WRAPPER_REQUIRED")
    try:
        user_fields = await directus_service.get_user_fields_direct(
            current_user.id, ["hashed_email", "encrypted_tfa_secret"], no_cache=True,
        )
        verified_domain = _email_domain(body.verified_email)
        raw_email_hash = base64.b64encode(hashlib.sha256(body.verified_email.encode()).digest()).decode("ascii")
        normalized_email_hash = hash_invite_email(body.verified_email)
        if not isinstance(user_fields, dict) or user_fields.get("hashed_email") not in {raw_email_hash, normalized_email_hash}:
            raise HTTPException(status_code=403, detail="TEAM_VERIFIED_EMAIL_REQUIRED")
        invite = await directus_service.team.get_invite_join_context(invite_id)
        if not invite or (invite.get("expires_at") and int(invite["expires_at"]) <= time.time()):
            raise HTTPException(status_code=404, detail="Invite not found")
        if invite.get("hashed_recipient_email") and invite["hashed_recipient_email"] != normalized_email_hash:
            raise HTTPException(status_code=404, detail="Invite not found")
        policy = await directus_service.team.get_security_policy_by_hash(invite["hashed_team_id"])
        if policy is None:
            raise HTTPException(status_code=404, detail="Invite not found")
        if policy["restrict_email_domains"]:
            if verified_domain not in policy["allowed_email_domains"]:
                raise HTTPException(status_code=403, detail="TEAM_EMAIL_DOMAIN_NOT_ALLOWED")
        if policy["require_strong_auth"] and not user_fields.get("encrypted_tfa_secret"):
            passkeys = await directus_service.get_items(
                "user_passkeys", params={"filter[user_id][_eq]": current_user.id, "fields": "id", "limit": 1},
                no_cache=True, admin_required=True,
            )
            if not isinstance(passkeys, list) or not passkeys:
                raise HTTPException(status_code=403, detail="TEAM_STRONG_AUTH_REQUIRED")
        result = await directus_service.team.accept_invite(
            invite_id, current_user.id, accepted_at=body.accepted_at,
            encrypted_team_key=body.encrypted_team_key,
            encrypted_member_profile=body.encrypted_member_profile,
            recipient_email_hash=normalized_email_hash,
            verified_email_domain=verified_domain,
            require_approval=bool(policy["require_invite_link_approval"]),
        )
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
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
    del request, response
    user_fields = await directus_service.get_user_fields_direct(current_user.id, ["hashed_email"], no_cache=True)
    declined = await directus_service.team.decline_invite(
        invite_id,
        user_fields.get("hashed_email") if isinstance(user_fields, dict) else None,
        declined_at=body.declined_at if body else None,
    )
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
    _reject_cleartext_team_payload(body.model_dump(exclude_none=True))
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
    encryption_service: Any = Depends(get_encryption_service),
    payment_service: Any = Depends(get_lifecycle_payment_service),
) -> dict[str, Any]:
    del response
    try:
        removable = await directus_service.team.prepare_member_removal(
            team_id, current_user.id, member_user_id
        )
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not removable:
        raise HTTPException(status_code=404, detail="Member not found")
    await _stop_team_recurring_billing(
        directus_service, encryption_service, payment_service, team_id,
        departing_payer_id=member_user_id,
    )
    removed_at = int(body.removed_at if body and body.removed_at else time.time())
    await directus_service.team.deactivate_member(removable, removed_at=removed_at)
    await ProjectRemoteAccessService(request.app.state.cache_service).revoke_member(
        team_id=team_id,
        member_user_id=member_user_id,
    )
    await directus_service.project.mark_team_member_sources_offline(
        team_id,
        member_user_id,
        updated_at=int(time.time()),
    )
    try:
        await directus_service.team.revoke_member_key_wrappers(
            team_id,
            member_user_id,
            revoked_at=removed_at,
        )
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    _queue_team_membership_email(member_user_id, team_id, "removed")
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
    encryption_service: Any = Depends(get_encryption_service),
    payment_service: Any = Depends(get_lifecycle_payment_service),
) -> dict[str, Any]:
    del request, response
    try:
        if body.role not in {"owner", "admin"}:
            await directus_service.team.require_team_role(team_id, current_user.id, {"owner", "admin"})
            target = await directus_service.team.get_membership(team_id, member_user_id)
            if target and target.get("role") != "owner":
                await _stop_team_recurring_billing(
                    directus_service, encryption_service, payment_service, team_id,
                    departing_payer_id=member_user_id,
                )
        membership = await directus_service.team.set_member_role(team_id, current_user.id, member_user_id, body.role, updated_at=body.updated_at)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")
    _queue_team_membership_email(member_user_id, team_id, "role_changed")
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


@router.get("/{team_id}/storage")
@limiter.limit("30/minute")
async def get_team_storage_overview(
    request: Request,
    response: Response,
    team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    """First-party/approved CLI and SDK Team storage metadata.

    Session/API-key authentication and current owner/admin membership are
    required. Caddy forwards /v1/teams/*; FastAPI enforces this role gate.
    This read-only, 30/minute surface does not charge credits or expose objects.
    """
    del request, response
    try:
        await directus_service.team.require_team_role(team_id, current_user.id, TEAM_BILLING_ROLES)
        team_hash = hash_id(team_id)
        quote = (await StorageUsageMeteringService(directus_service).quote_team([team_hash]))[team_hash]
    except TeamPermissionError as exc:
        _handle_team_error(exc)
    except StorageUsageIncompleteError as exc:
        raise HTTPException(status_code=503, detail="TEAM_STORAGE_USAGE_UNAVAILABLE") from exc
    billing_enabled = os.getenv("TEAM_STORAGE_BILLING_ENABLED", "0") == "1"
    billing_state: dict[str, Any] = {"status": "disabled_pending_validation", "invoices": [],
                                      "outstanding_credits": 0, "warning_count": 0,
                                      "expiry_due": False, "affected_units": []}
    if billing_enabled:
        try:
            orchestration = SubChatOrchestrationService(directus_service)
            debt = await orchestration.execute("list_team_storage_debt", {
                "protocol_version": 1, "hashed_team_id": team_hash})
            periods = debt.get("periods")
            if not isinstance(periods, list):
                raise RuntimeError("Team storage invoice lookup incomplete")
            owner_rows = await directus_service.get_items("team_storage_billing_owner_state", params={
                "filter[id][_eq]": team_hash,
                "fields": "episode_id,warning_count,deadline_at,warning_manual_review_at,warning_manual_review_reason,selection_hash",
                "limit": 1,
            }, admin_required=True, no_cache=True, raise_on_error=True)
            if not isinstance(owner_rows, list) or len(owner_rows) != 1:
                raise RuntimeError("Team storage warning status unavailable")
            owner = owner_rows[0]
            units = await orchestration.execute("list_team_storage_warning_units", {
                "protocol_version": 1, "hashed_team_id": team_hash,
                "episode_id": owner.get("episode_id"), "limit": 100})
            expiry = await orchestration.execute("inspect_team_storage_expiry", {
                "protocol_version": 1, "hashed_team_id": team_hash, "now_at": int(time.time())})
            billing_state = {
                "status": "manual_review" if owner.get("warning_manual_review_at") else
                          "unpaid" if periods else "current",
                "invoices": [{"id": period["id"], "period_start_at": period["period_start_at"],
                              "measured_bytes": period["measured_bytes"], "credits_due": period["credits_due"],
                              "state": period["state"], "policy_version": period["policy_version"]}
                             for period in periods],
                "has_more_invoices": bool(debt.get("has_more")),
                "outstanding_credits": int(debt["outstanding_credits"]),
                "warning_count": int(owner.get("warning_count") or 0),
                "notice_held": bool(owner.get("warning_manual_review_reason") and not owner.get("warning_manual_review_at")),
                "notice_hold_reason": owner.get("warning_manual_review_reason") if not owner.get("warning_manual_review_at") else None,
                "deadline_at": owner.get("deadline_at"),
                "expiry_due": bool(expiry.get("due")),
                "expiry_enabled": os.getenv("TEAM_STORAGE_UNPAID_EXPIRY_ENABLED", "0") == "1",
                "affected_units": units.get("units") or [],
                "has_more_affected_units": bool(units.get("has_more")),
            }
        except Exception as exc:
            raise HTTPException(status_code=503, detail="TEAM_STORAGE_BILLING_UNAVAILABLE") from exc
    return {
        "storage": {
            "total_bytes": quote.total_bytes,
            "legacy_upload_bytes": quote.legacy_upload_bytes,
            "logical_s3_bytes": quote.logical_s3_bytes,
            "categories": quote.categories,
            "measurement_at": quote.measurement_at,
            "metering_source_version": quote.source_version,
            "metering_policy_version": quote.policy_version,
            "free_bytes": 1_073_741_824,
            "credits_per_started_excess_gib_per_week": 3,
            "billable_gib": max(0, (quote.total_bytes - 1_073_741_824 + 1_073_741_823) // 1_073_741_824),
            "weekly_cost_credits": max(0, (quote.total_bytes - 1_073_741_824 + 1_073_741_823) // 1_073_741_824) * 3,
            "billing_status": billing_state["status"],
            "billing": billing_state,
        }
    }


class TeamCardOrderRequest(BaseModel):
    credits_amount: int = Field(gt=0)
    currency: str = "eur"
    email_encryption_key: str = Field(min_length=1)
    provider: str | None = None
    return_url: str | None = None
    buyer_address: BuyerAddress | None = None


class CreateOrderResponse(BaseModel):
    provider: str
    order_id: str
    client_secret: str | None = None
    checkout_url: str | None = None
    use_checkout: bool = False


class TeamSavedCardOrderRequest(TeamCardOrderRequest):
    payment_method_id: str = Field(min_length=1)


class TeamAutoTopupRequest(BaseModel):
    enabled: bool
    amount: int | None = None
    currency: str = "eur"
    threshold: int = 100
    payment_method_id: str | None = None
    email: str | None = None


class TeamMonthlyTopupRequest(BaseModel):
    credits_amount: int = Field(gt=0)
    currency: str = "eur"
    billing_day_preference: Literal["anniversary", "first_of_month"] = "anniversary"
    return_url: str = Field(min_length=1)
    email_encryption_key: str = Field(min_length=1)
    buyer_address: BuyerAddress | None = None


class TeamMonthlyBillingDayRequest(BaseModel):
    billing_day_preference: Literal["anniversary", "first_of_month"]


async def _require_team_billing_role(directus_service: Any, team_id: str, user_id: str) -> None:
    try:
        await directus_service.team.require_team_role(team_id, user_id, TEAM_BILLING_ROLES)
    except Exception as exc:
        _handle_team_error(exc)


@router.get("/{team_id}/billing/buyer-address", response_model=BuyerAddressRequest)
@limiter.limit("30/minute")
async def get_team_buyer_address(
    request: Request, response: Response, team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
) -> BuyerAddressRequest:
    response.headers["Cache-Control"] = "private, no-store"
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    address = await BillingProfileService(directus_service, encryption_service).get_address("team", team_id)
    return BuyerAddressRequest(buyer_address=address)


@router.put("/{team_id}/billing/buyer-address", response_model=BuyerAddressRequest)
@limiter.limit("10/minute")
async def set_team_buyer_address(
    request: Request, response: Response, team_id: str, body: BuyerAddressRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
) -> BuyerAddressRequest:
    response.headers["Cache-Control"] = "private, no-store"
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    address = body.buyer_address.model_dump(exclude_none=True) if body.buyer_address else None
    await BillingProfileService(directus_service, encryption_service).save_address(
        "team", team_id, address, current_user.vault_key_id or ""
    )
    return BuyerAddressRequest(buyer_address=address)


@router.post("/{team_id}/billing/card-orders", response_model=CreateOrderResponse)
@limiter.limit("10/minute")
async def create_team_card_order(
    request: Request, response: Response, team_id: str, body: TeamCardOrderRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    cache_service: Any = Depends(get_cache_service),
    encryption_service: Any = Depends(get_encryption_service),
    payment_service: Any = Depends(get_payment_service),
) -> CreateOrderResponse:
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    amount = get_price_for_credits(body.credits_amount, body.currency)
    if amount is None:
        raise HTTPException(status_code=400, detail="Invalid credit amount or currency")
    if body.provider not in {None, "stripe", "managed"}:
        raise HTTPException(status_code=400, detail="Invalid payment provider")
    from backend.core.api.app.utils.device_fingerprint import _extract_client_ip, get_geo_data_from_ip
    from backend.core.api.app.utils.geo_utils import is_eu_vat_country
    from backend.core.api.app.utils.payment_environment import (
        EU_REVENUE_CACHE_KEY, EU_REVENUE_CACHE_TTL, EU_REVENUE_THRESHOLD_EUR_CENTS,
        should_enforce_eu_revenue_threshold,
    )

    ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
    try:
        is_eu = is_eu_vat_country(get_geo_data_from_ip(ip).get("country_code", ""))
    except Exception:
        is_eu = True
    if body.provider == "stripe":
        is_eu = True
    elif body.provider == "managed":
        is_eu = False
    if should_enforce_eu_revenue_threshold(is_eu):
        revenue = await cache_service.get(EU_REVENUE_CACHE_KEY)
        if revenue is None:
            revenue = await payment_service.provider.get_total_stripe_revenue_eur_cents()
            await cache_service.set(EU_REVENUE_CACHE_KEY, revenue, ttl=EU_REVENUE_CACHE_TTL)
        if revenue >= EU_REVENUE_THRESHOLD_EUR_CENTS:
            raise HTTPException(status_code=402, detail="eu_payment_threshold_exceeded")
    if not current_user.encrypted_email_address:
        raise HTTPException(status_code=503, detail="User email unavailable")
    email = await encryption_service.decrypt_with_email_key(current_user.encrypted_email_address, body.email_encryption_key)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid email encryption key")
    profiles = BillingProfileService(directus_service, encryption_service)
    profile = await profiles.get_profile("team", team_id)
    order = await payment_service.create_order(
        amount=amount, currency=body.currency, email=email, credits_amount=body.credits_amount,
        customer_id=profile.get("stripe_customer_id"), is_eu=is_eu,
        customer_idempotency_key=f"team-billing-customer-{hashlib.sha256(team_id.encode()).hexdigest()}",
        embed_origin=request.headers.get("Origin") or request.headers.get("Referer"),
        return_url=body.return_url, use_global_pricing=not is_eu,
    )
    if not order or not order.get("id"):
        raise HTTPException(status_code=502, detail="Failed to initiate Team payment")
    if order.get("customer_id") and order["customer_id"] != profile.get("stripe_customer_id"):
        await profiles.update_profile("team", team_id, {"stripe_customer_id": order["customer_id"]})
    order_id = order["id"]
    await profiles.save_order_context(
        order_id=order_id, owner_kind="team", owner_id=team_id, actor_user_id=current_user.id,
        credits_amount=body.credits_amount, currency=body.currency,
        provider="stripe" if is_eu else "stripe_managed",
        vault_key_id=current_user.vault_key_id, email_encryption_key=body.email_encryption_key,
        payer_email=email,
        buyer_address=body.buyer_address.model_dump(exclude_none=True) if body.buyer_address else None,
        use_saved_address="buyer_address" not in body.model_fields_set,
    )
    await cache_service.set_order(
        order_id=order_id, user_id=current_user.id, credits_amount=body.credits_amount,
        status="created", ttl=86400 if not is_eu else 3600,
        email_encryption_key=body.email_encryption_key, currency=body.currency,
        provider="stripe" if is_eu else "stripe_managed",
    )
    return CreateOrderResponse(
        provider="stripe" if is_eu else "stripe_managed", order_id=order_id,
        client_secret=order.get("client_secret"), use_checkout=not is_eu,
    )


@router.get("/{team_id}/billing/card-orders/{order_id}")
@limiter.limit("30/minute")
async def get_team_card_order_status(
    request: Request, response: Response, team_id: str, order_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
    cache_service: Any = Depends(get_cache_service),
    payment_service: Any = Depends(get_payment_service),
    team_billing_service: TeamBillingService = Depends(get_team_billing_service),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    context = await BillingProfileService(directus_service, encryption_service).get_order_context(order_id)
    if context.get("owner_kind") != "team" or context.get("owner_hash") != hashlib.sha256(team_id.encode()).hexdigest():
        raise HTTPException(status_code=404, detail="Team order not found")
    cached = await cache_service.get_order(order_id) or {}
    if context.get("provider") == "team_subscription_setup":
        profile = await BillingProfileService(directus_service, encryption_service).get_profile("team", team_id)
        completed = (cached.get("status") == "completed" or profile.get("monthly_setup_order_id") == order_id) and bool(profile.get("monthly_subscription_id"))
        state = "COMPLETED" if completed else "PENDING_CONFIRMATION"
    else:
        details = await payment_service.get_order(order_id)
        provider_state = str((details or {}).get("status") or "").upper()
        if provider_state in {"CANCELED", "FAILED"}:
            state = "FAILED"
        elif provider_state in {"SUCCEEDED", "COMPLETED"}:
            events = await directus_service.get_items(
                "team_credit_events",
                params={"filter": {"event_id": {"_eq": f"stripe:{order_id}"}, "hashed_team_id": {"_eq": context["owner_hash"]}}, "limit": 1},
                no_cache=True, admin_required=True,
            )
            state = "COMPLETED" if cached.get("status") == "completed" or events else "PENDING_CONFIRMATION"
        else:
            state = "PENDING"
    credits = None
    if state == "COMPLETED":
        account = await team_billing_service.get_billing_summary(team_id, current_user.id)
        credits = int(account.get("balance_credits") or 0)
    return {"order_id": order_id, "state": state, "current_credits": credits}


@router.get("/{team_id}/billing/payment-methods")
@limiter.limit("30/minute")
async def list_team_payment_methods(
    request: Request, response: Response, team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
    payment_service: Any = Depends(get_payment_service),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    profile = await BillingProfileService(directus_service, encryption_service).get_profile("team", team_id)
    customer_id = profile.get("stripe_customer_id")
    if not customer_id:
        return {"payment_methods": []}
    return {"payment_methods": await payment_service._stripe_provider.list_payment_methods(customer_id)}


class TeamSavePaymentMethodRequest(BaseModel):
    payment_intent_id: str = Field(min_length=1)


@router.post("/{team_id}/billing/payment-methods")
@limiter.limit("5/minute")
async def save_team_payment_method(
    request: Request, response: Response, team_id: str, body: TeamSavePaymentMethodRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
    payment_service: Any = Depends(get_payment_service),
) -> dict[str, bool]:
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    profiles = BillingProfileService(directus_service, encryption_service)
    context = await profiles.get_order_context(body.payment_intent_id)
    if context.get("owner_kind") != "team" or context.get("owner_hash") != hashlib.sha256(team_id.encode()).hexdigest():
        raise HTTPException(status_code=404, detail="Team payment order not found")
    profile = await profiles.get_profile("team", team_id)
    customer_id = profile.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="Team Stripe customer unavailable")
    method_id = await payment_service._stripe_provider.get_payment_method(body.payment_intent_id)
    if not method_id:
        raise HTTPException(status_code=404, detail="Payment method not found")
    import stripe as stripe_lib
    try:
        method = stripe_lib.PaymentMethod.retrieve(method_id)
    except stripe_lib.error.StripeError as exc:
        raise HTTPException(status_code=400, detail="Invalid payment method") from exc
    if method.customer != customer_id:
        raise HTTPException(status_code=403, detail="Payment method does not belong to this Team")
    return {"success": True}


@router.post("/{team_id}/billing/saved-card-orders")
@limiter.limit("5/minute")
async def create_team_saved_card_order(
    request: Request, response: Response, team_id: str, body: TeamSavedCardOrderRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
    cache_service: Any = Depends(get_cache_service),
    payment_service: Any = Depends(get_payment_service),
) -> dict[str, Any]:
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    profile_service = BillingProfileService(directus_service, encryption_service)
    profile = await profile_service.get_profile("team", team_id)
    customer_id = profile.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="No Team payment method")
    amount = get_price_for_credits(body.credits_amount, body.currency)
    if amount is None:
        raise HTTPException(status_code=400, detail="Invalid credit amount or currency")
    import stripe as stripe_lib
    try:
        payment_method = stripe_lib.PaymentMethod.retrieve(body.payment_method_id)
    except stripe_lib.error.StripeError as exc:
        raise HTTPException(status_code=400, detail="Invalid payment method") from exc
    if payment_method.customer != customer_id:
        raise HTTPException(status_code=403, detail="Payment method does not belong to this Team")
    from backend.core.api.app.utils.geo_utils import is_eu_vat_country
    if payment_method.card and payment_method.card.country and not is_eu_vat_country(payment_method.card.country):
        raise HTTPException(status_code=400, detail="non_eu_card_use_checkout")
    if not current_user.encrypted_email_address:
        raise HTTPException(status_code=503, detail="User email unavailable")
    email = await encryption_service.decrypt_with_email_key(current_user.encrypted_email_address, body.email_encryption_key)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid email encryption key")
    order = await payment_service._stripe_provider.create_order_with_payment_method(
        amount=amount, currency=body.currency, email=email, credits_amount=body.credits_amount,
        customer_id=customer_id, payment_method_id=body.payment_method_id,
    )
    if not order or not order.get("id"):
        raise HTTPException(status_code=502, detail="Failed to initiate Team payment")
    order_id = order["id"]
    await profile_service.save_order_context(
        order_id=order_id, owner_kind="team", owner_id=team_id, actor_user_id=current_user.id,
        credits_amount=body.credits_amount, currency=body.currency, provider="stripe",
        vault_key_id=current_user.vault_key_id, email_encryption_key=body.email_encryption_key,
        payer_email=email,
        buyer_address=body.buyer_address.model_dump(exclude_none=True) if body.buyer_address else None,
        use_saved_address="buyer_address" not in body.model_fields_set,
    )
    await cache_service.set_order(
        order_id=order_id, user_id=current_user.id, credits_amount=body.credits_amount,
        status="created", ttl=3600, email_encryption_key=body.email_encryption_key,
        currency=body.currency, provider="stripe",
    )
    return {"success": True, "order_id": order_id, "client_secret": order.get("client_secret"), "message": "Team payment order created"}


@router.get("/{team_id}/billing/auto-topup")
@limiter.limit("30/minute")
async def get_team_auto_topup(
    request: Request, response: Response, team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    profile = await BillingProfileService(directus_service, encryption_service).get_profile("team", team_id)
    payment_method_id = None
    if profile.get("encrypted_auto_topup_payment_method") and profile.get("auto_topup_vault_key_id"):
        payment_method_id = await encryption_service.decrypt_with_user_key(
            profile["encrypted_auto_topup_payment_method"], profile["auto_topup_vault_key_id"]
        )
    return {
        "enabled": bool(profile.get("auto_topup_enabled")),
        "amount": profile.get("auto_topup_amount"),
        "currency": profile.get("auto_topup_currency") or "eur",
        "threshold": 100,
        "payment_method_id": payment_method_id,
    }


@router.put("/{team_id}/billing/auto-topup")
@limiter.limit("10/minute")
async def set_team_auto_topup(
    request: Request, response: Response, team_id: str, body: TeamAutoTopupRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
    payment_service: Any = Depends(get_payment_service),
) -> dict[str, Any]:
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    profiles = BillingProfileService(directus_service, encryption_service)
    profile = await profiles.get_profile("team", team_id)
    if not body.enabled:
        await profiles.update_profile("team", team_id, {
            "auto_topup_enabled": False,
            "encrypted_auto_topup_payment_method": None,
            "encrypted_auto_topup_email": None,
            "auto_topup_payer_user_id": None,
        })
        return {"enabled": False, "amount": profile.get("auto_topup_amount"), "currency": profile.get("auto_topup_currency") or "eur", "threshold": 100, "payment_method_id": None}
    if body.threshold != 100:
        raise HTTPException(status_code=400, detail="Team auto top-up threshold is 100 credits")
    if not body.amount or get_price_for_credits(body.amount, body.currency) is None:
        raise HTTPException(status_code=400, detail="Invalid Team auto top-up amount or currency")
    if not body.email or not body.payment_method_id:
        raise HTTPException(status_code=400, detail="Email and Team payment method are required")
    if not profile.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="Team payment method unavailable")
    import stripe as stripe_lib
    try:
        method = stripe_lib.PaymentMethod.retrieve(body.payment_method_id)
    except stripe_lib.error.StripeError as exc:
        raise HTTPException(status_code=400, detail="Invalid Team payment method") from exc
    if method.customer != profile["stripe_customer_id"]:
        raise HTTPException(status_code=403, detail="Payment method does not belong to this Team")
    from backend.core.api.app.utils.geo_utils import is_eu_vat_country
    if method.card and method.card.country and not is_eu_vat_country(method.card.country):
        raise HTTPException(status_code=400, detail="non_eu_card_use_checkout")
    billing_key_id = await profiles.get_or_create_team_billing_key(team_id)
    encrypted_method, _ = await encryption_service.encrypt_with_user_key(body.payment_method_id, billing_key_id)
    encrypted_email, _ = await encryption_service.encrypt_with_user_key(body.email, billing_key_id)
    if not encrypted_method or not encrypted_email:
        raise HTTPException(status_code=503, detail="Team auto top-up encryption unavailable")
    await profiles.update_profile("team", team_id, {
        "auto_topup_enabled": True,
        "auto_topup_amount": body.amount,
        "auto_topup_currency": body.currency.lower(),
        "encrypted_auto_topup_payment_method": encrypted_method,
        "encrypted_auto_topup_email": encrypted_email,
        "auto_topup_vault_key_id": billing_key_id,
        "auto_topup_payer_user_id": current_user.id,
    })
    return {"enabled": True, "amount": body.amount, "currency": body.currency.lower(), "threshold": 100, "payment_method_id": body.payment_method_id}


@router.post("/{team_id}/billing/monthly-auto-topup")
@limiter.limit("5/minute")
async def create_team_monthly_auto_topup(
    request: Request, response: Response, team_id: str, body: TeamMonthlyTopupRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
    cache_service: Any = Depends(get_cache_service),
    payment_service: Any = Depends(get_payment_service),
) -> dict[str, Any]:
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    tier = get_team_monthly_tier(body.credits_amount, body.currency)
    if not tier:
        raise HTTPException(status_code=400, detail="Invalid Team monthly subscription tier")
    if not current_user.encrypted_email_address:
        raise HTTPException(status_code=503, detail="Billing email or encryption key unavailable")
    email = await encryption_service.decrypt_with_email_key(current_user.encrypted_email_address, body.email_encryption_key)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid email encryption key")
    profiles = BillingProfileService(directus_service, encryption_service)
    profile = await profiles.get_profile("team", team_id)
    if profile.get("monthly_subscription_id") and profile.get("monthly_subscription_status") in {"active", "trialing", "past_due"}:
        raise HTTPException(status_code=409, detail="Team already has a monthly subscription")
    stripe_provider = payment_service._stripe_provider
    customer_id = profile.get("stripe_customer_id") or await stripe_provider.get_or_create_customer(
        email, idempotency_key=f"team-billing-customer-{hashlib.sha256(team_id.encode()).hexdigest()}"
    )
    if not customer_id:
        raise HTTPException(status_code=502, detail="Team Stripe customer unavailable")
    if customer_id != profile.get("stripe_customer_id"):
        await profiles.update_profile("team", team_id, {"stripe_customer_id": customer_id})
    total_credits = body.credits_amount + tier["bonus_credits"]
    product_name = f"{total_credits:,}".replace(",", ".") + " credits (monthly auto top-up)"
    price_id = await stripe_provider._find_price_for_product(product_name, body.currency, recurring=True)
    if not price_id:
        raise HTTPException(status_code=503, detail="Team subscription product unavailable")
    billing_cycle_anchor = None
    if body.billing_day_preference == "first_of_month":
        now = datetime.now(timezone.utc)
        month = now.month + 1 if now.month < 12 else 1
        year = now.year if now.month < 12 else now.year + 1
        billing_cycle_anchor = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
    result = await stripe_provider.create_checkout_session(
        price_id=price_id, mode="subscription", return_url=body.return_url,
        customer_id=customer_id,
        metadata={
            "team_id": team_id, "user_id": current_user.id,
            "credits_amount": str(body.credits_amount),
            "bonus_credits": str(tier["bonus_credits"]),
            "currency": body.currency.lower(),
            "billing_day_preference": body.billing_day_preference,
        },
        billing_cycle_anchor=billing_cycle_anchor,
    )
    if not result or not result.get("id"):
        raise HTTPException(status_code=502, detail="Team subscription checkout unavailable")
    billing_key_id = await profiles.get_or_create_team_billing_key(team_id)
    encrypted_email, _ = await encryption_service.encrypt_with_user_key(email, billing_key_id)
    await profiles.update_profile("team", team_id, {
        "encrypted_monthly_email": encrypted_email,
        "monthly_email_vault_key_id": billing_key_id,
        "monthly_payer_user_id": current_user.id,
    })
    await profiles.save_order_context(
        order_id=result["id"], owner_kind="team", owner_id=team_id, actor_user_id=current_user.id,
        credits_amount=body.credits_amount, currency=body.currency, provider="team_subscription_setup",
        vault_key_id=current_user.vault_key_id, email_encryption_key=body.email_encryption_key,
        bonus_credits=tier["bonus_credits"], payer_email=email,
        buyer_address=body.buyer_address.model_dump(exclude_none=True) if body.buyer_address else None,
        use_saved_address="buyer_address" not in body.model_fields_set,
    )
    await cache_service.set_order(
        order_id=result["id"], user_id=current_user.id, credits_amount=body.credits_amount,
        status="created", ttl=86400, currency=body.currency.lower(), provider="stripe",
        subscription_setup=True, bonus_credits=tier["bonus_credits"],
        billing_day_preference=body.billing_day_preference,
    )
    return {"order_id": result["id"], "client_secret": result.get("client_secret")}


@router.get("/{team_id}/billing/monthly-auto-topup")
@limiter.limit("30/minute")
async def get_team_monthly_auto_topup(
    request: Request, response: Response, team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    profile = await BillingProfileService(directus_service, encryption_service).get_profile("team", team_id)
    subscription_id = profile.get("monthly_subscription_id")
    if not subscription_id or profile.get("monthly_subscription_status") == "canceled":
        return {"has_subscription": False, "subscription": None}
    credits = int(profile.get("monthly_subscription_credits") or 0)
    currency = profile.get("monthly_subscription_currency") or "eur"
    tier = get_team_monthly_tier(credits, currency) or {"price": 0, "bonus_credits": int(profile.get("monthly_subscription_bonus_credits") or 0)}
    return {"has_subscription": True, "subscription": {
        "subscription_id": subscription_id,
        "status": profile.get("monthly_subscription_status") or "unknown",
        "credits_amount": credits,
        "bonus_credits": int(profile.get("monthly_subscription_bonus_credits") or 0),
        "currency": currency,
        "price": tier["price"],
        "next_billing_date": profile.get("monthly_next_billing_date"),
        "cancel_at_period_end": False,
        "billing_day_preference": profile.get("monthly_billing_day_preference") or "anniversary",
    }}


@router.post("/{team_id}/billing/monthly-auto-topup/cancel")
@limiter.limit("5/minute")
async def cancel_team_monthly_auto_topup(
    request: Request, response: Response, team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
    payment_service: Any = Depends(get_payment_service),
) -> dict[str, Any]:
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    profiles = BillingProfileService(directus_service, encryption_service)
    profile = await profiles.get_profile("team", team_id)
    subscription_id = profile.get("monthly_subscription_id")
    if not subscription_id or profile.get("monthly_subscription_status") == "canceled":
        raise HTTPException(status_code=404, detail="Team subscription not found")
    result = await payment_service._stripe_provider.cancel_subscription(subscription_id)
    if not result:
        raise HTTPException(status_code=502, detail="Team subscription cancellation failed")
    await profiles.update_profile("team", team_id, {
        "monthly_subscription_status": "canceled",
    })
    return {"subscription_id": subscription_id, "status": result.get("status", "canceled"), "cancel_at_period_end": False}


@router.patch("/{team_id}/billing/monthly-auto-topup/billing-day")
@limiter.limit("10/minute")
async def update_team_monthly_billing_day(
    request: Request, response: Response, team_id: str, body: TeamMonthlyBillingDayRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
    payment_service: Any = Depends(get_payment_service),
) -> dict[str, Any]:
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    profiles = BillingProfileService(directus_service, encryption_service)
    profile = await profiles.get_profile("team", team_id)
    subscription_id = profile.get("monthly_subscription_id")
    if not subscription_id or profile.get("monthly_subscription_status") == "canceled":
        raise HTTPException(status_code=404, detail="Team subscription not found")
    subscription = await payment_service._stripe_provider.get_subscription(subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Team subscription not found at payment provider")
    period_end = subscription.get("current_period_end")
    if not period_end:
        raise HTTPException(status_code=503, detail="Team subscription billing date unavailable")
    current_end = datetime.fromtimestamp(period_end, tz=timezone.utc)
    if body.billing_day_preference == "first_of_month":
        month = current_end.month + 1 if current_end.month < 12 else 1
        year = current_end.year if current_end.month < 12 else current_end.year + 1
        next_date = datetime(year, month, 1, tzinfo=timezone.utc)
        import stripe as stripe_lib
        try:
            stripe_lib.Subscription.modify(
                subscription_id, proration_behavior="none", billing_cycle_anchor="now",
                trial_end=int(next_date.timestamp()),
            )
        except stripe_lib.error.StripeError as exc:
            raise HTTPException(status_code=502, detail="Team billing day update failed") from exc
    else:
        next_date = current_end
    await profiles.update_profile("team", team_id, {
        "monthly_billing_day_preference": body.billing_day_preference,
        "monthly_next_billing_date": next_date.isoformat(),
    })
    return {"billing_day_preference": body.billing_day_preference, "next_billing_date": next_date.isoformat()}


@router.get("/{team_id}/storage/notice")
@limiter.limit("30/minute")
async def get_team_storage_notice(
    request: Request,
    response: Response,
    team_id: str,
    after_unit_id: str | None = Query(default=None, min_length=64, max_length=64, pattern="^[a-f0-9]{64}$"),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, Any]:
    """Owner/admin view of the frozen Team warning scope, with bounded paging."""
    del request, response
    try:
        await directus_service.team.require_team_role(team_id, current_user.id, TEAM_BILLING_ROLES)
    except TeamPermissionError as exc:
        _handle_team_error(exc)
    if os.getenv("TEAM_STORAGE_BILLING_ENABLED", "0") != "1":
        return {"episode_id": None, "warning_count": 0, "deadline_at": None,
                "manual_review": False, "notice_held": False,
                "notice_hold_reason": None, "unit_selection_hash": None,
                "units": [], "has_more": False, "next_after_unit_id": None}
    try:
        return await SubChatOrchestrationService(directus_service).execute(
            "list_team_storage_warning_units", {
                "protocol_version": 1, "hashed_team_id": hash_id(team_id),
                "limit": limit, "after_unit_id": after_unit_id,
            })
    except Exception as exc:
        raise HTTPException(status_code=503, detail="TEAM_STORAGE_NOTICE_UNAVAILABLE") from exc


@router.post("/{team_id}/billing/bank-transfer-orders", response_model=CreateBankTransferOrderResponse)
@limiter.limit("5/hour")
async def create_team_bank_transfer_order(
    request: Request,
    response: Response,
    team_id: str,
    body: CreateBankTransferOrderRequest,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    cache_service: Any = Depends(get_cache_service),
    payment_service: Any = Depends(get_payment_service),
    encryption_service: Any = Depends(get_encryption_service),
) -> CreateBankTransferOrderResponse:
    del request, response
    try:
        await directus_service.team.require_team_role(team_id, current_user.id, TEAM_BILLING_ROLES)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    if not payment_service.is_bank_transfer_available:
        raise HTTPException(status_code=503, detail="Bank transfer payments are currently unavailable.")
    if body.currency.lower() != "eur":
        raise HTTPException(status_code=400, detail="Bank transfers are only available in EUR (SEPA).")
    if body.is_gift_card or body.is_signup:
        raise HTTPException(status_code=400, detail="Team bank transfer orders cannot be gift-card or signup orders.")
    if not body.email_encryption_key:
        raise HTTPException(status_code=400, detail="Email encryption key is required for bank transfer orders.")
    price_cents = get_price_for_credits(body.credits_amount, "eur")
    if price_cents is None:
        raise HTTPException(status_code=400, detail=f"No pricing tier found for {body.credits_amount} credits.")

    pending_rows = await directus_service.get_items(
        "pending_bank_transfers",
        params={
            "filter[user_id][_eq]": str(current_user.id),
            "filter[team_id][_eq]": team_id,
            "filter[credits_amount][_eq]": body.credits_amount,
            "filter[order_type][_eq]": TEAM_BANK_TRANSFER_ORDER_TYPE,
            "filter[status][_eq]": "pending",
            "sort": "-created_at",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
    )
    bank_details = payment_service.get_bank_transfer_details()
    if pending_rows:
        return _team_bank_transfer_response(pending_rows[0], bank_details, price_cents)

    if not current_user.encrypted_email_address:
        raise HTTPException(status_code=503, detail="User email unavailable")
    payer_email = await encryption_service.decrypt_with_email_key(
        current_user.encrypted_email_address, body.email_encryption_key
    )
    if not payer_email:
        raise HTTPException(status_code=400, detail="Invalid email encryption key")

    order_id = f"bt_{uuid.uuid4().hex[:16]}"
    hashed_team_id = hashlib.sha256(team_id.encode()).hexdigest()
    team_prefix = hashed_team_id[:8]
    reference = generate_bank_transfer_reference("OMT", team_prefix, middle_length=len(team_prefix))
    created_at = datetime.now(timezone.utc).isoformat()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    record = {
        "order_id": order_id,
        "user_id": str(current_user.id),
        "team_id": team_id,
        "hashed_team_id": hashed_team_id,
        "credits_amount": body.credits_amount,
        "amount_expected_cents": price_cents,
        "currency": "eur",
        "reference": reference,
        "status": "pending",
        "order_type": TEAM_BANK_TRANSFER_ORDER_TYPE,
        "created_at": created_at,
        "expires_at": expires_at,
        "email_encryption_key": body.email_encryption_key,
    }
    success, created = await directus_service.create_item("pending_bank_transfers", record, admin_required=True)
    if not success or not isinstance(created, dict):
        raise HTTPException(status_code=500, detail="Failed to create team bank transfer order.")
    await BillingProfileService(directus_service, encryption_service).save_order_context(
        order_id=order_id, owner_kind="team", owner_id=team_id, actor_user_id=current_user.id,
        credits_amount=body.credits_amount, currency="eur", provider="bank_transfer",
        vault_key_id=current_user.vault_key_id, email_encryption_key=body.email_encryption_key,
        payer_email=payer_email,
        buyer_address=body.buyer_address.model_dump(exclude_none=True) if body.buyer_address else None,
        use_saved_address="buyer_address" not in body.model_fields_set,
    )
    await cache_service.set_bank_transfer_order(
        order_id=order_id,
        user_id=str(current_user.id),
        credits_amount=body.credits_amount,
        amount_expected_cents=price_cents,
        reference=reference,
        currency="eur",
        email_encryption_key=body.email_encryption_key,
        order_type=TEAM_BANK_TRANSFER_ORDER_TYPE,
        team_id=team_id,
        hashed_team_id=hashed_team_id,
        expires_at=expires_at,
    )
    return _team_bank_transfer_response(created, bank_details, price_cents)


@router.get("/{team_id}/billing/bank-transfer-orders")
@limiter.limit("30/minute")
async def list_team_bank_transfer_orders(
    request: Request,
    response: Response,
    team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> dict[str, list[PendingBankTransferSummary]]:
    del request, response
    try:
        await directus_service.team.require_team_role(team_id, current_user.id, TEAM_BILLING_ROLES)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    rows = await directus_service.get_items(
        "pending_bank_transfers",
        params={
            "filter[team_id][_eq]": team_id,
            "filter[order_type][_eq]": TEAM_BANK_TRANSFER_ORDER_TYPE,
            "filter[status][_eq]": "pending",
            "sort": "-created_at",
            "limit": 20,
        },
        no_cache=True,
        admin_required=True,
    )
    return {"orders": [
        PendingBankTransferSummary(
            order_id=row.get("order_id", ""),
            credits_amount=int(row.get("credits_amount") or 0),
            amount_eur=f"{int(row.get('amount_expected_cents') or 0) / 100:.2f}",
            reference=row.get("reference", ""),
            status=row.get("status", "pending"),
            expires_at=row.get("expires_at", ""),
        )
        for row in (rows or [])
    ]}


@router.get("/{team_id}/billing/bank-transfer-orders/{order_id}", response_model=BankTransferStatusResponse)
@limiter.limit("30/minute")
async def get_team_bank_transfer_order_status(
    request: Request,
    response: Response,
    team_id: str,
    order_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
) -> BankTransferStatusResponse:
    del request, response
    try:
        await directus_service.team.require_team_role(team_id, current_user.id, TEAM_BILLING_ROLES)
    except Exception as exc:  # noqa: BLE001 - converted by typed handler
        _handle_team_error(exc)
    rows = await directus_service.get_items(
        "pending_bank_transfers",
        params={
            "filter[order_id][_eq]": order_id,
            "filter[team_id][_eq]": team_id,
            "filter[order_type][_eq]": TEAM_BANK_TRANSFER_ORDER_TYPE,
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Team bank transfer order not found.")
    return _team_bank_transfer_status(rows[0])


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
    _reject_cleartext_team_payload(body.model_dump(exclude_none=True))
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


@router.get("/{team_id}/billing/usage/export")
@limiter.limit("10/minute")
async def export_team_usage(
    request: Request, response: Response, team_id: str,
    format: Literal["csv", "pdf"] = Query(default="csv"),
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    team_billing_service: TeamBillingService = Depends(get_team_billing_service),
) -> StreamingResponse:
    """Owner/admin Team-only usage export; no Personal usage is queried."""
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    usage = await team_billing_service.list_usage(team_id, current_user.id)
    team_token = hashlib.sha256(team_id.encode()).hexdigest()[:12]
    filename = f"team_usage_{team_token}.{format}"
    fields = ("created_at", "actor_user_hash", "workspace_type", "object_id_hash", "credit_amount", "event_id")
    if format == "csv":
        import csv

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(fields)
        for event in usage:
            writer.writerow([event.get(field, "") for field in fields])
        content = output.getvalue().encode("utf-8")
        media_type = "text/csv; charset=utf-8"
    else:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen.canvas import Canvas

        output_pdf = io.BytesIO()
        canvas = Canvas(output_pdf, pagesize=A4)
        width, height = A4
        y = height - 48
        canvas.setFont("Helvetica-Bold", 14)
        canvas.drawString(42, y, "Team credit usage")
        y -= 26
        canvas.setFont("Helvetica", 9)
        for event in usage:
            if y < 42:
                canvas.showPage()
                canvas.setFont("Helvetica", 9)
                y = height - 48
            line = "  |  ".join(str(event.get(field, ""))[:32] for field in ("created_at", "workspace_type", "credit_amount", "actor_user_hash"))
            canvas.drawString(42, y, line[:105])
            y -= 15
        canvas.save()
        content = output_pdf.getvalue()
        media_type = "application/pdf"
    return StreamingResponse(
        io.BytesIO(content), media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


@router.get("/{team_id}/billing/invoices")
@limiter.limit("30/minute")
async def list_team_invoices(
    request: Request, response: Response, team_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
) -> dict[str, Any]:
    """First-party Team invoice list, owner/admin scoped, no Personal invoice fallback."""
    response.headers["Cache-Control"] = "private, no-store"
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    team_hash = hashlib.sha256(team_id.encode()).hexdigest()
    invoices = await directus_service.get_items(
        "invoices", params={"filter": {"hashed_team_id": {"_eq": team_hash}}, "sort": "-date", "limit": 100},
        no_cache=True, admin_required=True,
    ) or []
    transfers = await directus_service.get_items(
        "pending_bank_transfers",
        params={"filter": {"team_id": {"_eq": team_id}, "order_type": {"_eq": TEAM_BANK_TRANSFER_ORDER_TYPE}, "status": {"_in": ["pending", "completed"]}}, "limit": 100},
        no_cache=True, admin_required=True,
    ) or []
    by_order = {row.get("order_id"): row for row in transfers}
    rows = []
    invoiced_orders = set()
    for invoice in invoices:
        key_id = invoice.get("invoice_vault_key_id")
        if not key_id:
            continue
        async def decrypt(field: str, default: str = "") -> str:
            ciphertext = invoice.get(field)
            return str(await encryption_service.decrypt_with_user_key(ciphertext, key_id)) if ciphertext else default
        order_id = invoice.get("order_id")
        transfer = by_order.get(order_id) or {}
        rows.append({
            "id": invoice["id"], "order_id": order_id,
            "date": str(invoice.get("date") or "")[:10],
            "amount": await decrypt("encrypted_amount", "0"),
            "credits_purchased": int(await decrypt("encrypted_credits_purchased", "0")),
            "filename": await decrypt("encrypted_filename"),
            "currency": await decrypt("encrypted_currency", "eur"),
            "provider": invoice.get("provider"),
            "is_gift_card": False,
            "refunded_at": invoice.get("refunded_at"),
            "refund_status": invoice.get("refund_status"),
            "bank_transfer_reference": transfer.get("reference"),
            "transaction_status": transfer.get("status"),
            "document_status": "ready",
        })
        invoiced_orders.add(order_id)
    for transfer in transfers:
        if transfer.get("order_id") in invoiced_orders:
            continue
        rows.append({
            "id": transfer["order_id"], "order_id": transfer["order_id"],
            "date": str(transfer.get("completed_at") or transfer.get("created_at") or "")[:10],
            "amount": str(transfer.get("amount_expected_cents") or 0),
            "credits_purchased": int(transfer.get("credits_amount") or 0),
            "filename": "", "currency": "eur", "provider": "bank_transfer",
            "is_gift_card": False, "refunded_at": None, "refund_status": None,
            "bank_transfer_reference": transfer.get("reference"),
            "transaction_status": transfer.get("status"),
            "document_status": "pending_bank_transfer" if transfer.get("status") == "pending" else "generating",
        })
    rows.sort(key=lambda item: item["date"], reverse=True)
    return {"invoices": rows}


@router.get("/{team_id}/billing/invoices/{invoice_id}/download")
@limiter.limit("30/minute")
async def download_team_invoice(
    request: Request, response: Response, team_id: str, invoice_id: str,
    current_user: User = Depends(_current_user),
    directus_service: "DirectusService" = Depends(get_directus_service),
    encryption_service: Any = Depends(get_encryption_service),
    s3_service: Any = Depends(get_s3_service),
) -> StreamingResponse:
    await _require_team_billing_role(directus_service, team_id, current_user.id)
    team_hash = hashlib.sha256(team_id.encode()).hexdigest()
    rows = await directus_service.get_items(
        "invoices", params={"filter": {"id": {"_eq": invoice_id}, "hashed_team_id": {"_eq": team_hash}}, "limit": 1},
        no_cache=True, admin_required=True,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Team invoice not found")
    invoice = rows[0]
    key_id = invoice.get("invoice_vault_key_id")
    if not key_id:
        raise HTTPException(status_code=503, detail="Team invoice encryption key unavailable")
    s3_key = await encryption_service.decrypt_with_user_key(invoice["encrypted_s3_object_key"], key_id)
    aes_key = await encryption_service.decrypt_with_user_key(invoice["encrypted_aes_key"], key_id)
    if not s3_key or not aes_key:
        raise HTTPException(status_code=503, detail="Team invoice data unavailable")
    from backend.core.api.app.services.s3.config import get_bucket_name
    encrypted_pdf = await s3_service.get_file(
        bucket_name=get_bucket_name("invoices", os.getenv("SERVER_ENVIRONMENT", "development")),
        object_key=s3_key,
    )
    if not encrypted_pdf:
        raise HTTPException(status_code=404, detail="Team invoice file not found")
    pdf = AESGCM(base64.b64decode(aes_key)).decrypt(base64.b64decode(invoice["aes_nonce"]), encrypted_pdf, b"")
    filename = f"team_invoice_{invoice_id}.pdf"
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"})
