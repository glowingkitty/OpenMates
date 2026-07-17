"""SDK session endpoints for API-key clients.

Purpose: give npm and pip SDKs enough encrypted account context to start work.
Architecture: docs/specs/sdk-packages-v1/spec.yml.
Security: returns only API-key-wrapped master key material, never plaintext keys.
Scope: SDK bootstrap routes; chat execution routes are added in later slices.
"""

import hashlib
import importlib
import inspect
import json
import time
import uuid
from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.services.api_key_authorization import (
    ApiKeyAuthorizationService,
    ApiKeyScopeError,
)
from backend.core.api.app.services.chat_recovery_service import (
    ChatRecoveryProtocolError,
    ChatRecoveryService,
)
from backend.core.api.app.services.chat_recovery_cutover import (
    ChatRecoveryCutoverController,
)
from backend.core.api.app.routes.handlers.websocket_handlers.chat_turn_preflight_handler import (
    COMMITMENT_VERSION,
    build_inference_commitment,
    canonicalize_inference_request,
    enqueue_chat_turn,
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
    history: list[dict[str, Any]] = Field(default_factory=list)
    save_to_account: bool = Field(default=False)
    title: str | None = Field(default=None)
    memory_ids: list[str] = Field(default_factory=list)
    model: str | None = Field(default=None)
    focus_mode: dict[str, str] | None = Field(default=None)
    stream: bool = Field(default=False)
    protocol_version: int | None = Field(default=None)
    chat_id: str | None = Field(default=None)
    turn_id: str | None = Field(default=None)
    message_id: str | None = Field(default=None)
    chat_key_version: int | None = Field(default=None)
    encrypted_chat_key: str | None = Field(default=None)
    recovery_public_key: str | None = Field(default=None)
    expected_messages_v: int | None = Field(default=None)
    encrypted_user_message: dict[str, Any] | None = Field(default=None)
    encrypted_chat_metadata: dict[str, Any] | None = Field(default=None)
    inference_request: dict[str, Any] | None = Field(default=None)


class SdkRecoveryClaimRequest(BaseModel):
    protocol_version: int = Field(default=1)


class SdkRecoveryPersistRequest(BaseModel):
    protocol_version: int = Field(default=1)
    lease_generation: int
    lease_token: str
    expected_messages_v: int
    encrypted_assistant_message: dict[str, Any]


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


SDK_SCOPE_BY_SURFACE = {
    "chats": ("chat", "chat"),
    "account": ("account", "account"),
    "settings": ("settings", "settings"),
    "memories": ("memories", "memory"),
    "billing": ("billing", "billing"),
    "notifications": ("notifications", "notification"),
    "reminders": ("reminders", "reminder"),
    "docs": ("docs", "docs"),
    "embeds": ("embeds", "embed"),
    "connected-accounts": ("connected_accounts", "connected_account"),
    "learning-mode": ("learning_mode", "learning_mode"),
    "inspirations": ("inspirations", "inspiration"),
    "new-chat-suggestions": ("new_chat_suggestions", "new_chat_suggestion"),
    "feedback": ("feedback", "feedback"),
    "benchmark": ("benchmark", "benchmark"),
}


def _sdk_scope_action(method: str) -> str:
    return "read" if method.upper() == "GET" else "write"


def _require_sdk_scope_for_surface(
    api_key_info: dict[str, Any],
    surface: str,
    method: str,
    path: str = "",
) -> str:
    scope_config = SDK_SCOPE_BY_SURFACE.get(surface)
    if scope_config is None:
        raise HTTPException(status_code=404, detail="Unknown SDK surface")

    if surface == "chats":
        parts = [part for part in path.split("/") if part]
        if request_method_is_read(method):
            required_scope = "chat:read_existing"
        elif len(parts) > 1 and parts[1] == "export":
            required_scope = "chat:export"
        elif len(parts) > 1 and parts[1] == "share":
            required_scope = "chat:share"
        elif method.upper() == "DELETE":
            required_scope = "chat:delete"
        else:
            required_scope = "chat:create_saved"
        _require_chat_scope(api_key_info, required_scope)
        return required_scope

    if surface == "settings":
        parts = [part for part in path.split("/") if part]
        if parts and parts[0] == "api-keys":
            action = "read" if request_method_is_read(method) else "create" if method.upper() == "POST" and len(parts) == 1 else "revoke"
            required_scope = f"developer:api_keys:{action}"
            try:
                ApiKeyAuthorizationService().require_scope(
                    api_key_info.get("api_key_metadata") or {},
                    "developer",
                    required_scope,
                )
            except ApiKeyScopeError as exc:
                raise HTTPException(
                    status_code=403,
                    detail={"error": "missing_scope", "missing_scope": exc.missing_scope},
                ) from exc
            return required_scope
        if parts and parts[0] == "api-key-devices":
            if request_method_is_read(method):
                action = "read"
            elif len(parts) >= 3 and parts[2] == "approve":
                action = "approve"
            else:
                action = "revoke"
            required_scope = f"developer:devices:{action}"
            try:
                ApiKeyAuthorizationService().require_scope(
                    api_key_info.get("api_key_metadata") or {},
                    "developer",
                    required_scope,
                )
            except ApiKeyScopeError as exc:
                raise HTTPException(
                    status_code=403,
                    detail={"error": "missing_scope", "missing_scope": exc.missing_scope},
                ) from exc
            return required_scope

    group, prefix = scope_config
    required_scope = f"{prefix}:{_sdk_scope_action(method)}"
    try:
        ApiKeyAuthorizationService().require_scope(
            api_key_info.get("api_key_metadata") or {},
            group,
            required_scope,
        )
    except ApiKeyScopeError as exc:
        raise HTTPException(
            status_code=403,
            detail={"error": "missing_scope", "missing_scope": exc.missing_scope},
        ) from exc
    return required_scope


def request_method_is_read(method: str) -> bool:
    return method.upper() == "GET"


def _bounded_int_query(
    request: Request,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = request.query_params.get(name)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise HTTPException(status_code=400, detail=f"{name} must be between {minimum} and {maximum}")
    return value


def _require_sdk_read_scope(api_key_info: dict[str, Any], group: str, scope: str) -> None:
    try:
        ApiKeyAuthorizationService().require_scope(
            api_key_info.get("api_key_metadata") or {},
            group,
            scope,
        )
    except ApiKeyScopeError as exc:
        raise HTTPException(
            status_code=403,
            detail={"error": "missing_scope", "missing_scope": exc.missing_scope},
        ) from exc


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _sdk_route_handler(handler: Any) -> Any:
    # SDK dispatch reuses product route handlers directly; unwrap decorators
    # such as SlowAPI so internal calls keep normal FastAPI dependencies explicit.
    return inspect.unwrap(handler)


def _sdk_route_module(module_name: str) -> Any:
    return importlib.import_module(f"backend.core.api.app.routes.{module_name}")


def _extract_chat_response_content(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    if isinstance(result.get("content"), str):
        return result["content"]
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None
    message = first_choice.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    if isinstance(first_choice.get("text"), str):
        return first_choice["text"]
    return None


def _extract_chat_response_model_name(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    for key in ("model_name", "modelName", "selected_model_name", "model"):
        value = result.get(key)
        if isinstance(value, str) and value:
            return value
    usage = result.get("usage")
    if isinstance(usage, dict):
        value = usage.get("model_name") or usage.get("modelName")
        if isinstance(value, str) and value:
            return value
    return None


def _sdk_recovery_job_id(inference_task_id: str) -> str:
    try:
        namespace = uuid.UUID(inference_task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_inference_task_id"}) from exc
    return str(uuid.uuid5(namespace, "recovery-job"))


def _sdk_recovery_identity(api_key_info: dict[str, Any]) -> tuple[str, str]:
    device_hash = api_key_info.get("device_hash")
    if not isinstance(device_hash, str) or not device_hash:
        raise HTTPException(status_code=403, detail={"error": "approved_device_required"})
    user_id = str(api_key_info["user_id"])
    return hashlib.sha256(user_id.encode()).hexdigest(), device_hash


async def _execute_sdk_recovery(
    request: Request,
    operation: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    try:
        return await ChatRecoveryService(request.app.state.directus_service).execute(operation, data)
    except ChatRecoveryProtocolError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"error": exc.code}) from exc


async def _sdk_user_from_api_key(
    request: Request,
    api_key_info: dict[str, Any],
) -> User:
    user_id = api_key_info["user_id"]
    profile_success, profile, profile_message = await request.app.state.directus_service.get_user_profile(user_id)
    if not profile_success or not profile:
        raise HTTPException(status_code=404, detail=f"User profile not found: {profile_message}")
    username = profile.get("username") or profile.get("encrypted_username") or "api-key-user"
    vault_key_id = profile.get("vault_key_id")
    if not vault_key_id:
        raise HTTPException(status_code=500, detail="User encryption key not found")
    return User(
        id=user_id,
        username=username,
        vault_key_id=vault_key_id,
        is_admin=bool(profile.get("is_admin")),
        credits=int(profile.get("credits") or 0),
        profile_image_url=profile.get("profile_image_url"),
        language=profile.get("language") or "en",
        darkmode=bool(profile.get("darkmode") or False),
        encrypted_email_address=profile.get("encrypted_email_address"),
        encrypted_key=profile.get("encrypted_key"),
        salt=profile.get("salt"),
        user_email_salt=profile.get("user_email_salt"),
        account_id=profile.get("account_id"),
        invoice_counter=profile.get("invoice_counter"),
        auto_topup_low_balance_enabled=bool(profile.get("auto_topup_low_balance_enabled") or False),
        auto_topup_low_balance_threshold=profile.get("auto_topup_low_balance_threshold"),
        auto_topup_low_balance_amount=profile.get("auto_topup_low_balance_amount"),
        auto_topup_low_balance_currency=profile.get("auto_topup_low_balance_currency"),
    )


async def _dispatch_sdk_surface(
    request: Request,
    api_key_info: dict[str, Any],
    surface: str,
    path: str,
    body: dict[str, Any] | None,
) -> Any:
    user = await _sdk_user_from_api_key(request, api_key_info)
    directus_service = request.app.state.directus_service
    cache_service = request.app.state.cache_service
    encryption_service = getattr(request.app.state, "encryption_service", None)

    if surface == "chats":
        parts = [part for part in path.split("/") if part]
        if not parts:
            return None
        chat_id = parts[0]
        if not await directus_service.chat.check_chat_ownership(chat_id, api_key_info["user_id"]):
            raise HTTPException(status_code=404, detail="Chat not found")
        if len(parts) == 1 and request.method == "DELETE":
            messages_ok = await directus_service.chat.delete_all_messages_for_chat(chat_id)
            drafts_ok = await directus_service.chat.delete_all_drafts_for_chat(chat_id)
            chat_ok = await directus_service.chat.persist_delete_chat(chat_id)
            if not (messages_ok and drafts_ok and chat_ok):
                raise HTTPException(status_code=502, detail="Failed to delete chat")
            return {"success": True, "chat_id": chat_id}
        if len(parts) == 2 and parts[1] == "export" and request.method == "POST":
            payload = (body or {}).get("payload") or {}
            return {"chat_id": chat_id, "format": (body or {}).get("format", "json"), "data": payload}
        if len(parts) == 2 and parts[1] == "follow-ups" and request.method == "GET":
            chat = await directus_service.chat.get_chat_metadata(chat_id)
            return {"suggestions": [], "encrypted_follow_up_request_suggestions": (chat or {}).get("encrypted_follow_up_request_suggestions")}
        if len(parts) == 2 and parts[1] == "share" and request.method == "POST":
            return {"chat_id": chat_id, "share": "client_side_key_required"}

    if surface == "docs":
        if path == "search":
            query = request.query_params.get("q") or request.query_params.get("query")
            if not query:
                raise HTTPException(status_code=400, detail="Missing docs search query")
            if len(query) > 200:
                raise HTTPException(status_code=400, detail="Docs search query must be 200 characters or fewer")
            docs_routes = _sdk_route_module("docs_routes")

            return {"results": await _sdk_route_handler(docs_routes.search_docs)(query)}
        docs_routes = _sdk_route_module("docs_routes")

        if path == "":
            return await _sdk_route_handler(docs_routes.list_docs)()
        if path.endswith("/download"):
            path = path.removesuffix("/download")
        response = await _sdk_route_handler(docs_routes.get_doc)(path)
        content = response.body.decode("utf-8") if isinstance(response.body, bytes) else str(response.body)
        return {"slug": path, "content": content}

    if surface == "learning-mode":
        from backend.core.api.app.routes.learning_mode import (
            LearningModeActivateRequest,
            LearningModeDeactivateRequest,
            activate_learning_mode,
            deactivate_learning_mode,
            get_learning_mode_status,
        )

        if path == "" and request.method == "GET":
            return _jsonable(await _sdk_route_handler(get_learning_mode_status)(user, cache_service, directus_service))
        if path in ("enable", "activate") and request.method == "POST":
            return _jsonable(await _sdk_route_handler(activate_learning_mode)(
                request,
                LearningModeActivateRequest(passcode=str((body or {}).get("passcode") or ""), age_group=str((body or {}).get("age_group") or "")),
                user,
                cache_service,
                directus_service,
            ))
        if path in ("disable", "deactivate") and request.method == "POST":
            return _jsonable(await _sdk_route_handler(deactivate_learning_mode)(
                request,
                LearningModeDeactivateRequest(passcode=str((body or {}).get("passcode") or "")),
                user,
                cache_service,
                directus_service,
            ))

    if surface == "notifications":
        from backend.core.api.app.services.notification_event_service import NotificationEventService

        if path in ("", "status") and request.method == "GET":
            if path == "status":
                return {
                    "enabled": True,
                    "stream": "/v1/sdk/notifications/stream",
                }
            limit = _bounded_int_query(request, "limit", default=50, minimum=1, maximum=100)
            events = await NotificationEventService(cache_service).get_recent(str(user.id), limit=limit)
            return {"events": events}

    if surface == "reminders":
        settings_routes = _sdk_route_module("settings")

        parts = [part for part in path.split("/") if part]
        if not parts and request.method == "GET":
            return _jsonable(await _sdk_route_handler(settings_routes.get_active_reminders)(
                request,
                include_recent_fired=request.query_params.get("include_recent_fired") == "true",
                upcoming_hours=_bounded_int_query(request, "upcoming_hours", default=0, minimum=0, maximum=168),
                recent_hours=_bounded_int_query(request, "recent_hours", default=12, minimum=1, maximum=168),
                current_user=user,
                cache_service=cache_service,
                encryption_service=encryption_service,
            ))
        if len(parts) == 1 and request.method == "PATCH":
            return _jsonable(await _sdk_route_handler(settings_routes.update_reminder_endpoint)(
                parts[0],
                request,
                settings_routes.UpdateReminderRequest(**(body or {})),
                user,
                cache_service,
                encryption_service,
            ))
        if len(parts) == 1 and request.method == "DELETE":
            return await _sdk_route_handler(settings_routes.delete_reminder_endpoint)(parts[0], request, user, cache_service)

    if surface == "inspirations" and request.method == "GET":
        from backend.core.api.app.routes.default_inspirations import get_default_inspirations

        return await _sdk_route_handler(get_default_inspirations)(
            request,
            lang=request.query_params.get("lang", "en"),
            directus_service=directus_service,
            cache_service=cache_service,
        )

    if surface == "new-chat-suggestions" and request.method == "GET":
        limit = _bounded_int_query(request, "limit", default=10, minimum=1, maximum=50)
        hashed_user_id = hashlib.sha256(str(user.id).encode()).hexdigest()
        suggestions = await cache_service.get_new_chat_suggestions(hashed_user_id)
        if suggestions is None:
            suggestions = await directus_service.chat.get_new_chat_suggestions_for_user(hashed_user_id, limit=limit)
            await cache_service.set_new_chat_suggestions(hashed_user_id, suggestions, ttl=600)
        return {"suggestions": suggestions[:limit], "limit": limit}

    if surface == "account":
        if path == "" and request.method == "GET":
            return {
                "id": user.id,
                "username": user.username,
                "credits": user.credits,
                "language": user.language,
                "darkmode": user.darkmode,
            }
        if path == "topic-preferences" and request.method == "GET":
            profile_success, profile, _message = await directus_service.get_user_profile(user.id)
            if not profile_success or not profile:
                raise HTTPException(status_code=404, detail="User profile not found")
            return {"encrypted_settings": profile.get("encrypted_settings")}
        if path in ("export/manifest", "export/data"):
            _require_chat_scope(api_key_info, "chat:read_existing")
            _require_sdk_read_scope(api_key_info, "billing", "billing:read")
        settings_routes = _sdk_route_module("settings")
        from backend.core.api.app.schemas.settings import StorageDeleteFilesRequest, TimezoneUpdateRequest, TopicPreferencesEncryptedRequest, UsernameUpdateRequest

        if path == "timezone" and request.method == "POST":
            return _jsonable(await _sdk_route_handler(settings_routes.update_user_timezone)(
                request,
                TimezoneUpdateRequest(timezone=str((body or {}).get("timezone") or "")),
                user,
                directus_service,
                cache_service,
            ))
        if path == "username" and request.method == "POST":
            return _jsonable(await _sdk_route_handler(settings_routes.update_username)(
                request,
                UsernameUpdateRequest(username=str((body or {}).get("username") or "")),
                user,
                directus_service,
                cache_service,
                encryption_service,
            ))
        if path == "export/manifest" and request.method == "GET":
            return _jsonable(await _sdk_route_handler(settings_routes.get_export_manifest)(request, user, directus_service, cache_service))
        if path == "export/data" and request.method == "GET":
            return _jsonable(await _sdk_route_handler(settings_routes.get_export_data)(request, True, True, user, directus_service, encryption_service, cache_service))
        if path == "storage" and request.method == "GET":
            return _jsonable(await _sdk_route_handler(settings_routes.get_storage_overview)(request, user, directus_service))
        if path == "storage/files" and request.method == "GET":
            return _jsonable(await _sdk_route_handler(settings_routes.list_storage_files)(
                request,
                category=request.query_params.get("category"),
                current_user=user,
                directus_service=directus_service,
            ))
        if path == "storage/files" and request.method == "DELETE":
            payload = body or {}
            scope = "all" if payload.get("all") else "category" if payload.get("category") else "single"
            return _jsonable(await _sdk_route_handler(settings_routes.delete_storage_files)(
                StorageDeleteFilesRequest(scope=scope, file_id=payload.get("file_id"), category=payload.get("category")),
                request,
                user,
                directus_service,
            ))
        if path == "topic-preferences" and request.method == "POST":
            return _jsonable(await _sdk_route_handler(settings_routes.update_topic_preferences)(
                request,
                TopicPreferencesEncryptedRequest(**(body or {})),
                user,
                directus_service,
                cache_service,
            ))

    if surface == "memories":
        parts = [part for part in path.split("/") if part]
        hashed_user_id = hashlib.sha256(str(user.id).encode()).hexdigest()
        if not parts and request.method == "GET":
            app_id = request.query_params.get("app_id")
            item_type = request.query_params.get("item_type")
            filters: dict[str, Any] = {"hashed_user_id": {"_eq": hashed_user_id}}
            if app_id:
                filters["app_id"] = {"_eq": app_id}
            if item_type:
                filters["item_type"] = {"_eq": item_type}
            memories = await directus_service.get_items(
                "user_app_settings_and_memories",
                params={"filter": filters, "limit": -1, "sort": "-updated_at"},
            )
            return {"memories": memories or []}
        if parts == ["types"] and request.method == "GET":
            apps_routes = _sdk_route_module("apps_api")

            apps = await _sdk_route_handler(apps_routes.list_apps)(request=request, user_info={"user_id": user.id})
            return {"apps": _jsonable(apps)}
        if not parts and request.method == "POST":
            entry = (body or {}).get("entry") or body or {}
            entry_id = str(entry.get("id") or "")
            if not entry_id or not entry.get("app_id") or not entry.get("item_key"):
                raise HTTPException(status_code=400, detail="Missing memory entry fields")
            payload = {
                **entry,
                "hashed_user_id": hashed_user_id,
                "encrypted_app_key": entry.get("encrypted_app_key", ""),
            }
            existing = await directus_service.get_items(
                "user_app_settings_and_memories",
                params={"filter": {"id": {"_eq": entry_id}, "hashed_user_id": {"_eq": hashed_user_id}}, "limit": 1},
            )
            if existing:
                await directus_service.update_item("user_app_settings_and_memories", entry_id, payload)
            else:
                await directus_service.create_item("user_app_settings_and_memories", payload)
            return {"success": True, "id": entry_id}
        if len(parts) == 1 and request.method == "PATCH":
            payload = {**(body or {}), "hashed_user_id": hashed_user_id}
            updated = await directus_service.update_item("user_app_settings_and_memories", parts[0], payload)
            if not updated:
                raise HTTPException(status_code=404, detail="Memory not found")
            return {"success": True, "id": parts[0]}
        if len(parts) == 1 and request.method == "DELETE":
            existing = await directus_service.get_items(
                "user_app_settings_and_memories",
                params={"filter": {"id": {"_eq": parts[0]}, "hashed_user_id": {"_eq": hashed_user_id}}, "limit": 1},
            )
            if not existing:
                raise HTTPException(status_code=404, detail="Memory not found")
            await directus_service.delete_item("user_app_settings_and_memories", parts[0])
            return {"success": True, "id": parts[0]}

    if surface == "settings":
        settings_routes = _sdk_route_module("settings")
        from backend.core.api.app.schemas.settings import (
            AiModelDefaultsRequest,
            AutoDeleteChatsRequest,
            DarkModeUpdateRequest,
            LanguageUpdateRequest,
            UiFontUpdateRequest,
        )

        if path == "api-keys" and request.method == "GET":
            return _jsonable(await _sdk_route_handler(settings_routes.get_api_keys)(
                request,
                user,
                directus_service,
                cache_service,
            ))
        if path == "api-keys" and request.method == "POST":
            return _jsonable(await _sdk_route_handler(settings_routes.create_api_key)(
                request,
                settings_routes.ApiKeyCreateRequest(**(body or {})),
                user,
                directus_service,
                cache_service,
            ))
        if path.startswith("api-keys/") and request.method == "DELETE":
            key_id = path.split("/", 1)[1]
            return _jsonable(await _sdk_route_handler(settings_routes.delete_api_key)(
                request,
                key_id,
                user,
                directus_service,
                cache_service,
            ))
        if path == "api-key-devices" and request.method == "GET":
            return _jsonable(await _sdk_route_handler(settings_routes.get_api_key_devices)(
                request,
                user,
                directus_service,
            ))
        if path.startswith("api-key-devices/") and request.method == "POST":
            parts = path.split("/")
            if len(parts) == 3 and parts[2] == "approve":
                return _jsonable(await _sdk_route_handler(settings_routes.approve_api_key_device)(
                    request,
                    parts[1],
                    user,
                    directus_service,
                ))
            if len(parts) == 3 and parts[2] == "revoke":
                return _jsonable(await _sdk_route_handler(settings_routes.revoke_api_key_device)(
                    request,
                    parts[1],
                    user,
                    directus_service,
                ))

        if path == "language" and request.method == "POST":
            return _jsonable(await _sdk_route_handler(settings_routes.update_user_language)(
                request,
                LanguageUpdateRequest(language=str((body or {}).get("language") or "")),
                user,
                directus_service,
                cache_service,
            ))
        if path == "dark-mode" and request.method == "POST":
            return _jsonable(await _sdk_route_handler(settings_routes.update_user_darkmode)(
                request,
                DarkModeUpdateRequest(darkmode=bool((body or {}).get("enabled"))),
                user,
                directus_service,
                cache_service,
            ))
        if path == "font" and request.method == "POST":
            return _jsonable(await _sdk_route_handler(settings_routes.update_user_ui_font)(
                request,
                UiFontUpdateRequest(ui_font=str((body or {}).get("font") or "")),
                user,
                directus_service,
                cache_service,
            ))
        if path == "auto-delete/chats" and request.method == "POST":
            return _jsonable(await _sdk_route_handler(settings_routes.update_auto_delete_chats)(
                request,
                AutoDeleteChatsRequest(period=str((body or {}).get("period") or "")),
                user,
                directus_service,
                cache_service,
            ))
        if path == "ai-model-defaults" and request.method == "POST":
            return _jsonable(await _sdk_route_handler(settings_routes.update_ai_model_defaults)(
                request,
                AiModelDefaultsRequest(**(body or {})),
                user,
                directus_service,
                cache_service,
            ))

    if surface == "billing":
        if path == "" and request.method == "GET":
            settings_routes = _sdk_route_module("settings")

            return _jsonable(await _sdk_route_handler(settings_routes.get_billing_overview)(request, user, directus_service, cache_service, encryption_service))
        if path == "invoices" and request.method == "GET":
            settings_routes = _sdk_route_module("settings")

            overview = await _sdk_route_handler(settings_routes.get_billing_overview)(request, user, directus_service, cache_service, encryption_service)
            return {"invoices": _jsonable(getattr(overview, "invoices", []))}
        if path == "usage" and request.method == "GET":
            settings_routes = _sdk_route_module("settings")

            return await _sdk_route_handler(settings_routes.get_usage)(request, user, directus_service, cache_service)
        if path == "usage/summaries" and request.method == "GET":
            settings_routes = _sdk_route_module("settings")

            return await _sdk_route_handler(settings_routes.get_usage_summaries)(
                request,
                type=request.query_params.get("type", "chats"),
                months=_bounded_int_query(request, "months", default=3, minimum=1, maximum=36),
                current_user=user,
                directus_service=directus_service,
                cache_service=cache_service,
            )
        if path == "usage/daily" and request.method == "GET":
            settings_routes = _sdk_route_module("settings")

            return await _sdk_route_handler(settings_routes.get_daily_overview)(request, _bounded_int_query(request, "days", default=7, minimum=1, maximum=90), user, directus_service, cache_service)
        if path == "usage/export" and request.method == "GET":
            settings_routes = _sdk_route_module("settings")

            return await _sdk_route_handler(settings_routes.export_usage_csv)(request, _bounded_int_query(request, "months", default=3, minimum=1, maximum=36), user, directus_service, encryption_service)
        if path == "auto-topup/low-balance" and request.method == "POST":
            settings_routes = _sdk_route_module("settings")
            from backend.core.api.app.schemas.settings import AutoTopUpLowBalanceRequest

            return _jsonable(await _sdk_route_handler(settings_routes.update_low_balance_auto_topup)(request, AutoTopUpLowBalanceRequest(**(body or {})), user, directus_service, cache_service, encryption_service))
        if path == "bank-transfer-orders" and request.method == "POST":
            payments_routes = _sdk_route_module("payments")

            return _jsonable(await _sdk_route_handler(payments_routes.create_bank_transfer_order)(request=request, order_data=payments_routes.CreateBankTransferOrderRequest(**(body or {})), payment_service=request.app.state.payment_service, cache_service=cache_service, directus_service=directus_service, encryption_service=encryption_service, current_user=user))
        if path == "bank-transfer-orders" and request.method == "GET":
            payments_routes = _sdk_route_module("payments")

            return _jsonable(await _sdk_route_handler(payments_routes.get_pending_bank_transfers)(request=request, cache_service=cache_service, directus_service=directus_service, current_user=user))
        if path.startswith("bank-transfer-orders/") and request.method == "GET":
            payments_routes = _sdk_route_module("payments")

            return _jsonable(await _sdk_route_handler(payments_routes.get_bank_transfer_status)(request=request, order_id=path.split("/", 1)[1], cache_service=cache_service, directus_service=directus_service, current_user=user))
        if path == "gift-cards/redeem" and request.method == "POST":
            payments_routes = _sdk_route_module("payments")

            return _jsonable(await _sdk_route_handler(payments_routes.redeem_gift_card)(request, payments_routes.RedeemGiftCardRequest(**(body or {})), None, user, directus_service, cache_service, encryption_service))
        if path == "gift-cards/redeemed" and request.method == "GET":
            payments_routes = _sdk_route_module("payments")

            return _jsonable(await _sdk_route_handler(payments_routes.get_redeemed_gift_cards)(request=request, _official_cloud=None, current_user=user, directus_service=directus_service, cache_service=cache_service, encryption_service=encryption_service))
        if path == "gift-cards/purchased" and request.method == "GET":
            payments_routes = _sdk_route_module("payments")

            return _jsonable(await _sdk_route_handler(payments_routes.get_purchased_gift_cards)(request=request, current_user=user, directus_service=directus_service))
        if path == "gift-cards/bank-transfer-orders" and request.method == "POST":
            payments_routes = _sdk_route_module("payments")

            return _jsonable(await _sdk_route_handler(payments_routes.create_gift_card_bank_transfer_order)(request=request, order_data=payments_routes.CreateBankTransferOrderRequest(**(body or {})), _official_cloud=None, payment_service=request.app.state.payment_service, cache_service=cache_service, directus_service=directus_service, encryption_service=encryption_service, current_user=user))
        if path.startswith("gift-cards/purchases/") and request.method == "GET":
            payments_routes = _sdk_route_module("payments")

            return _jsonable(await _sdk_route_handler(payments_routes.get_gift_card_purchase_status)(request=request, order_id=path.split("/", 2)[2], _official_cloud=None, cache_service=cache_service, directus_service=directus_service, current_user=user))
        if path.startswith("invoices/") and path.endswith("/download") and request.method == "GET":
            payments_routes = _sdk_route_module("payments")

            invoice_id = path.split("/")[1]
            return await _sdk_route_handler(payments_routes.download_invoice)(request, invoice_id, user, directus_service, encryption_service, request.app.state.s3_service)
        if path.startswith("invoices/") and path.endswith("/credit-note/download") and request.method == "GET":
            payments_routes = _sdk_route_module("payments")

            invoice_id = path.split("/")[1]
            return await _sdk_route_handler(payments_routes.download_credit_note)(request, invoice_id, user, directus_service, encryption_service, request.app.state.s3_service)
        if path == "refund" and request.method == "POST":
            payments_routes = _sdk_route_module("payments")

            return _jsonable(await _sdk_route_handler(payments_routes.request_refund)(request=request, refund_request=payments_routes.RefundRequest(**(body or {})), current_user=user, payment_service=request.app.state.payment_service, directus_service=directus_service, encryption_service=encryption_service, cache_service=cache_service, compliance_service=payments_routes.ComplianceService()))

    if surface == "embeds":
        parts = [part for part in path.split("/") if part]
        if len(parts) == 1 and request.method == "GET":
            embed_id = parts[0]
            hashed_user_id = hashlib.sha256(str(user.id).encode()).hexdigest()
            embed_rows = await directus_service.get_items(
                "embeds",
                params={
                    "filter": {"embed_id": {"_eq": embed_id}, "hashed_user_id": {"_eq": hashed_user_id}},
                    "limit": 1,
                },
            )
            if not embed_rows:
                raise HTTPException(status_code=404, detail="Embed not found")
            embed_keys = await directus_service.embed.get_embed_keys_by_embed_id(embed_id)
            owned_keys = [key for key in (embed_keys or []) if key.get("hashed_user_id") in (None, hashed_user_id)]
            return {"embed": embed_rows[0], "embed_keys": owned_keys}
        from backend.core.api.app.routes.embeds_api import get_embed_version, list_embed_versions, restore_embed_version

        if len(parts) == 2 and parts[1] == "versions" and request.method == "GET":
            return await _sdk_route_handler(list_embed_versions)(parts[0], request, user, directus_service)
        if len(parts) == 3 and parts[1] == "versions" and request.method == "GET":
            return await _sdk_route_handler(get_embed_version)(parts[0], int(parts[2]), request, user, directus_service)
        if len(parts) == 4 and parts[1] == "versions" and parts[3] == "restore" and request.method == "POST":
            return await _sdk_route_handler(restore_embed_version)(parts[0], int(parts[2]), request, user, directus_service)

    if surface == "connected-accounts":
        if path == "import" and request.method == "POST":
            from backend.core.api.app.services.connected_accounts_service import ConnectedAccountRow

            row_payload = (body or {}).get("row") or body or {}
            hashed_user_id = hashlib.sha256(str(user.id).encode()).hexdigest()
            if row_payload.get("hashed_user_id") != hashed_user_id:
                raise HTTPException(status_code=403, detail="Connected account owner hash does not match current user")
            try:
                row = ConnectedAccountRow.validate_for_storage(row_payload)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            payload = row.__dict__ | {"updated_at": int(time.time())}
            stored = await directus_service.create_item("connected_accounts", payload)
            if isinstance(stored, tuple):
                success, data = stored
                if not success:
                    raise HTTPException(status_code=502, detail="Failed to store connected account")
                stored = data or payload
            return {"success": True, "id": str((stored or payload).get("id", row.id)), "sync_version": int((stored or payload).get("updated_at") or payload["updated_at"])}

    if surface == "feedback" and path == "assistant-response" and request.method == "POST":
        rating = int((body or {}).get("rating") or 0)
        if rating < 1 or rating > 5:
            raise HTTPException(status_code=400, detail="rating must be between 1 and 5")
        return {"success": True, "rating": rating}

    if surface == "benchmark":
        if path == "estimate" and request.method == "POST":
            return {"estimate": {"credits": None}, "input": body or {}}
        if path == "run" and request.method == "POST":
            from backend.core.api.app.services.skill_registry import get_global_registry

            return await get_global_registry().dispatch_skill("ai", "ask", {**(body or {}), "_user_id": api_key_info["user_id"], "_api_key_hash": api_key_info.get("api_key_hash"), "_external_request": True, "usage_context": "benchmark"})

    return None


async def _sdk_parity_placeholder(
    request: Request,
    surface: str,
    path: str = "",
    body: dict[str, Any] | None = None,
) -> Any:
    api_key_info = await _authenticate_sdk_request(request)
    required_scope = _require_sdk_scope_for_surface(api_key_info, surface, request.method, path)
    result = await _dispatch_sdk_surface(request, api_key_info, surface, path, body)
    if result is not None:
        return result
    raise HTTPException(
        status_code=501,
        detail={
            "error": "sdk_surface_not_implemented",
            "surface": surface,
            "path": path,
            "method": request.method,
            "required_scope": required_scope,
            "accepted_body": body is not None,
        },
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
        admin_required=True,
    )
    hashed_user_id = hashlib.sha256(api_key_info["user_id"].encode()).hexdigest()
    hashed_chat_ids = [
        hashlib.sha256(str(chat.get("id")).encode()).hexdigest()
        for chat in chats
        if chat.get("id")
    ]
    wrappers = await request.app.state.directus_service.chat_key_wrapper.get_wrappers_by_hashed_chat_ids_batch(
        hashed_chat_ids,
        hashed_user_id=hashed_user_id,
    )
    wrappers_by_hash: dict[str, list[dict[str, Any]]] = {}
    for wrapper in wrappers:
        hashed_chat_id = wrapper.get("hashed_chat_id")
        if isinstance(hashed_chat_id, str):
            wrappers_by_hash.setdefault(hashed_chat_id, []).append(wrapper)
    for chat in chats:
        chat_id = chat.get("id")
        if chat_id:
            chat["chat_key_wrappers"] = wrappers_by_hash.get(hashlib.sha256(str(chat_id).encode()).hexdigest(), [])
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

    if request_body.save_to_account:
        cutover_state = await ChatRecoveryCutoverController(
            request.app.state.cache_service,
            request.app.state.directus_service,
        ).get_state(authoritative=True)
        if cutover_state.get("protocol_epoch") != 1 or cutover_state.get("sends_paused"):
            raise HTTPException(status_code=426, detail={"error": "client_update_required"})
        required_fields = {
            "chat_id": request_body.chat_id,
            "turn_id": request_body.turn_id,
            "message_id": request_body.message_id,
            "chat_key_version": request_body.chat_key_version,
            "encrypted_chat_key": request_body.encrypted_chat_key,
            "recovery_public_key": request_body.recovery_public_key,
            "expected_messages_v": request_body.expected_messages_v,
            "encrypted_user_message": request_body.encrypted_user_message,
            "inference_request": request_body.inference_request,
        }
        if request_body.protocol_version != 1:
            raise HTTPException(status_code=426, detail={"error": "client_update_required"})
        missing = [name for name, value in required_fields.items() if value is None]
        if missing:
            raise HTTPException(
                status_code=400,
                detail={"error": "saved_chat_preflight_required", "missing": missing},
            )
        device_hash = api_key_info.get("device_hash")
        if not isinstance(device_hash, str) or not device_hash:
            raise HTTPException(status_code=403, detail={"error": "approved_device_required"})

        user_id = str(api_key_info["user_id"])
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        encrypted_user_message = dict(request_body.encrypted_user_message or {})
        if encrypted_user_message.get("chat_id") != request_body.chat_id or encrypted_user_message.get("client_message_id") != request_body.message_id:
            raise HTTPException(status_code=400, detail={"error": "encrypted_user_message_identity_mismatch"})
        encrypted_user_message["hashed_user_id"] = hashed_user_id
        try:
            inference_request = json.loads(canonicalize_inference_request(request_body.inference_request or {}))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail={"error": "invalid_inference_request"}) from exc
        inference_messages = inference_request.get("messages")
        if not isinstance(inference_messages, list) or not inference_messages:
            raise HTTPException(status_code=400, detail={"error": "invalid_inference_request"})
        current_message = inference_messages[-1]
        if not isinstance(current_message, dict) or current_message.get("content") != request_body.message:
            raise HTTPException(status_code=400, detail={"error": "inference_request_mismatch"})
        try:
            preflight = await ChatRecoveryService(request.app.state.directus_service).execute(
                "prepare_preflight",
                {
                    "protocol_version": 1,
                    "hashed_user_id": hashed_user_id,
                    "chat_id": request_body.chat_id,
                    "turn_id": request_body.turn_id,
                    "user_message_id": request_body.message_id,
                    "device_hash": device_hash,
                    "chat_key_version": request_body.chat_key_version,
                    "wrapped_chat_key": request_body.encrypted_chat_key,
                    "recovery_public_key": request_body.recovery_public_key,
                    "inference_commitment": build_inference_commitment(inference_request),
                    "commitment_version": COMMITMENT_VERSION,
                    "expected_messages_v": request_body.expected_messages_v,
                    "encrypted_user_message": encrypted_user_message,
                    **(
                        {"encrypted_chat_metadata": request_body.encrypted_chat_metadata}
                        if request_body.encrypted_chat_metadata is not None
                        else {}
                    ),
                },
            )
            enqueue = await enqueue_chat_turn(
                directus_service=request.app.state.directus_service,
                user_id_hash=hashed_user_id,
                device_fingerprint_hash=device_hash,
                preflight_id=str(preflight["preflight_id"]),
                inference_request=inference_request,
            )
        except ChatRecoveryProtocolError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"error": exc.code}) from exc

        history_messages = [message for message in inference_messages if isinstance(message, dict)]
        focus_mode = inference_request.get("focus_mode")
        dispatch_payload = {
            "chat_id": request_body.chat_id,
            "message_id": request_body.message_id,
            "user_id": user_id,
            "user_id_hash": hashed_user_id,
            "message_history": [
                {
                    "role": message.get("role", "user"),
                    "content": message.get("content", ""),
                    "sender_name": message.get("name") or message.get("role", "user"),
                    "created_at": int(time.time()),
                }
                for message in history_messages
            ],
            "current_user_content": current_message["content"],
            "chat_has_title": request_body.encrypted_chat_metadata is None,
            "is_incognito": False,
            "is_external": True,
            "active_focus_id": focus_mode.get("focus_mode_id") if isinstance(focus_mode, dict) else None,
            "user_preferences": {"model": inference_request.get("model"), "apps_enabled": True},
            "memory_ids": inference_request.get("memory_ids", []),
            "recovery_task_id": enqueue.get("inference_task_id"),
            "recovery_preflight_id": preflight.get("preflight_id"),
            "recovery_turn_id": request_body.turn_id,
            "recovery_public_key": request_body.recovery_public_key,
            "chat_key_version": request_body.chat_key_version,
            "_api_key_name": api_key_info.get("api_key_encrypted_name", ""),
            "_api_key_hash": api_key_info.get("api_key_hash"),
            "_device_hash": device_hash,
        }
        from backend.core.api.app.services.skill_registry import get_global_registry

        result = await get_global_registry().dispatch_skill("ai", "ask", dispatch_payload)
        raw_result = _jsonable(result)
        task_id = raw_result.get("task_id") if isinstance(raw_result, dict) else None
        if task_id != enqueue.get("inference_task_id"):
            raise HTTPException(status_code=502, detail={"error": "inference_task_identity_mismatch"})
        await _execute_sdk_recovery(
            request,
            "mark_outbox_dispatched",
            {
                "protocol_version": 1,
                "outbox_id": enqueue.get("outbox_id"),
                "inference_task_id": task_id,
            },
        )
        return {
            "persistent": True,
            "chat_id": request_body.chat_id,
            "preflight": enqueue,
            "task_id": task_id,
        }

    history_messages = [message for message in request_body.history if isinstance(message, dict)]
    payload = {
        "messages": [*history_messages, {"role": "user", "content": request_body.message}],
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
    if request_body.focus_mode:
        payload["focus_mode"] = request_body.focus_mode

    from backend.core.api.app.services.skill_registry import get_global_registry

    result = await get_global_registry().dispatch_skill("ai", "ask", payload)
    if hasattr(result, "body_iterator"):
        return {"persistent": request_body.save_to_account, "stream": True}
    raw_result = _jsonable(result)
    content = _extract_chat_response_content(raw_result)
    model_name = _extract_chat_response_model_name(raw_result)
    return {
        "persistent": request_body.save_to_account,
        "chat_id": None,
        "response": {"content": content, "model_name": model_name, "raw": raw_result},
    }


@router.post("/chats/recovery/{inference_task_id}/claim")
async def claim_sdk_chat_recovery(
    request: Request,
    inference_task_id: str,
    request_body: SdkRecoveryClaimRequest,
) -> dict[str, Any]:
    api_key_info = await _authenticate_sdk_request(request)
    _require_chat_scope(api_key_info, "chat:create_saved")
    if request_body.protocol_version != 1:
        raise HTTPException(status_code=426, detail={"error": "client_update_required"})
    hashed_user_id, device_hash = _sdk_recovery_identity(api_key_info)
    return await _execute_sdk_recovery(
        request,
        "lease_job",
        {
            "protocol_version": 1,
            "job_id": _sdk_recovery_job_id(inference_task_id),
            "hashed_user_id": hashed_user_id,
            "device_hash": device_hash,
        },
    )


@router.post("/chats/recovery/{inference_task_id}/persist")
async def persist_sdk_chat_recovery(
    request: Request,
    inference_task_id: str,
    request_body: SdkRecoveryPersistRequest,
) -> dict[str, Any]:
    api_key_info = await _authenticate_sdk_request(request)
    _require_chat_scope(api_key_info, "chat:create_saved")
    if request_body.protocol_version != 1:
        raise HTTPException(status_code=426, detail={"error": "client_update_required"})
    hashed_user_id, device_hash = _sdk_recovery_identity(api_key_info)
    encrypted_message = dict(request_body.encrypted_assistant_message)
    if encrypted_message.get("client_message_id") != inference_task_id:
        raise HTTPException(status_code=400, detail={"error": "encrypted_assistant_message_identity_mismatch"})
    encrypted_message["hashed_user_id"] = hashed_user_id
    return await _execute_sdk_recovery(
        request,
        "persist_terminal",
        {
            "protocol_version": 1,
            "job_id": _sdk_recovery_job_id(inference_task_id),
            "hashed_user_id": hashed_user_id,
            "device_hash": device_hash,
            "lease_generation": request_body.lease_generation,
            "lease_token": request_body.lease_token,
            "expected_messages_v": request_body.expected_messages_v,
            "encrypted_assistant_message": encrypted_message,
        },
    )


@router.get("/chats/{chat_id}")
async def load_sdk_chat(
    request: Request,
    chat_id: str,
) -> dict[str, Any]:
    api_key_info = await _authenticate_sdk_request(request)
    _require_chat_scope(api_key_info, "chat:read_existing")
    user_id = api_key_info["user_id"]
    if not await request.app.state.directus_service.chat.check_chat_ownership(chat_id, user_id):
        raise HTTPException(status_code=404, detail="Chat not found")

    chat = await request.app.state.directus_service.chat.get_chat_metadata(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = await request.app.state.directus_service.chat.get_all_messages_for_chat(
        chat_id,
        decrypt_content=False,
    )
    hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
    embeds = await request.app.state.directus_service.embed.get_embeds_by_hashed_chat_id(hashed_chat_id)
    embed_keys = await request.app.state.directus_service.embed.get_embed_keys_by_hashed_chat_id(hashed_chat_id)
    chat_key_wrappers = await request.app.state.directus_service.chat_key_wrapper.list_authorized_wrappers(
        chat_id,
        user_id,
    )
    return {
        "chat": chat,
        "messages": messages or [],
        "embeds": embeds,
        "embed_keys": embed_keys,
        "chat_key_wrappers": chat_key_wrappers,
    }


@router.get("/drafts")
async def list_sdk_drafts(request: Request) -> dict[str, Any]:
    api_key_info = await _authenticate_sdk_request(request)
    _require_chat_scope(api_key_info, "chat:read_existing")
    user_id = api_key_info["user_id"]
    from backend.core.api.app.routes.handlers.websocket_handlers.get_draft_versions_handler import get_authoritative_user_draft

    chat_ids = await request.app.state.cache_service.get_chat_ids_versions(user_id)
    persisted = await request.app.state.directus_service.get_items(
        "drafts",
        params={
            "filter[hashed_user_id][_eq]": hashlib.sha256(user_id.encode()).hexdigest(),
            "fields": "chat_id",
            "limit": -1,
        },
    )
    for row in persisted or []:
        chat_id = str(row.get("chat_id") or "")
        if chat_id and chat_id not in chat_ids:
            chat_ids.append(chat_id)
    drafts = []
    for chat_id in chat_ids:
        draft = await get_authoritative_user_draft(
            request.app.state.cache_service,
            request.app.state.directus_service,
            user_id,
            chat_id,
        )
        if draft:
            encrypted_md, draft_v, encrypted_preview = draft
            drafts.append({
                "chat_id": chat_id,
                "encrypted_draft_md": encrypted_md,
                "encrypted_draft_preview": encrypted_preview,
                "draft_v": draft_v,
            })
    return {"drafts": drafts}


@router.get("/drafts/{chat_id}")
async def get_sdk_draft(request: Request, chat_id: str) -> dict[str, Any]:
    api_key_info = await _authenticate_sdk_request(request)
    _require_chat_scope(api_key_info, "chat:read_existing")
    from backend.core.api.app.routes.handlers.websocket_handlers.get_draft_versions_handler import get_authoritative_user_draft

    draft = await get_authoritative_user_draft(
        request.app.state.cache_service,
        request.app.state.directus_service,
        api_key_info["user_id"],
        chat_id,
    )
    if not draft:
        return {"draft": None}
    encrypted_md, draft_v, encrypted_preview = draft
    return {"draft": {
        "chat_id": chat_id,
        "encrypted_draft_md": encrypted_md,
        "encrypted_draft_preview": encrypted_preview,
        "draft_v": draft_v,
    }}


@router.api_route(
    "/{surface}",
    methods=["GET", "POST", "PATCH", "DELETE"],
)
async def sdk_surface_root(
    request: Request,
    surface: str,
    body: dict[str, Any] | None = Body(default=None),
) -> Any:
    return await _sdk_parity_placeholder(request, surface, body=body)


@router.api_route(
    "/{surface}/{path:path}",
    methods=["GET", "POST", "PATCH", "DELETE"],
)
async def sdk_surface_path(
    request: Request,
    surface: str,
    path: str,
    body: dict[str, Any] | None = Body(default=None),
) -> Any:
    return await _sdk_parity_placeholder(request, surface, path=path, body=body)


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
