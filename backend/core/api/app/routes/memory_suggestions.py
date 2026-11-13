# backend/core/api/app/routes/memory_suggestions.py
#
# API surface: first-party client surface only (session auth; never public/developer API-key REST).
# Routes: POST /update-preview and POST /create-draft (both explicit user actions, billed).
# Surface: first-party client only (session auth). Accepts cleartext memory and
# chat text for ONE explicit user action; text is never logged or stored.
# Rate limited; refuses when the wallet is empty. The model request is charged
# and attributed to the originating chat; the usage record holds token counts
# and chat_id only. A false-positive ("unchanged") request is charged too.
# Exactly-once: the client sends one request_id per user action and repeats it on
# its automatic network retry. The first delivery claims the id; a second delivery
# is refused with 409 before any model call or charge, so one action is never
# billed twice. Only the id is kept (10 minutes), never text.
# Spec: app-memories.suggestions.billing
# test-file: backend/tests/test_memory_suggestions_route.py

import hashlib
import logging
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.apps.ai.processing.memory_create_draft import run_memory_create_draft
from backend.apps.ai.processing.memory_update_preview import MemoryPreviewError, run_memory_update_preview
from backend.apps.ai.processing.memory_preview_billing import charge_preview, priced_buckets
from backend.apps.ai.processing.postprocessor import POSTPROCESSING_MODEL_ID
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.billing_service import BillingService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.config_manager import config_manager

router = APIRouter(prefix="/v1/memory-suggestions", tags=["Memory Suggestions"])
logger = logging.getLogger(__name__)

REQUEST_CLAIM_TTL_SECONDS = 600
REQUEST_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
# Same shape as a chat turn's message id; the usage row links the charge to that turn.
MESSAGE_ID_MAX_LENGTH = 128


def _claim_key(user_id_hash: str, request_id: str) -> str:
    return f"memory_suggestion_request:{user_id_hash}:{request_id}"


async def _claim_request(cache_service: Any, user_id_hash: str, request_id: Optional[str]) -> str:
    """Return the operation suffix for one user action; refuse a second delivery of the same request_id."""
    if request_id is None:
        return str(uuid.uuid4())
    client = await cache_service.client
    key = _claim_key(user_id_hash, request_id)
    if not await client.set(key, "1", nx=True, ex=REQUEST_CLAIM_TTL_SECONDS):
        logger.info("Memory suggestion request refused as duplicate delivery")
        raise HTTPException(status_code=409, detail="duplicate_request")
    return request_id


async def _release_unbilled_request(cache_service: Any, user_id_hash: str, request_id: Optional[str]) -> None:
    """Free the claim of an attempt that produced no result and charged nothing.

    The same request_id may then be retried. Once any charge was made the claim
    is kept, so one request_id is never billed for a second model call.
    """
    if request_id is None:
        return
    client = await cache_service.client
    await client.delete(_claim_key(user_id_hash, request_id))
    logger.info("Memory suggestion request claim released after an unbilled failure")


class PreviewMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8_000)


class UpdatePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_id: str = Field(min_length=1, max_length=64)
    memory_id: str = Field(min_length=1, max_length=240)
    memory_markdown: str = Field(min_length=1, max_length=24_000, repr=False)
    messages: List[PreviewMessage] = Field(min_length=1, max_length=24, repr=False)
    request_id: Optional[str] = Field(default=None, pattern=REQUEST_ID_PATTERN)
    message_id: Optional[str] = Field(default=None, min_length=1, max_length=MESSAGE_ID_MAX_LENGTH)


