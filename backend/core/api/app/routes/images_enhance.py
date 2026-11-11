# backend/core/api/app/routes/images_enhance.py
#
# Image Enhance: a faithful 2K re-render of one image embed, stored by the
# client core as the next version of the same embed.
# Specification: feature.embed-user-edits (embed-user-edits.enhance.faithful-2k,
# embed-user-edits.enhance.billed-once-refunded-on-failure).
# Plan: docs/plans/embed-user-edit-versions (A2).
#
# Access model: first-party client surface only (session auth; web, CLI/TUI and
# Apple through the shared Rust core). Not on the public or developer API-key
# surface: the request carries the source file's AES key (client-decrypted
# embed content) and the response returns the result's AES key. The source key
# is Vault-encrypted for the worker in transit and never stored; the result is
# stored Vault-encrypted for the requester only.
# Scoping: the embed must belong to the requester (Personal); chat scope needs
# chat ownership and the embed's chat and is refused with 403
# project_context_required while the embed has a live Project file link (the
# commit refuses that scope too); project scope needs a Personal Project with a
# live file link to the embed (jobs.PROJECT_FILE_ITEM_TYPES, deleted_target_state
# null, the same rule as the user revision commit). The job stores the scope and
# the commit accepts the result only in that scope. Team-billed Enhance is refused (403 team_enhance_unavailable)
# until a Team refund route exists, so a Team charge can never stay unrefunded.
# Limits: 10/minute per IP and, per user, 10 new jobs a minute and 100 a day
# (429). Paid: 402 when the Personal balance is below the quoted price. A stale
# expected_version is 409 embed_version_conflict without a job or charge.
# Idempotent by operation_id: a replay returns the same job and never charges again.
# Billing of an unsaved result: the job records result_delivered_at before a
# response first carries the result (file keys and AES key). An uncommitted
# result is refunded on expiry only if it was never delivered; a delivered one
# stays charged and can be read and committed until expires_at, never after.
# test-file: backend/tests/test_images_enhance.py

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from kombu.exceptions import OperationalError as BrokerUnavailable
from pydantic import BaseModel, ConfigDict, Field

from backend.apps.images import enhance_jobs as jobs
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.billing_service import BillingService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.config_manager import config_manager
from backend.shared.python_utils.media_encryption import AES_GCM_NONCE_BYTES, AES_KEY_BYTES, MEDIA_ENCRYPTION_V2

router = APIRouter(prefix="/v1/images/enhance", tags=["Images"])
logger = logging.getLogger(__name__)

UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
ID_PATTERN = r"^[A-Za-z0-9._:-]{1,128}$"
IMAGE_TYPES = frozenset({("images", "generated_image"), ("images", "upload")})
MAX_SOURCE_SIDE = 8192
USER_LIMIT_PER_MINUTE = 10
USER_LIMIT_PER_DAY = 100
ENHANCE_TASK_NAME = "apps.images.tasks.enhance"
ENHANCE_QUEUE = "app_images"
_B64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


class ChatScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["chat"]
    chat_id: str = Field(pattern=ID_PATTERN)
    team_id: Optional[str] = Field(default=None, pattern=ID_PATTERN)


class ProjectScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["project"]
    project_id: str = Field(pattern=ID_PATTERN)
    team_id: Optional[str] = Field(default=None, pattern=ID_PATTERN)


class EnhanceSource(BaseModel):
    """The head version's file to enhance, as named in the decrypted embed content."""

    model_config = ConfigDict(extra="forbid")
    s3_key: str = Field(min_length=1, max_length=512)
    aes_key: str = Field(min_length=44, max_length=44, repr=False)
    aes_nonce: Optional[str] = Field(default=None, min_length=16, max_length=16)
    encryption: Optional[Literal["aes-gcm-nonce-prefixed-v1"]] = None
    format: Literal["png", "jpg", "jpeg", "webp"]
    width: int = Field(gt=0, le=MAX_SOURCE_SIDE)
    height: int = Field(gt=0, le=MAX_SOURCE_SIDE)


class EnhanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(pattern=UUID_PATTERN)
    embed_id: str = Field(pattern=ID_PATTERN)
    scope: ChatScope | ProjectScope = Field(discriminator="kind")
    expected_version: int = Field(ge=1)
    source: EnhanceSource


def _decoded_length(value: str) -> int:
    if not _B64.fullmatch(value):
        return -1
    try:
        return len(base64.b64decode(value, validate=True))
    except (binascii.Error, ValueError):
        return -1


