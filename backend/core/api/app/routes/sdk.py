"""SDK session endpoints for API-key clients.

Purpose: give npm and pip SDKs enough encrypted account context to start work.
Architecture: docs/specs/sdk-packages-v1/spec.yml.
Security: returns only API-key-wrapped master key material, never plaintext keys.
Scope: SDK bootstrap routes; chat execution routes are added in later slices.
"""

import hashlib
from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.core.api.app.services.api_key_authorization import (
    ApiKeyAuthorizationService,
    ApiKeyScopeError,
)

from backend.core.api.app.utils.api_key_auth import (
    ApiKeyAuthService,
    ApiKeyNotFoundError,
    DeviceNotApprovedError,
    get_api_key_auth_service,
)

if TYPE_CHECKING:
    from backend.core.api.app.services.directus import DirectusService


router = APIRouter(prefix="/v1/sdk", tags=["SDK"])


class SdkChatCreateRequest(BaseModel):
    message: str | None = Field(default=None)
    save_to_account: bool = Field(default=False)
    title: str | None = Field(default=None)
    memory_ids: list[str] = Field(default_factory=list)
    model: str | None = Field(default=None)
    stream: bool = Field(default=False)


async def _authenticate_sdk_request(request: Request) -> dict[str, Any]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing API key bearer token")

    api_key = auth_header.removeprefix("Bearer ").strip()
    try:
        return await get_api_key_auth_service(request).authenticate_api_key(api_key, request=request)
    except DeviceNotApprovedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ApiKeyNotFoundError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _require_chat_scope(api_key_info: dict[str, Any], scope: str) -> None:
    try:
        ApiKeyAuthorizationService().require_chat_scope(
            api_key_info.get("api_key_metadata") or {},
            scope,
        )
    except ApiKeyScopeError as exc:
        raise HTTPException(
            status_code=403,
            detail={"error": "missing_scope", "missing_scope": exc.missing_scope},
        ) from exc


def _require_memory_scope(api_key_info: dict[str, Any]) -> None:
    metadata = api_key_info.get("api_key_metadata") or {}
    if metadata.get("full_access", True):
        return
    memory_scopes = metadata.get("scopes", {}).get("memories") or []
    if "memory:read" not in memory_scopes:
        raise HTTPException(
            status_code=403,
            detail={"error": "missing_scope", "missing_scope": "memory:read"},
        )


@router.post("/session")
async def create_sdk_session(
    request: Request,
    sdk_name: str = Body(default="unknown"),
    device_identity: str = Body(default=""),
) -> dict[str, Any]:
    return await create_sdk_session_for_api_key(
        request=request,
        sdk_name=sdk_name,
        device_identity=device_identity,
        auth_service=get_api_key_auth_service(request),
        directus_service=request.app.state.directus_service,
    )


@router.get("/chats")
async def list_sdk_chats(
    request: Request,
    limit: int = Query(default=10, ge=0, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    api_key_info = await _authenticate_sdk_request(request)
    _require_chat_scope(api_key_info, "chat:read_existing")
    chats = await request.app.state.directus_service.chat.get_user_chats_metadata(
        api_key_info["user_id"],
        limit=-1 if limit == 0 else limit,
        offset=offset,
    )
    return {"chats": chats, "limit": limit, "offset": offset}


@router.post("/chats")
async def create_sdk_chat(
    request: Request,
    request_body: SdkChatCreateRequest,
) -> dict[str, Any]:
    api_key_info = await _authenticate_sdk_request(request)
    _require_chat_scope(
        api_key_info,
        "chat:create_saved" if request_body.save_to_account else "chat:create_incognito",
    )
    if request_body.memory_ids:
        _require_memory_scope(api_key_info)

    if not request_body.message:
        return {"persistent": request_body.save_to_account, "chat_id": None}

    from backend.core.api.app.services.skill_registry import get_global_registry

    payload = {
        "messages": [{"role": "user", "content": request_body.message}],
        "model": request_body.model,
        "stream": request_body.stream,
        "is_incognito": not request_body.save_to_account,
        "apps_enabled": True,
        "_user_id": api_key_info["user_id"],
        "_api_key_name": api_key_info.get("api_key_encrypted_name", ""),
        "_api_key_hash": api_key_info.get("api_key_hash"),
        "_device_hash": api_key_info.get("device_hash"),
        "_external_request": True,
    }
    if request_body.memory_ids:
        payload["memory_ids"] = request_body.memory_ids

    result = await get_global_registry().dispatch_skill("ai", "ask", payload)
    if hasattr(result, "body_iterator"):
        return {"persistent": request_body.save_to_account, "stream": True}
    return {
        "persistent": request_body.save_to_account,
        "chat_id": None,
        "response": result,
    }


async def create_sdk_session_for_api_key(
    *,
    request: Request,
    sdk_name: str,
    device_identity: str,
    auth_service: ApiKeyAuthService,
    directus_service: "DirectusService",
) -> dict[str, Any]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing API key bearer token")

    api_key = auth_header.removeprefix("Bearer ").strip()
    try:
        api_key_info = await auth_service.authenticate_api_key(api_key, request=request)
    except DeviceNotApprovedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ApiKeyNotFoundError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user_id = api_key_info["user_id"]
    api_key_hash = api_key_info["api_key_hash"]
    hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
    login_method = f"api_key_{api_key_hash}"
    key_wrapper = await directus_service.get_encryption_key(hashed_user_id, login_method)
    if not key_wrapper:
        raise HTTPException(status_code=404, detail="API key encryption wrapper not found")

    success, profile, _message = await directus_service.get_user_profile(user_id)
    username = profile.get("username") if success and profile else None

    return {
        "user": {"id": user_id, "username": username},
        "api_key": {
            "id": api_key_info.get("api_key_id"),
            "encrypted_name": api_key_info.get("api_key_encrypted_name"),
            "metadata": api_key_info.get("api_key_metadata") or {},
        },
        "key_wrapper": {
            "encrypted_key": key_wrapper.get("encrypted_key"),
            "salt": key_wrapper.get("salt"),
            "key_iv": key_wrapper.get("key_iv"),
        },
        "device": {
            "hash": api_key_info.get("device_hash"),
            "sdk_name": sdk_name,
            "identity": device_identity,
        },
    }
