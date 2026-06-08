# backend/core/api/app/routes/application_preview.py
#
# Backend contract helpers for generated application live previews.
# This first slice validates preview-origin isolation, viewer-scoped session
# records, timeout policy, and minute-rounded billing before the later E2B
# worker and preview gateway endpoints are wired in.

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import time
import uuid
from typing import Any, Awaitable, Callable, Iterable, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.utils.encryption import EncryptionService
from backend.shared.providers.e2b_application_preview import (
    ApplicationPreviewEntrypoint,
    ApplicationPreviewFile,
    ApplicationPreviewPlanningError,
    plan_application_preview_startup,
)


router = APIRouter(prefix="/v1/applications", tags=["Application Preview"])

APPLICATION_PREVIEW_CREDITS_PER_STARTED_MINUTE = 5
APPLICATION_PREVIEW_IDLE_TIMEOUT_SECONDS = 5 * 60
APPLICATION_PREVIEW_HARD_TIMEOUT_SECONDS = 30 * 60
APPLICATION_PREVIEW_SESSION_TTL_SECONDS = APPLICATION_PREVIEW_HARD_TIMEOUT_SECONDS + 10 * 60
LOCAL_PREVIEW_HOSTS = {"localhost", "127.0.0.1", "::1"}
CLIENT_CONTENT_REQUIRED_CODE = "client_content_required"
PayloadResolver = Callable[[str, Any, Any, Any, Any, Any], Awaitable[dict[str, Any]]]


class ApplicationPreviewConfigError(ValueError):
    """Raised when application live previews are unsafe or unavailable."""


class ApplicationPreviewStartRequest(BaseModel):
    chat_id: str = Field(min_length=1)
    shared_context: str | None = None
    requested_runtime: str | None = None


class ApplicationPreviewStartResponse(BaseModel):
    session_id: str
    preview_url: str
    status: str
    credits_per_minute: int = APPLICATION_PREVIEW_CREDITS_PER_STARTED_MINUTE


class ApplicationPreviewStopResponse(BaseModel):
    session_id: str
    status: str
    charged_credits: int | None = None


class ApplicationPreviewEvent(BaseModel):
    kind: str
    text: str
    timestamp: float


class ApplicationPreviewStatusResponse(BaseModel):
    session_id: str
    status: str
    events: list[ApplicationPreviewEvent] = Field(default_factory=list)
    error: str | None = None
    charged_credits: int | None = None
    latest_screenshot_url: str | None = None


def build_application_preview_worker_payload(
    *,
    application_embed_id: str,
    application_content: dict[str, Any],
    child_contents: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if str(application_content.get("type") or "").lower() != "application":
        raise HTTPException(status_code=400, detail="Target embed is not an application")

    file_refs = application_content.get("file_refs")
    entrypoints = application_content.get("entrypoints")
    if not isinstance(file_refs, list) or not file_refs:
        raise HTTPException(status_code=400, detail="Application embed has no file references")
    if not isinstance(entrypoints, list) or not entrypoints:
        raise HTTPException(status_code=400, detail="Application embed has no preview entrypoints")

    files = [_worker_file_from_ref(ref, child_contents) for ref in file_refs if isinstance(ref, dict)]
    preview_entrypoints = [_worker_entrypoint(entrypoint) for entrypoint in entrypoints if isinstance(entrypoint, dict)]
    try:
        plan_application_preview_startup(
            files=[ApplicationPreviewFile(path=str(file["path"]), content=str(file["content"])) for file in files],
            entrypoints=[ApplicationPreviewEntrypoint(**entrypoint) for entrypoint in preview_entrypoints],
        )
    except ApplicationPreviewPlanningError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "application_embed_id": application_embed_id,
        "framework": application_content.get("framework"),
        "runtime": application_content.get("runtime"),
        "files": files,
        "entrypoints": preview_entrypoints,
    }


