# backend/core/api/app/routes/connected_account_actions.py
#
# Authenticated connected-account operation action routes.
# Undo remains client-mediated: callers provide a fresh short-lived token ref,
# and the server resolves it only for the exact journaled provider action.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.apps.ai.processing.connected_account_receipts import publish_connected_account_action_receipt
from backend.core.api.app.services.connected_account_operation_journal import (
    ConnectedAccountOperationJournalService,
)
from backend.core.api.app.services.token_broker import TokenBrokerService
from backend.shared.providers.google_calendar.client import GoogleCalendarClient
from backend.shared.providers.google_calendar.oauth import exchange_google_refresh_token

router = APIRouter(prefix="/v1/connected-accounts/actions", tags=["Connected Account Actions"])


class UndoConnectedAccountActionRequest(BaseModel):
    """Client-mediated undo request for one operation journal action."""

    turn_token_ref: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)


class UndoConnectedAccountActionResponse(BaseModel):
    """Safe undo result returned to web, CLI, and Apple clients."""

    action_id: str
    status: str
    undo_type: str
    events: list[dict[str, str]]
    receipt: dict[str, Any]


def get_directus_service(request: Request) -> Any:
    if not hasattr(request.app.state, "directus_service"):
        raise HTTPException(status_code=500, detail="Directus service unavailable")
    return request.app.state.directus_service


def get_cache_service(request: Request) -> Any:
    if not hasattr(request.app.state, "cache_service"):
        raise HTTPException(status_code=500, detail="Cache service unavailable")
    return request.app.state.cache_service


def get_encryption_service(request: Request) -> Any:
    if not hasattr(request.app.state, "encryption_service"):
        raise HTTPException(status_code=500, detail="Encryption service unavailable")
    return request.app.state.encryption_service


async def get_current_user_lazy(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
) -> Any:
    from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user

    return await get_current_user(
        directus_service=request.app.state.directus_service,
        cache_service=request.app.state.cache_service,
        refresh_token=refresh_token,
        response=response,
        request=request,
    )


def _require_vault_key_id(current_user: Any) -> str:
    vault_key_id = getattr(current_user, "vault_key_id", None)
    if not vault_key_id:
        raise HTTPException(status_code=403, detail="User vault key is required for connected-account undo")
    return str(vault_key_id)


