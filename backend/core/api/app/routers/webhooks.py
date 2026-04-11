# backend/core/api/app/routers/webhooks.py
#
# Webhook management (CRUD) and incoming webhook handler.
#
# Two distinct auth contexts:
# - CRUD endpoints: JWT auth (authenticated user managing their keys)
# - POST /incoming: Webhook key auth (external service triggering a chat)
#
# Incoming flow (mirrors the reminder pattern — see backend/apps/reminder/tasks.py):
#   1. Auth + rate-limit + dedupe the webhook key.
#   2. Pre-create the chat in Directus so later AI persistence has a row to attach to.
#   3. Broadcast a `webhook_chat` WebSocket event with PLAINTEXT content to any online
#      device for that user. The frontend handler encrypts with a freshly-generated
#      chat key and persists via `chat_system_message_added`, matching reminder_fired.
#   4. If the user is offline, queue an email notification + cache a vault-encrypted
#      copy of the pending chat for 24h so the UI can recover it on reconnect.
#   5. Unless the key has `require_confirmation=True`, unconditionally dispatch an
#      AI ask-request so the assistant replies server-side regardless of presence.
#
# Architecture: docs/architecture/webhooks.md
# Related: api_key_auth.py, webhook_auth.py, cache_webhook_mixin.py

import hashlib
import json
import logging
import time
import uuid
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.models.user import User
from backend.core.api.app.utils.webhook_auth import verify_webhook_key
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/webhooks",
    tags=["Webhooks"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

# --- CRUD models (JWT-authenticated) ---

class WebhookCreateRequest(BaseModel):
    """Request to create a new webhook key. Key hash + encrypted fields are
    generated client-side (zero-knowledge pattern matching API keys)."""
    encrypted_name: str = Field(..., min_length=1, max_length=512)
    webhook_key_hash: str = Field(..., min_length=64, max_length=64,
                                  description="SHA-256 hex hash of the full webhook key")
    encrypted_key_prefix: str = Field(..., min_length=1, max_length=512)
    direction: str = Field(default="incoming", pattern="^(incoming|outgoing)$")
    permissions: List[str] = Field(default=["trigger_chat"])
    require_confirmation: bool = Field(default=False)
    expires_at: Optional[str] = Field(default=None, description="ISO 8601 timestamp")


class WebhookResponse(BaseModel):
    """Response for a single webhook record (encrypted fields excluded —
    client decrypts via master key)."""
    id: str
    direction: str = "incoming"
    permissions: List[str] = []
    require_confirmation: bool = False
    is_active: bool = True
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None


class WebhookListResponse(BaseModel):
    webhooks: List[WebhookResponse]


class WebhookUpdateRequest(BaseModel):
    """Partial update for a webhook. Only the supplied fields are changed."""
    is_active: Optional[bool] = None
    require_confirmation: Optional[bool] = None
    encrypted_name: Optional[str] = Field(default=None, max_length=512)


# --- Incoming webhook models (webhook-key authenticated) ---

class WebhookIncomingRequest(BaseModel):
    """Payload sent by external services to trigger a chat."""
    message: str = Field(
        ...,
        min_length=1,
        max_length=50_000,
        description="The message content. Will be stored as a system message in a new chat.",
    )


class WebhookIncomingResponse(BaseModel):
    chat_id: str
    status: str  # "processing" or "pending_confirmation"


# ---------------------------------------------------------------------------
# Helper: max webhooks per user
# ---------------------------------------------------------------------------

MAX_WEBHOOKS_PER_USER = 10
ALLOWED_PERMISSIONS = {"trigger_chat"}

# Pending webhook chat cache TTL (24 hours)
PENDING_WEBHOOK_CHAT_TTL = 86400

# Prompt wrapper passed to the AI as the "user" turn when a webhook fires.
# Mirrors REMINDER_TASK_TEMPLATE in backend/apps/reminder/tasks.py so webhook
# chats carry the same "task triggered, just act" signal to the LLM.
WEBHOOK_TASK_TEMPLATE = (
    "[Incoming Webhook — Task Triggered]\n\n"
    "Task: {message}\n\n"
    "Carry out this task now. Do not explain that a webhook fired unless the user "
    "explicitly asks."
)


# ---------------------------------------------------------------------------
# CRUD endpoints (JWT auth — user managing their own webhook keys)
# ---------------------------------------------------------------------------

@router.post("", response_model=WebhookResponse)
@limiter.limit("5/minute")
async def create_webhook(
    request: Request,
    payload: WebhookCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """Create a new incoming webhook key for the current user."""
    directus_service: DirectusService = request.app.state.directus_service

    # Validate permissions
    for perm in payload.permissions:
        if perm not in ALLOWED_PERMISSIONS:
            raise HTTPException(status_code=400, detail=f"Unknown permission: {perm}")

    # Only incoming webhooks supported for now
    if payload.direction != "incoming":
        raise HTTPException(status_code=400, detail="Only 'incoming' webhooks are supported currently")

    # Validate key hash format (64 hex chars = SHA-256)
    if len(payload.webhook_key_hash) != 64:
        raise HTTPException(status_code=400, detail="Invalid webhook key hash (must be 64 hex characters)")

    # Check existing count
    existing = await directus_service.get_user_webhooks_by_user_id(current_user.id)
    if len(existing) >= MAX_WEBHOOKS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum number of webhook keys reached ({MAX_WEBHOOKS_PER_USER})",
        )

    # Duplicate check
    existing_key = await directus_service.get_webhook_by_key_hash(payload.webhook_key_hash)
    if existing_key:
        raise HTTPException(status_code=400, detail="Webhook key hash already exists")

    hashed_user_id = hashlib.sha256(current_user.id.encode()).hexdigest()

    created = await directus_service.create_webhook(
        user_id=current_user.id,
        hashed_user_id=hashed_user_id,
        key_hash=payload.webhook_key_hash,
        encrypted_key_prefix=payload.encrypted_key_prefix,
        encrypted_name=payload.encrypted_name,
        direction=payload.direction,
        permissions=payload.permissions,
        require_confirmation=payload.require_confirmation,
        expires_at=payload.expires_at,
    )

    if not created:
        raise HTTPException(status_code=500, detail="Failed to create webhook key")

    logger.info(f"Created webhook key for user {current_user.id} (direction={payload.direction})")

    return WebhookResponse(
        id=created.get("id", ""),
        direction=payload.direction,
        permissions=payload.permissions,
        require_confirmation=payload.require_confirmation,
        is_active=True,
        created_at=created.get("created_at"),
        expires_at=created.get("expires_at"),
        last_used_at=None,
    )


@router.get("", response_model=WebhookListResponse)
@limiter.limit("30/minute")
async def list_webhooks(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """List all webhook keys for the current user."""
    directus_service: DirectusService = request.app.state.directus_service
    items = await directus_service.get_user_webhooks_by_user_id(current_user.id)

    webhooks = []
    for item in items:
        webhooks.append(WebhookResponse(
            id=item.get("id", ""),
            direction=item.get("direction", "incoming"),
            permissions=item.get("permissions") or [],
            require_confirmation=bool(item.get("require_confirmation", False)),
            is_active=bool(item.get("is_active", True)),
            created_at=item.get("created_at"),
            expires_at=item.get("expires_at"),
            last_used_at=item.get("last_used_at"),
        ))

    return WebhookListResponse(webhooks=webhooks)


@router.patch("/{webhook_id}", response_model=WebhookResponse)
@limiter.limit("10/minute")
async def update_webhook(
    request: Request,
    webhook_id: str,
    payload: WebhookUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """Update a webhook key's settings (active status, confirmation requirement, name)."""
    directus_service: DirectusService = request.app.state.directus_service

    # Verify ownership: fetch user's webhooks and check the target is among them
    user_webhooks = await directus_service.get_user_webhooks_by_user_id(current_user.id)
    target = next((w for w in user_webhooks if w.get("id") == webhook_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Webhook not found")

    # Build update payload (only include non-None fields)
    update_data: Dict[str, Any] = {}
    if payload.is_active is not None:
        update_data["is_active"] = payload.is_active
    if payload.require_confirmation is not None:
        update_data["require_confirmation"] = payload.require_confirmation
    if payload.encrypted_name is not None:
        update_data["encrypted_name"] = payload.encrypted_name

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    success = await directus_service.update_webhook(webhook_id, update_data)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update webhook")

    # Invalidate cache for this key
    cache_service: CacheService = request.app.state.cache_service
    key_hash = target.get("key_hash")
    if key_hash:
        await cache_service.delete(f"webhook_key_record:{key_hash}")

    # Return updated record
    return WebhookResponse(
        id=webhook_id,
        direction=target.get("direction", "incoming"),
        permissions=target.get("permissions") or [],
        require_confirmation=payload.require_confirmation if payload.require_confirmation is not None else target.get("require_confirmation", False),
        is_active=payload.is_active if payload.is_active is not None else target.get("is_active", True),
        created_at=target.get("created_at"),
        expires_at=target.get("expires_at"),
        last_used_at=target.get("last_used_at"),
    )


@router.delete("/{webhook_id}")
@limiter.limit("10/minute")
async def delete_webhook(
    request: Request,
    webhook_id: str,
    current_user: User = Depends(get_current_user),
):
    """Revoke and delete a webhook key."""
    directus_service: DirectusService = request.app.state.directus_service

    # Verify ownership
    user_webhooks = await directus_service.get_user_webhooks_by_user_id(current_user.id)
    target = next((w for w in user_webhooks if w.get("id") == webhook_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Webhook not found")

    success = await directus_service.delete_webhook(webhook_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete webhook")

    # Invalidate cache for this key
    cache_service: CacheService = request.app.state.cache_service
    key_hash = target.get("key_hash")
    if key_hash:
        await cache_service.delete(f"webhook_key_record:{key_hash}")

    logger.info(f"Deleted webhook {webhook_id} for user {current_user.id}")
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Incoming webhook endpoint (webhook key auth)
# ---------------------------------------------------------------------------

@router.post(
    "/incoming",
    response_model=WebhookIncomingResponse,
    summary="Trigger a new chat via webhook",
    description=(
        "External services call this endpoint to create a new chat with a system message. "
        "Authenticate with a webhook key: `Authorization: Bearer wh-...`"
    ),
)
@limiter.limit("10/minute")
async def webhook_incoming(
    request: Request,
    payload: WebhookIncomingRequest,
    webhook_info: Dict[str, Any] = Depends(verify_webhook_key),
):
    """
    Create a new chat triggered by an incoming webhook.

    Mirrors the reminder-fired flow (backend/apps/reminder/tasks.py):
      1. Pre-create a minimal chat row in Directus so the AI response has something
         to attach to.
      2. Broadcast a `webhook_chat` WebSocket event carrying PLAINTEXT content —
         the WS channel is already TLS + session-authenticated, and the frontend
         is responsible for chat-key-encrypting and persisting via
         `chat_system_message_added`.
      3. Register the chat in the user's chat_ids_versions sorted set.
      4. Offline safety net: vault-encrypt a copy into a 24h pending cache and
         queue an email notification so the user is alerted.
      5. Unless `require_confirmation` is set on the webhook key, dispatch an AI
         ask-request server-side so the assistant runs regardless of whether
         any device is online.
    """
    user_id = webhook_info["user_id"]
    hashed_user_id = webhook_info["hashed_user_id"]
    require_confirmation = webhook_info["require_confirmation"]
    webhook_id = webhook_info["webhook_id"]

    cache_service: CacheService = request.app.state.cache_service
    encryption_service = request.app.state.encryption_service
    directus_service: DirectusService = request.app.state.directus_service

    # --- Get user's vault key ID (needed for the offline-delivery safety net) ---
    cached_user = await cache_service.get_user_by_id(user_id)
    vault_key_id = None
    if cached_user:
        vault_key_id = cached_user.get("vault_key_id")

    if not vault_key_id:
        # Directus fallback (never treat cache miss as terminal)
        try:
            success, user_profile, _ = await directus_service.get_user_profile(user_id)
            if success and user_profile:
                vault_key_id = user_profile.get("vault_key_id")
        except Exception as e:
            logger.error(f"Failed to fetch user profile for webhook chat: {e}")

    if not vault_key_id:
        logger.error(f"No vault_key_id for user {user_id[:8]}... — cannot create webhook chat")
        raise HTTPException(status_code=500, detail="User encryption not configured")

    # --- Generate IDs ---
    chat_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    now_ts = int(time.time())
    status_value = "pending_confirmation" if require_confirmation else "processing"

    # --- Pre-create chat in Directus (mirrors reminder tasks.py:234-253) ---
    # The AI response persistence flow needs a chat row to exist. The frontend
    # handler will fill in the real encrypted_title once it generates the chat key.
    try:
        minimal_chat_metadata = {
            "chat_id": chat_id,
            "hashed_user_id": hashed_user_id,
            "title_v": 0,
            "messages_v": 0,
            "last_edited_overall_timestamp": now_ts,
            "last_message_timestamp": now_ts,
            "unread_count": 1,
        }
        created_data, is_duplicate = await directus_service.chat.create_chat_in_directus(
            minimal_chat_metadata
        )
        if created_data:
            logger.info(f"Pre-created chat {chat_id} in Directus for webhook {webhook_id}")
        elif is_duplicate:
            logger.debug(f"Chat {chat_id} already exists (race), continuing")
        else:
            logger.warning(f"Failed to pre-create chat {chat_id} in Directus, continuing anyway")
    except Exception as create_err:
        logger.warning(f"Error pre-creating chat {chat_id}: {create_err}, continuing anyway")

    # --- Register chat in user's chat_ids_versions for ownership checks ---
    await cache_service.add_chat_to_ids_versions(user_id, chat_id, now_ts)

    # --- Vault-encrypt a copy for the offline safety net only ---
    # Online users get plaintext via the WS event below; this copy is just so the
    # frontend can recover the chat via the pending cache after a cold-boot.
    try:
        encrypted_content, key_version = await encryption_service.encrypt_with_user_key(
            payload.message, vault_key_id
        )
    except Exception as e:
        logger.error(f"Vault encryption failed for webhook chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Encryption failed")

    webhook_pending_record = {
        "chat_id": chat_id,
        "message_id": message_id,
        "webhook_id": webhook_id,
        "user_id": user_id,
        "hashed_user_id": hashed_user_id,
        "encrypted_content": encrypted_content,
        "vault_key_version": key_version,
        "role": "system",
        "status": status_value,
        "created_at": now_ts,
        "source": "webhook",
    }
    pending_key = f"webhook_pending_chat:{user_id}:{chat_id}"
    try:
        await cache_service.set(
            pending_key,
            json.dumps(webhook_pending_record),
            ttl=PENDING_WEBHOOK_CHAT_TTL,
        )
    except Exception as e:
        logger.warning(f"Failed to cache pending webhook chat record: {e}")
        # Non-fatal — online delivery path doesn't depend on this cache.

    # --- Broadcast plaintext via WebSocket (reminder_fired pattern) ---
    user_is_online = False
    try:
        from backend.core.api.app.routes.websockets import manager
        user_is_online = manager.is_user_active(user_id)

        if user_is_online:
            await manager.broadcast_to_user(
                message={
                    "type": "webhook_chat",
                    "event": "webhook_chat",
                    "payload": {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "content": payload.message,  # plaintext — frontend encrypts with chat key
                        "status": status_value,
                        "source": "webhook",
                        "webhook_id": webhook_id,
                        "fired_at": now_ts,
                    },
                },
                user_id=user_id,
            )
            logger.info(
                f"Delivered webhook chat {chat_id} to online user {user_id[:8]}... "
                f"(status={status_value})"
            )
    except Exception as e:
        logger.warning(f"Failed to broadcast webhook_chat WS event: {e}")
        # Non-fatal — offline delivery path still fires below.

    # --- Offline notification (only when no device was live to receive it) ---
    if not user_is_online:
        _queue_webhook_email_notification(
            request=request,
            user_id=user_id,
            chat_id=chat_id,
            cached_user=cached_user,
            vault_key_id=vault_key_id,
            encryption_service=encryption_service,
        )
        logger.info(
            f"User {user_id[:8]}... offline — webhook chat {chat_id} queued for "
            f"email + pending cache (status={status_value})"
        )

    # --- Dispatch AI response server-side (unconditional unless approval required) ---
    if not require_confirmation:
        try:
            await _dispatch_webhook_ai_request(
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                message=payload.message,
                cache_service=cache_service,
            )
        except Exception as ai_error:
            logger.warning(
                f"Failed to dispatch AI request for webhook chat {chat_id}: {ai_error}",
                exc_info=True,
            )
            # Non-fatal — the chat + system message still exist; user can reply manually.

    return WebhookIncomingResponse(chat_id=chat_id, status=status_value)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _queue_webhook_email_notification(
    request: Request,
    user_id: str,
    chat_id: str,
    cached_user: Optional[Dict[str, Any]],
    vault_key_id: str,
    encryption_service: Any,
) -> None:
    """
    Queue a Celery task to send an email notification for a webhook-triggered chat.

    Follows the same pattern as ai_response_notification_email_task:
    - Respects email_notifications_enabled + webhookChats preference
    - Decrypts notification email via vault
    - Non-fatal: errors are logged but never propagate to the caller
    """
    try:
        if not cached_user:
            logger.debug(f"No cached user data for webhook email notification (user {user_id[:8]}...)")
            return

        # Check notification preferences
        email_enabled = cached_user.get("email_notifications_enabled", False)
        if not email_enabled:
            logger.debug(f"Email notifications disabled for user {user_id[:8]}...")
            return

        prefs = cached_user.get("email_notification_preferences") or {}
        webhook_emails = prefs.get("webhookChats", True)  # Default: opt-in
        if not webhook_emails:
            logger.debug(f"Webhook chat emails disabled for user {user_id[:8]}...")
            return

        encrypted_email = cached_user.get("encrypted_notification_email")
        if not encrypted_email:
            logger.debug(f"No notification email for user {user_id[:8]}...")
            return

        language = cached_user.get("language", "en") or "en"
        darkmode = bool(cached_user.get("darkmode", False))

        # Dispatch Celery email task — the task itself handles decryption.
        from backend.core.api.app.tasks.celery_config import app as celery_app

        celery_app.send_task(
            name="app.tasks.email_tasks.webhook_chat_notification_email_task.send_webhook_chat_notification",
            kwargs={
                "user_id": user_id,
                "chat_id": chat_id,
                "language": language,
                "darkmode": darkmode,
            },
            queue="email",
        )
        logger.info(f"Queued webhook chat email notification for user {user_id[:8]}...")

    except Exception as e:
        logger.warning(f"Failed to queue webhook email notification: {e}")


# ---------------------------------------------------------------------------
# AI dispatch helper (server-side assistant run, presence-independent)
# ---------------------------------------------------------------------------

async def _dispatch_webhook_ai_request(
    user_id: str,
    chat_id: str,
    message_id: str,
    message: str,
    cache_service: CacheService,
) -> None:
    """
    Dispatch an AI ask request for a fired webhook.

    Mirrors backend/apps/reminder/tasks.py::_dispatch_reminder_ai_request.
    The webhook chat is a brand-new chat, so there is no prior message history —
    we build a single-turn history containing the wrapped task prompt and let the
    `ai/ask` skill take over. The assistant response is persisted by the AI
    pipeline to Directus whether or not any device is online.
    """
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

    task_content = WEBHOOK_TASK_TEMPLATE.format(message=message)
    message_history = [
        {
            "content": task_content,
            "role": "user",
            "created_at": int(time.time()),
        }
    ]

    user_preferences: Dict[str, Any] = {}
    try:
        user_timezone = await cache_service.get_user_timezone(user_id)
        if user_timezone:
            user_preferences["timezone"] = user_timezone
    except Exception as tz_err:
        logger.debug(f"Could not fetch user timezone for webhook AI dispatch: {tz_err}")

    ask_request = {
        "chat_id": chat_id,
        "message_id": message_id,
        "user_id": user_id,
        "user_id_hash": user_id_hash,
        "message_history": message_history,
        "chat_has_title": False,  # New chat, title not yet set.
        "mate_id": None,
        "active_focus_id": None,
        "user_preferences": user_preferences,
        "app_settings_memories_metadata": None,
    }

    # Dispatch via in-process SkillRegistry (same pattern as reminder AI dispatch;
    # the API container registry has the `ai` app registered).
    from backend.core.api.app.services.skill_registry import get_global_registry

    response_data = await get_global_registry().dispatch_skill("ai", "ask", ask_request)
    ai_task_id = response_data.get("task_id") if isinstance(response_data, dict) else None

    if ai_task_id:
        await cache_service.set_active_ai_task(chat_id, ai_task_id)
        logger.info(
            f"Dispatched AI ask request for webhook chat {chat_id} (task_id={ai_task_id})"
        )
    else:
        logger.warning(f"ai.ask returned no task_id for webhook chat {chat_id}")