def build_application_preview_worker_payload_from_shared_context(
    *,
    application_embed_id: str,
    shared_context: str,
) -> dict[str, Any]:
    try:
        context = json.loads(shared_context)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Shared application preview context is invalid") from exc

    if not isinstance(context, dict):
        raise HTTPException(status_code=400, detail="Shared application preview context must be an object")
    if context.get("application_embed_id") not in {None, application_embed_id}:
        raise HTTPException(status_code=400, detail="Shared application preview context does not match the requested embed")

    application_content = context.get("application_content")
    child_contents = context.get("child_contents")
    if not isinstance(application_content, dict) or not isinstance(child_contents, dict):
        raise HTTPException(status_code=400, detail="Shared application preview context is missing application files")

    normalized_child_contents = {
        str(embed_id): content
        for embed_id, content in child_contents.items()
        if isinstance(content, dict)
    }
    return build_application_preview_worker_payload(
        application_embed_id=application_embed_id,
        application_content=application_content,
        child_contents=normalized_child_contents,
    )


def _worker_file_from_ref(ref: dict[str, Any], child_contents: dict[str, dict[str, Any]]) -> dict[str, str]:
    embed_id = str(ref.get("embed_id") or "")
    path = str(ref.get("path") or "")
    role = str(ref.get("role") or "source")
    child = child_contents.get(embed_id)
    if not embed_id or child is None:
        raise HTTPException(status_code=409, detail="Application child file is not available for preview")
    if str(child.get("type") or "").lower() not in {"code", "code-code"}:
        raise HTTPException(status_code=400, detail="Application file reference must point to a code embed")
    code = child.get("code")
    if not isinstance(code, str) or not code:
        raise HTTPException(status_code=400, detail="Application child code is empty")
    return {"path": path, "content": code, "source_embed_id": embed_id, "role": role}


def _worker_entrypoint(entrypoint: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(entrypoint.get("name") or ""),
        "command": str(entrypoint.get("command") or ""),
        "port": int(entrypoint.get("port") or 0),
    }


def get_cache_service(request: Request) -> Any:
    return request.app.state.cache_service


def get_directus_service(request: Request) -> Any:
    return request.app.state.directus_service


def get_encryption_service(request: Request) -> EncryptionService:
    return request.app.state.encryption_service


def send_application_preview_task(name: str, args: list[Any], queue: str) -> Any:
    from backend.core.api.app.tasks.celery_config import app as celery_app

    return celery_app.send_task(name, args=args, queue=queue)


async def get_application_preview_current_user(
    directus_service: Any = Depends(get_directus_service),
    cache_service: Any = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False),
) -> Any:
    from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user

    return await get_current_user(directus_service, cache_service, refresh_token)


def _decode_toon_content(plaintext_toon: str) -> dict[str, Any] | None:
    try:
        from toon_format import decode as toon_decode

        decoded = toon_decode(plaintext_toon)
    except ImportError:
        decoded = None
    except Exception:
        decoded = None

    if not isinstance(decoded, dict):
        try:
            decoded = json.loads(plaintext_toon)
        except json.JSONDecodeError:
            return None
    return decoded if isinstance(decoded, dict) else None


async def _load_cached_embed_content(
    *,
    embed_id: str,
    current_user: Any,
    cache_service: Any,
    directus_service: Any,
    encryption_service: EncryptionService,
) -> dict[str, Any] | None:
    vault_key_id = getattr(current_user, "vault_key_id", None)
    if not vault_key_id:
        return None

    client = await cache_service.client
    raw_embed = await client.get(f"embed:{embed_id}")
    if not raw_embed:
        return None

    try:
        embed_data = json.loads(raw_embed.decode("utf-8") if isinstance(raw_embed, bytes) else raw_embed)
    except json.JSONDecodeError:
        return None

    encrypted_content = embed_data.get("encrypted_content") if isinstance(embed_data, dict) else None
    if not isinstance(encrypted_content, str) or not encrypted_content:
        return None

    plaintext_toon = await encryption_service.decrypt_with_user_key(encrypted_content, vault_key_id)
    return _decode_toon_content(plaintext_toon) if plaintext_toon else None