@router.post("/{action_id}/undo", response_model=UndoConnectedAccountActionResponse)
async def undo_connected_account_action(
    action_id: str,
    body: UndoConnectedAccountActionRequest,
    current_user: Any = Depends(get_current_user_lazy),
    directus_service: Any = Depends(get_directus_service),
    cache_service: Any = Depends(get_cache_service),
    encryption_service: Any = Depends(get_encryption_service),
) -> UndoConnectedAccountActionResponse:
    """Undo a supported Calendar operation after journal and token-ref checks."""

    vault_key_id = _require_vault_key_id(current_user)
    journal = ConnectedAccountOperationJournalService(encryption_service=encryption_service)
    entry = await journal.load_owned_action(
        directus_service=directus_service,
        user_id=current_user.id,
        action_id=action_id,
    )
    if not entry:
        raise HTTPException(status_code=403, detail="Connected-account action not found for current user")
    if entry.get("decision") == "undo_success":
        raise HTTPException(status_code=409, detail="Connected-account action was already undone")
    if entry.get("app_id_hash") != _sha256("calendar"):
        raise HTTPException(status_code=422, detail="Connected-account action has no undo implementation")

    undo_payload = await journal.decrypt_undo_payload(entry=entry, user_vault_key_id=vault_key_id)
    events = undo_payload.get("events") if isinstance(undo_payload.get("events"), list) else []
    if not events:
        raise HTTPException(status_code=422, detail="Connected-account action has no undo implementation")

    undone_events: list[dict[str, str]] = []
    broker = TokenBrokerService(
        cache_service=cache_service,
        encryption_service=encryption_service,
        exchange_refresh_token=exchange_google_refresh_token,
    )
    token_ref_metadata = await broker.get_turn_token_ref_metadata(turn_token_ref=body.turn_token_ref)
    if not token_ref_metadata:
        raise HTTPException(status_code=403, detail="turn token ref expired or not found")
    token_ref_account_hash = _sha256(str(token_ref_metadata.get("connected_account_id") or ""))
    if token_ref_account_hash != entry.get("connected_account_id_hash"):
        raise HTTPException(status_code=403, detail="turn token ref account mismatch")

    access_token_handle: str | None = None
    try:
        for event in events:
            if not isinstance(event, dict):
                raise HTTPException(status_code=422, detail="Connected-account action has unsupported undo payload")
            calendar_id = str(event.get("calendar_id") or "")
            event_id = str(event.get("event_id") or "")
            if not calendar_id or not event_id:
                raise HTTPException(status_code=422, detail="Connected-account undo payload is incomplete")

            undo_type = str(event.get("undo_type") or "")
            broker_action = _broker_action_for_undo_type(undo_type)
            action_scope = {"calendar_id": calendar_id, "event_id": event_id}
            handle = await broker.exchange_turn_token_ref(
                turn_token_ref=body.turn_token_ref,
                user_id=current_user.id,
                user_vault_key_id=vault_key_id,
                chat_id=body.chat_id,
                message_id=body.message_id,
                app_id="calendar",
                action=broker_action,
                action_scope=action_scope,
            )
            access_token_handle = handle.access_token_handle
            access_token = await broker.resolve_access_token_handle(
                access_token_handle=handle.access_token_handle,
                user_id=current_user.id,
                user_vault_key_id=vault_key_id,
                chat_id=body.chat_id,
                message_id=body.message_id,
                app_id="calendar",
                action=broker_action,
                action_scope=action_scope,
            )
            event_result = await _execute_calendar_undo_event(
                calendar_client=GoogleCalendarClient(access_token=access_token),
                event=event,
                calendar_id=calendar_id,
                event_id=event_id,
            )
            undone_events.append(event_result)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    finally:
        await broker.delete_turn_artifacts(
            turn_token_ref=body.turn_token_ref,
            access_token_handle=access_token_handle,
        )

    receipt = {
        "action_id": action_id,
        "app_id": "calendar",
        "action": "undo",
        "decision": "undo_success",
        "undo_type": _receipt_undo_type(events),
        "event_count": len(undone_events),
    }
    await journal.mark_undone(
        directus_service=directus_service,
        entry=entry,
        receipt=receipt,
        user_vault_key_id=vault_key_id,
    )
    await publish_connected_account_action_receipt(
        cache_service=cache_service,
        user_id=current_user.id,
        payload={
            "chat_id": body.chat_id,
            "message_id": body.message_id,
            "action_id": action_id,
            "receipt": receipt,
        },
    )
    return UndoConnectedAccountActionResponse(
        action_id=action_id,
        status="undone",
        undo_type=str(receipt["undo_type"]),
        events=undone_events,
        receipt=receipt,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _broker_action_for_undo_type(undo_type: str) -> str:
    if undo_type == "delete_created_event":
        return "delete"
    if undo_type == "restore_updated_event":
        return "update"
    if undo_type == "recreate_deleted_event":
        return "write"
    raise HTTPException(status_code=422, detail="Connected-account action has unsupported undo payload")


async def _execute_calendar_undo_event(
    *,
    calendar_client: GoogleCalendarClient,
    event: dict[str, Any],
    calendar_id: str,
    event_id: str,
) -> dict[str, str]:
    undo_type = str(event.get("undo_type") or "")
    if undo_type == "delete_created_event":
        await calendar_client.delete_event(calendar_id=calendar_id, event_id=event_id)
        return {"calendar_id": calendar_id, "event_id": event_id, "status": "deleted"}

    snapshot = event.get("snapshot") if isinstance(event.get("snapshot"), dict) else {}
    title = str(snapshot.get("title") or snapshot.get("summary") or "")
    start = str(snapshot.get("start") or "")
    end = str(snapshot.get("end") or "")
    if not title or not start or not end:
        raise HTTPException(status_code=422, detail="Connected-account undo snapshot is incomplete")

    if undo_type == "restore_updated_event":
        updated = await calendar_client.update_event(
            calendar_id=calendar_id,
            event_id=event_id,
            title=title,
            start=start,
            end=end,
            location=snapshot.get("location"),
            description=snapshot.get("description"),
            attendees=snapshot.get("attendees") if isinstance(snapshot.get("attendees"), list) else None,
        )
        return {"calendar_id": calendar_id, "event_id": updated.id or event_id, "status": "restored"}

    if undo_type == "recreate_deleted_event":
        recreated = await calendar_client.create_event(
            calendar_id=calendar_id,
            title=title,
            start=start,
            end=end,
            location=snapshot.get("location"),
            description=snapshot.get("description"),
            attendees=snapshot.get("attendees") if isinstance(snapshot.get("attendees"), list) else None,
        )
        return {"calendar_id": calendar_id, "event_id": recreated.id or event_id, "status": "recreated"}

    raise HTTPException(status_code=422, detail="Connected-account action has unsupported undo payload")


def _receipt_undo_type(events: list[Any]) -> str:
    undo_types = sorted({str(event.get("undo_type") or "") for event in events if isinstance(event, dict)})
    if len(undo_types) == 1:
        return undo_types[0]
    return "mixed"