def _validate_source_encoding(source: EnhanceSource) -> None:
    if _decoded_length(source.aes_key) != AES_KEY_BYTES:
        raise HTTPException(status_code=422, detail="invalid_source_key")
    if source.encryption == MEDIA_ENCRYPTION_V2:
        if source.aes_nonce is not None:
            raise HTTPException(status_code=422, detail="invalid_source_nonce")
    elif source.aes_nonce is None or _decoded_length(source.aes_nonce) != AES_GCM_NONCE_BYTES:
        raise HTTPException(status_code=422, detail="invalid_source_nonce")


def _logical_version(value: Any) -> int:
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HTTPException(status_code=409, detail="embed_version_malformed")
    return value


def _json_list(value: Any) -> list:
    if value is None:
        return []
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list):
        raise HTTPException(status_code=409, detail="embed_file_index_malformed")
    return parsed


async def _owned_embed(directus: Any, *, embed_id: str, owner_hash: str) -> Dict[str, Any]:
    rows = await directus.get_items("embeds", params={
        "filter[embed_id][_eq]": embed_id, "filter[hashed_user_id][_eq]": owner_hash,
        "fields": "id,embed_id,hashed_user_id,hashed_chat_id,hashed_team_id,version_number,s3_file_keys,app_id,skill_id",
        "limit": 2,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list) or len(rows) != 1:
        raise HTTPException(status_code=404, detail="embed_not_found")
    row = rows[0]
    if row.get("hashed_team_id"):
        raise HTTPException(status_code=403, detail="team_enhance_unavailable")
    return row


async def _live_project_file_links(directus: Any, *, embed_id: str, project_id: Optional[str] = None) -> list:
    """Live Project file links of the embed (in one Project, or in any when ``project_id`` is None)."""
    params: Dict[str, Any] = {
        "filter[item_type][_in]": ",".join(jobs.PROJECT_FILE_ITEM_TYPES),
        "filter[target_id_hash][_eq]": jobs.hash_id(embed_id),
        "filter[deleted_target_state][_null]": True,
        "fields": "id", "limit": 1,
    }
    if project_id is not None:
        params["filter[hashed_project_id][_eq]"] = jobs.hash_id(project_id)
    links = await directus.get_items("project_items", params=params, admin_required=True, no_cache=True,
                                     raise_on_error=True)
    if not isinstance(links, list):
        raise HTTPException(status_code=503, detail="project_lookup_failed")
    return links


async def _require_scope(directus: Any, *, scope: ChatScope | ProjectScope, embed: Dict[str, Any], user_id: str) -> str:
    """Return the scope id after checking the requester may change the embed there."""
    if isinstance(scope, ChatScope):
        if embed.get("hashed_chat_id") != jobs.hash_id(scope.chat_id):
            raise HTTPException(status_code=404, detail="embed_not_found")
        if not await directus.chat.check_chat_ownership(scope.chat_id, user_id):
            raise HTTPException(status_code=404, detail="chat_not_found")
        # A Project file has one writer scope, as in the user revision commit.
        if await _live_project_file_links(directus, embed_id=str(embed["embed_id"])):
            raise HTTPException(status_code=403, detail="project_context_required")
        return scope.chat_id
    projects = await directus.get_items("projects", params={
        "filter[project_id][_eq]": scope.project_id, "filter[hashed_user_id][_eq]": jobs.hash_id(user_id),
        "fields": "id,project_id,hashed_team_id", "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(projects, list) or not projects or projects[0].get("hashed_team_id"):
        raise HTTPException(status_code=404, detail="project_not_found")
    if not await _live_project_file_links(directus, embed_id=str(embed["embed_id"]), project_id=scope.project_id):
        raise HTTPException(status_code=404, detail="embed_not_in_project")
    return scope.project_id


async def _consume_user_rate_limit(cache_service: Any, owner_hash: str) -> None:
    """Fixed-window per-user limits for new jobs; replays never reach this."""
    client = await cache_service.client
    if not client:
        raise HTTPException(status_code=503, detail="rate_limit_unavailable")
    now = jobs.now_ts()
    windows = ((f"images_enhance_rate:{owner_hash}:m:{now // 60}", 60, USER_LIMIT_PER_MINUTE),
               (f"images_enhance_rate:{owner_hash}:d:{now // 86400}", 86400, USER_LIMIT_PER_DAY))
    for key, ttl, limit in windows:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, ttl)
        if count > limit:
            raise HTTPException(status_code=429, detail="rate_limited")


async def _view(state: Any, job: Dict[str, Any], user: User) -> Dict[str, Any]:
    """The requester's view; the result is included only after its delivery is recorded."""
    result = None
    if job.get("encrypted_result") and jobs.result_deliverable(job, now=jobs.now_ts()):
        result = await jobs.open_result(
            state.encryption_service, vault_key_id=user.vault_key_id, ciphertext=job["encrypted_result"],
        )
        try:
            job = await jobs.mark_result_delivered(state.directus_service, job)
        except jobs.EnhanceJobConflict as exc:
            raise HTTPException(status_code=409, detail="enhance_job_busy") from exc
    return jobs.public_view(job, result=result)


def _replay_or_conflict(job: Dict[str, Any], *, owner_hash: str, embed_id: str) -> None:
    if job.get("hashed_user_id") != owner_hash or job.get("embed_id") != embed_id:
        raise HTTPException(status_code=409, detail="operation_id_conflict")


@router.post("", include_in_schema=False)
@limiter.limit("10/minute")
async def start_enhance(
    request: Request, response: Response, body: EnhanceRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    state = request.app.state
    directus = state.directus_service
    owner_hash = jobs.hash_id(current_user.id)
    if body.scope.team_id is not None:
        raise HTTPException(status_code=403, detail="team_enhance_unavailable")

    existing = await jobs.get_job(directus, body.operation_id)
    if existing is not None:
        _replay_or_conflict(existing, owner_hash=owner_hash, embed_id=body.embed_id)
        response.status_code = 200
        return await _view(state, existing, current_user)

    _validate_source_encoding(body.source)
    embed = await _owned_embed(directus, embed_id=body.embed_id, owner_hash=owner_hash)
    if (embed.get("app_id"), embed.get("skill_id")) not in IMAGE_TYPES:
        raise HTTPException(status_code=422, detail="not_an_image")
    scope_id = await _require_scope(directus, scope=body.scope, embed=embed, user_id=current_user.id)
    head = _logical_version(embed.get("version_number"))
    if head != body.expected_version:
        raise HTTPException(status_code=409, detail={"code": "embed_version_conflict", "current_version": head})
    owned_keys = {ref.get("key") for ref in _json_list(embed.get("s3_file_keys")) if isinstance(ref, dict)}
    if body.source.s3_key not in owned_keys:
        raise HTTPException(status_code=422, detail="source_not_owned")

    try:
        credits = jobs.enhance_credits(config_manager)
    except jobs.EnhanceJobError as exc:
        logger.error("Enhance pricing unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="pricing_unavailable") from exc
    billing = BillingService(state.cache_service, directus, state.encryption_service)
    if await billing.get_authoritative_personal_balance(user_id=current_user.id, user_id_hash=owner_hash) < credits:
        raise HTTPException(status_code=402, detail="insufficient_credits")
    await _consume_user_rate_limit(state.cache_service, owner_hash)

    # The worker needs the source key; it travels Vault-encrypted and is never stored.
    wrapped_source_key, _ = await state.encryption_service.encrypt_with_user_key(
        body.source.aes_key, current_user.vault_key_id,
    )
    if not wrapped_source_key:
        raise HTTPException(status_code=503, detail="encryption_unavailable")
    job, created = await jobs.create_job(
        directus, operation_id=body.operation_id, embed_id=body.embed_id, user_id=current_user.id,
        scope_kind=body.scope.kind, scope_id=scope_id, base_version=head, credits=credits,
    )
    if not created:
        _replay_or_conflict(job, owner_hash=owner_hash, embed_id=body.embed_id)
        response.status_code = 200
        return await _view(state, job, current_user)

    from backend.core.api.app.tasks.celery_config import app as celery_app

    try:
        celery_app.send_task(ENHANCE_TASK_NAME, kwargs={
            "operation_id": body.operation_id,
            "user_id": current_user.id,
            "vault_key_id": current_user.vault_key_id,
            "chat_id": body.scope.chat_id if isinstance(body.scope, ChatScope) else None,
            "source": {
                "s3_key": body.source.s3_key,
                "wrapped_aes_key": wrapped_source_key,
                "aes_nonce": body.source.aes_nonce,
                "encryption": body.source.encryption,
                "format": body.source.format,
            },
        }, queue=ENHANCE_QUEUE)
    except BrokerUnavailable as exc:
        await jobs.transition(directus, job, expected_state=jobs.STATE_PENDING,
                              changes={"state": jobs.STATE_FAILED, "error_code": "dispatch_failed"})
        raise HTTPException(status_code=503, detail="enhance_unavailable") from exc
    response.status_code = 202
    return jobs.public_view(job)


@router.get("/{operation_id}", include_in_schema=False)
@limiter.limit("60/minute")
async def get_enhance(
    request: Request, response: Response, operation_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    if not re.fullmatch(UUID_PATTERN, operation_id):
        raise HTTPException(status_code=422, detail="invalid_operation_id")
    job = await jobs.get_job(request.app.state.directus_service, operation_id)
    if job is None or job.get("hashed_user_id") != jobs.hash_id(current_user.id):
        raise HTTPException(status_code=404, detail="enhance_not_found")
    return await _view(request.app.state, job, current_user)