async def _strict_owner_chat_access(
    *,
    application_embed_id: str,
    body: ApplicationPreviewStartRequest,
    current_user: Any,
    cache_service: Any,
    directus_service: Any,
) -> None:
    embed_ids = await cache_service.get_chat_embed_ids(body.chat_id) if hasattr(cache_service, "get_chat_embed_ids") else []
    if embed_ids and application_embed_id not in embed_ids:
        raise HTTPException(status_code=404, detail="Application embed is not available in this chat")

    metadata = None
    if hasattr(cache_service, "get_embed_from_cache"):
        metadata = await cache_service.get_embed_from_cache(application_embed_id)
    if not metadata and hasattr(directus_service, "embed"):
        metadata = await directus_service.embed.get_embed_by_id(application_embed_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Application embed is not available")

    expected_user_hash = _sha256_hex(current_user.id)
    expected_chat_hash = _sha256_hex(body.chat_id)
    if metadata.get("hashed_user_id") != expected_user_hash or metadata.get("hashed_chat_id") != expected_chat_hash:
        raise HTTPException(status_code=403, detail="Application embed is not available to this viewer")


async def collect_application_preview_worker_payload(
    *,
    application_embed_id: str,
    body: ApplicationPreviewStartRequest,
    current_user: Any,
    cache_service: Any,
    directus_service: Any,
    encryption_service: EncryptionService,
) -> dict[str, Any]:
    if body.shared_context:
        return build_application_preview_worker_payload_from_shared_context(
            application_embed_id=application_embed_id,
            shared_context=body.shared_context,
        )

    await _strict_owner_chat_access(
        application_embed_id=application_embed_id,
        body=body,
        current_user=current_user,
        cache_service=cache_service,
        directus_service=directus_service,
    )

    application_content = await _load_cached_embed_content(
        embed_id=application_embed_id,
        current_user=current_user,
        cache_service=cache_service,
        directus_service=directus_service,
        encryption_service=encryption_service,
    )
    if not application_content:
        raise HTTPException(
            status_code=409,
            detail={
                "code": CLIENT_CONTENT_REQUIRED_CODE,
                "message": "Application content is not in the recent server cache; reopen the chat from this device and try again.",
            },
        )

    file_refs = application_content.get("file_refs")
    child_ids = [str(ref.get("embed_id") or "") for ref in file_refs if isinstance(ref, dict)] if isinstance(file_refs, list) else []
    child_contents: dict[str, dict[str, Any]] = {}
    for child_id in child_ids:
        if not child_id:
            continue
        child_content = await _load_cached_embed_content(
            embed_id=child_id,
            current_user=current_user,
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
        )
        if child_content:
            child_contents[child_id] = child_content

    return build_application_preview_worker_payload(
        application_embed_id=application_embed_id,
        application_content=application_content,
        child_contents=child_contents,
    )


async def resolve_application_preview_worker_payload(
    *,
    request: Request,
    application_embed_id: str,
    body: ApplicationPreviewStartRequest,
    current_user: Any,
    cache_service: Any,
    directus_service: Any,
    encryption_service: EncryptionService,
) -> dict[str, Any]:
    resolver: PayloadResolver | None = getattr(request.app.state, "application_preview_payload_resolver", None)
    if resolver:
        return await resolver(application_embed_id, body, current_user, cache_service, directus_service, encryption_service)
    return await collect_application_preview_worker_payload(
        application_embed_id=application_embed_id,
        body=body,
        current_user=current_user,
        cache_service=cache_service,
        directus_service=directus_service,
        encryption_service=encryption_service,
    )


def application_preview_session_key(session_id: str) -> str:
    return f"application_preview_session:{session_id}"


def calculate_preview_charge_credits(duration_seconds: float) -> int:
    if duration_seconds <= 0:
        return 0
    charged_minutes = max(1, math.ceil(duration_seconds / 60))
    return charged_minutes * APPLICATION_PREVIEW_CREDITS_PER_STARTED_MINUTE


def hash_preview_gateway_token(preview_token: str) -> str:
    return _sha256_hex(preview_token)


def generate_preview_gateway_token() -> str:
    return secrets.token_urlsafe(32)


def build_preview_session_record(
    *,
    session_id: str,
    viewer_user_id: str,
    chat_id: str,
    application_embed_id: str,
    now: float,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "viewer_user_id": viewer_user_id,
        "viewer_user_id_hash": _sha256_hex(viewer_user_id),
        "chat_id_hash": _sha256_hex(chat_id),
        "application_embed_id": application_embed_id,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "idle_deadline": now + APPLICATION_PREVIEW_IDLE_TIMEOUT_SECONDS,
        "hard_deadline": now + APPLICATION_PREVIEW_HARD_TIMEOUT_SECONDS,
        "billing_state": {
            "credits_per_started_minute": APPLICATION_PREVIEW_CREDITS_PER_STARTED_MINUTE,
            "charged_credits": 0,
            "charged_minutes": 0,
        },
    }


def application_preview_url(preview_origin: str, session_id: str, path: str = "") -> str:
    return application_preview_url_with_token(preview_origin, session_id, "", path)


def application_preview_url_with_token(preview_origin: str, session_id: str, preview_token: str, path: str = "") -> str:
    normalized_path = path.strip("/")
    token_segment = f"/{preview_token.strip('/')}" if preview_token else ""
    suffix = f"/{normalized_path}" if normalized_path else "/"
    return f"{preview_origin}/p/{session_id}{token_segment}{suffix}"


async def create_application_preview_session(
    *,
    cache_service: Any,
    session_id: str,
    application_embed_id: str,
    body: ApplicationPreviewStartRequest,
    current_user: Any,
    preview_origin: str,
    now: float,
    preview_token: str | None = None,
) -> ApplicationPreviewStartResponse:
    if getattr(current_user, "credits", 0) < APPLICATION_PREVIEW_CREDITS_PER_STARTED_MINUTE:
        raise HTTPException(status_code=402, detail="Not enough credits to start application preview")

    record = build_preview_session_record(
        session_id=session_id,
        viewer_user_id=current_user.id,
        chat_id=body.chat_id,
        application_embed_id=application_embed_id,
        now=now,
    )
    token = preview_token or generate_preview_gateway_token()
    preview_url = application_preview_url_with_token(preview_origin, session_id, token)
    record.update(
        {
            "preview_token_hash": hash_preview_gateway_token(token),
            "requested_runtime": body.requested_runtime,
            "uses_client_shared_context": bool(body.shared_context),
            "events": [{"kind": "status", "text": "Queued application preview...", "timestamp": now}],
        }
    )

    client = await cache_service.client
    await client.set(
        application_preview_session_key(session_id),
        json.dumps(record),
        ex=APPLICATION_PREVIEW_SESSION_TTL_SECONDS,
    )
    return ApplicationPreviewStartResponse(session_id=session_id, preview_url=preview_url, status="queued")


async def create_application_preview_session_and_dispatch(
    *,
    cache_service: Any,
    session_id: str,
    application_embed_id: str,
    body: ApplicationPreviewStartRequest,
    current_user: Any,
    preview_origin: str,
    worker_payload: dict[str, Any],
    task_sender: Any,
    now: float,
    preview_token: str | None = None,
) -> ApplicationPreviewStartResponse:
    response = await create_application_preview_session(
        cache_service=cache_service,
        session_id=session_id,
        application_embed_id=application_embed_id,
        body=body,
        current_user=current_user,
        preview_origin=preview_origin,
        now=now,
        preview_token=preview_token,
    )
    task_sender("code.run_application_preview", args=[session_id, worker_payload], queue="app_code")
    return response


async def get_application_preview_session(
    cache_service: Any,
    session_id: str,
    current_user: Any,
) -> dict[str, Any]:
    client = await cache_service.client
    raw = await client.get(application_preview_session_key(session_id))
    if not raw:
        raise HTTPException(status_code=404, detail="Application preview session not found or expired")

    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    expected_user_hash = _sha256_hex(current_user.id)
    if data.get("viewer_user_id_hash") != expected_user_hash:
        raise HTTPException(status_code=404, detail="Application preview session not found or expired")
    return data


def build_application_preview_status_response(data: dict[str, Any]) -> ApplicationPreviewStatusResponse:
    billing_state = data.get("billing_state") if isinstance(data.get("billing_state"), dict) else {}
    charged_credits = billing_state.get("charged_credits")
    return ApplicationPreviewStatusResponse(
        session_id=str(data.get("session_id") or ""),
        status=str(data.get("status") or "unknown"),
        events=_public_preview_events(data.get("events")),
        error=data.get("error") if isinstance(data.get("error"), str) else None,
        charged_credits=charged_credits if isinstance(charged_credits, int) else None,
        latest_screenshot_url=data.get("latest_screenshot_url") if isinstance(data.get("latest_screenshot_url"), str) else None,
    )


def _public_preview_events(events: Any) -> list[ApplicationPreviewEvent]:
    if not isinstance(events, list):
        return []

    public_events: list[ApplicationPreviewEvent] = []
    for event in events[-50:]:
        if not isinstance(event, dict):
            continue
        public_events.append(
            ApplicationPreviewEvent(
                kind=str(event.get("kind") or "status"),
                text=str(event.get("text") or ""),
                timestamp=float(event.get("timestamp") or 0),
            )
        )
    return public_events


async def stop_application_preview_session(
    cache_service: Any,
    session_id: str,
    current_user: Any,
    *,
    now: float,
    task_sender: Any | None = None,
) -> ApplicationPreviewStopResponse:
    data = await get_application_preview_session(cache_service, session_id, current_user)
    sandbox_id = data.get("sandbox_id") if isinstance(data.get("sandbox_id"), str) else None
    if data.get("status") not in {"stopped", "failed", "timeout"}:
        data.update({
            "status": "stopped",
            "stop_reason": "user_requested",
            "sandbox_stop_requested_at": now if sandbox_id else None,
            "updated_at": now,
        })
        data.setdefault("events", []).append({"kind": "status", "text": "Stopped application preview.", "timestamp": now})
        client = await cache_service.client
        await client.set(
            application_preview_session_key(session_id),
            json.dumps(data),
            ex=APPLICATION_PREVIEW_SESSION_TTL_SECONDS,
        )
        if sandbox_id and task_sender:
            task_sender("code.stop_application_preview", args=[session_id, sandbox_id], queue="app_code")
    billing_state = data.get("billing_state") if isinstance(data.get("billing_state"), dict) else {}
    charged_credits = billing_state.get("charged_credits")
    return ApplicationPreviewStopResponse(
        session_id=session_id,
        status=str(data.get("status") or "stopped"),
        charged_credits=charged_credits if isinstance(charged_credits, int) else None,
    )


def validate_application_preview_origin(
    preview_origin: str | None,
    *,
    app_origins: Iterable[str],
    api_origin: str | None = None,
) -> str:
    normalized_preview = _normalize_origin(preview_origin, name="APPLICATION_PREVIEW_ORIGIN")
    protected_origins = [_normalize_origin(origin, name="OpenMates app origin") for origin in app_origins if origin]
    if api_origin:
        protected_origins.append(_normalize_origin(api_origin, name="OpenMates API origin"))

    for protected_origin in protected_origins:
        if _origins_conflict(normalized_preview, protected_origin):
            raise ApplicationPreviewConfigError(
                "APPLICATION_PREVIEW_ORIGIN must be a separate site from OpenMates app/API origins."
            )

    return normalized_preview


def preview_origin_from_request(request: Request) -> str:
    return validate_application_preview_origin(
        os.getenv("APPLICATION_PREVIEW_ORIGIN"),
        app_origins=getattr(request.app.state, "allowed_origins", []) or [],
        api_origin=os.getenv("API_PUBLIC_ORIGIN"),
    )


@router.post("/{application_embed_id}/preview/start", response_model=ApplicationPreviewStartResponse)
async def start_application_preview(
    application_embed_id: str,
    body: ApplicationPreviewStartRequest,
    request: Request,
    current_user: Any = Depends(get_application_preview_current_user),
    cache_service: Any = Depends(get_cache_service),
    directus_service: Any = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> ApplicationPreviewStartResponse:
    try:
        preview_origin = preview_origin_from_request(request)
    except ApplicationPreviewConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    worker_payload = await resolve_application_preview_worker_payload(
        request=request,
        application_embed_id=application_embed_id,
        body=body,
        current_user=current_user,
        cache_service=cache_service,
        directus_service=directus_service,
        encryption_service=encryption_service,
    )
    task_sender = getattr(request.app.state, "application_preview_task_sender", send_application_preview_task)
    return await create_application_preview_session_and_dispatch(
        cache_service=cache_service,
        session_id=str(uuid.uuid4()),
        application_embed_id=application_embed_id,
        body=body,
        current_user=current_user,
        preview_origin=preview_origin,
        worker_payload=worker_payload,
        task_sender=task_sender,
        now=time.time(),
    )


@router.get("/preview/{session_id}", response_model=ApplicationPreviewStatusResponse)
async def get_application_preview_status(
    session_id: str,
    current_user: Any = Depends(get_application_preview_current_user),
    cache_service: Any = Depends(get_cache_service),
) -> ApplicationPreviewStatusResponse:
    data = await get_application_preview_session(cache_service, session_id, current_user)
    return build_application_preview_status_response(data)


@router.post("/preview/{session_id}/stop", response_model=ApplicationPreviewStopResponse)
async def stop_application_preview(
    session_id: str,
    request: Request,
    current_user: Any = Depends(get_application_preview_current_user),
    cache_service: Any = Depends(get_cache_service),
) -> ApplicationPreviewStopResponse:
    task_sender = getattr(request.app.state, "application_preview_task_sender", send_application_preview_task)
    return await stop_application_preview_session(cache_service, session_id, current_user, now=time.time(), task_sender=task_sender)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_origin(value: str | None, *, name: str) -> str:
    raw = (value or "").strip().rstrip("/")
    if not raw:
        raise ApplicationPreviewConfigError(f"{name} is required for application live previews.")

    parsed = urlparse(raw)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ApplicationPreviewConfigError(f"{name} must be an absolute http(s) origin.")
    if parsed.username or parsed.password or parsed.path or parsed.params or parsed.query or parsed.fragment:
        raise ApplicationPreviewConfigError(f"{name} must be an origin only, without path, query, or credentials.")
    if parsed.scheme == "http" and hostname not in LOCAL_PREVIEW_HOSTS:
        raise ApplicationPreviewConfigError(f"{name} must use https outside local development.")

    port = _safe_port(parsed, name)
    default_port = 443 if parsed.scheme == "https" else 80
    netloc = hostname if port in {None, default_port} else f"{hostname}:{port}"
    return f"{parsed.scheme}://{netloc}"


def _safe_port(parsed: Any, name: str) -> int | None:
    try:
        return parsed.port
    except ValueError as exc:
        raise ApplicationPreviewConfigError(f"{name} has an invalid port.") from exc


def _origins_conflict(preview_origin: str, protected_origin: str) -> bool:
    preview = urlparse(preview_origin)
    protected = urlparse(protected_origin)
    preview_host = (preview.hostname or "").lower()
    protected_host = (protected.hostname or "").lower()

    if preview_origin == protected_origin:
        return True
    if preview_host in LOCAL_PREVIEW_HOSTS and protected_host in LOCAL_PREVIEW_HOSTS:
        return False
    return _registrable_site(preview_host) == _registrable_site(protected_host)


def _registrable_site(hostname: str) -> str:
    parts = [part for part in hostname.split(".") if part]
    if len(parts) <= 2:
        return hostname
    return ".".join(parts[-2:])