@router.post("/update-preview", include_in_schema=False)
@limiter.limit("20/minute")
async def update_preview(request: Request, response: Response, body: UpdatePreviewRequest) -> Dict[str, Any]:
    state = request.app.state
    user = await _user(request, response)
    # Ownership first: no LLM call or charge may be attributed to a foreign chat.
    if not await state.directus_service.chat.check_chat_ownership(body.chat_id, user.id):
        raise HTTPException(status_code=404, detail="Chat not found")
    user_id_hash = hashlib.sha256(user.id.encode()).hexdigest()
    billing = BillingService(state.cache_service, state.directus_service, state.encryption_service)
    if await billing.get_authoritative_personal_balance(user_id=user.id, user_id_hash=user_id_hash) < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits")
    usage_events: List[Dict[str, Any]] = []
    task_id = f"memory-update-preview-{await _claim_request(state.cache_service, user_id_hash, body.request_id)}"
    try:
        updated, telemetry = await run_memory_update_preview(
            task_id=task_id, model_id=POSTPROCESSING_MODEL_ID, memory_markdown=body.memory_markdown,
            messages=[m.model_dump() for m in body.messages], secrets_manager=state.secrets_manager,
            usage_callback=usage_events.append,
        )
        error: Optional[MemoryPreviewError] = None
    except MemoryPreviewError as exc:
        updated, telemetry, error = None, None, exc
    # Charge whatever was incurred, including unchanged and unusable results.
    buckets = priced_buckets(usage_events[-1] if usage_events else telemetry)
    if buckets:
        await charge_preview(billing, config_manager.get_model_pricing, user_id=user.id, user_id_hash=user_id_hash,
                             chat_id=body.chat_id, operation_id=task_id, buckets=buckets, message_id=body.message_id)
    if error is not None:
        if not buckets:
            await _release_unbilled_request(state.cache_service, user_id_hash, body.request_id)
        raise HTTPException(status_code=502, detail="Memory update preview failed")
    return {"status": "unchanged"} if updated is None else {"status": "updated", "body": updated}


class CreateDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120, repr=False)
    summary: str = Field(min_length=1, max_length=400, repr=False)
    user_message: str = Field(min_length=1, max_length=8_000, repr=False)
    assistant_response: str = Field(min_length=1, max_length=8_000, repr=False)
    request_id: Optional[str] = Field(default=None, pattern=REQUEST_ID_PATTERN)
    message_id: Optional[str] = Field(default=None, min_length=1, max_length=MESSAGE_ID_MAX_LENGTH)


@router.post("/create-draft", include_in_schema=False)
@limiter.limit("20/minute")
async def create_draft(request: Request, response: Response, body: CreateDraftRequest) -> Dict[str, Any]:
    """Generate one unsaved memory document (load_mode ask_first) from a recommendation; billed like update-preview.

    Returns {title, when_to_use, body, app_id}; app_id is one of the discovered app ids or null.
    """
    state = request.app.state
    user = await _user(request, response)
    if not await state.directus_service.chat.check_chat_ownership(body.chat_id, user.id):
        raise HTTPException(status_code=404, detail="Chat not found")
    user_id_hash = hashlib.sha256(user.id.encode()).hexdigest()
    billing = BillingService(state.cache_service, state.directus_service, state.encryption_service)
    if await billing.get_authoritative_personal_balance(user_id=user.id, user_id_hash=user_id_hash) < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits")
    usage_events: List[Dict[str, Any]] = []
    task_id = f"memory-create-draft-{await _claim_request(state.cache_service, user_id_hash, body.request_id)}"
    try:
        draft, telemetry = await run_memory_create_draft(
            task_id=task_id, model_id=POSTPROCESSING_MODEL_ID, title=body.title, summary=body.summary,
            user_message=body.user_message, assistant_response=body.assistant_response,
            secrets_manager=state.secrets_manager, usage_callback=usage_events.append,
            # The optional app_id is chosen within the same model call, only from these ids.
            app_ids=(getattr(state, "discovered_apps_metadata", None) or {}).keys(),
        )
        error: Optional[MemoryPreviewError] = None
    except MemoryPreviewError as exc:
        draft, telemetry, error = None, None, exc
    buckets = priced_buckets(usage_events[-1] if usage_events else telemetry)
    if buckets:
        await charge_preview(billing, config_manager.get_model_pricing, user_id=user.id, user_id_hash=user_id_hash,
                             chat_id=body.chat_id, operation_id=task_id, buckets=buckets, purpose="memory_create_draft",
                             message_id=body.message_id)
    if error is not None or draft is None:
        if not buckets:
            await _release_unbilled_request(state.cache_service, user_id_hash, body.request_id)
        raise HTTPException(status_code=502, detail="Memory draft generation failed")
    return draft


async def _user(request: Request, response: Response):
    state = request.app.state
    return await get_current_user(
        directus_service=state.directus_service, cache_service=state.cache_service,
        request=request, response=response, refresh_token=request.cookies.get("auth_refresh_token"),
    )
