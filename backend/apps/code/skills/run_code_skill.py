# backend/apps/code/skills/run_code_skill.py
#
# Assistant skill for Code Run.
# The skill reuses the existing /v1/code/run collection/start path so assistant,
# web, REST, and SDK surfaces share validation, E2B execution, billing, and
# status semantics instead of creating a second sandbox entrypoint.

from __future__ import annotations

import inspect
import time
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill


CODE_RUN_ASSISTANT_AUTH_TTL_SECONDS = 60 * 60
CODE_RUN_ASSISTANT_MAX_UNPROMPTED_RERUNS = 2
CODE_RUN_ASSISTANT_MAX_AUTO_RUNS = 1 + CODE_RUN_ASSISTANT_MAX_UNPROMPTED_RERUNS


class RunCodeRequest(BaseModel):
    chat_id: str | None = Field(default=None, description="Chat ID containing the code embeds to run.")
    target_embed_id: str = Field(description="Code embed ID to execute as the entrypoint.")
    enable_internet: bool = Field(default=True, description="Allow outbound internet access from the E2B sandbox.")
    selected_embed_ids: list[str] | None = Field(default=None, description="Optional related embed IDs to include in the run.")
    dependency_installs: list[dict[str, Any]] = Field(default_factory=list, description="Selected package installs for this run.")
    user_confirmed_unmodified_code: bool = Field(
        default=False,
        description="True only after the user explicitly confirms running code not created or edited by the assistant in this turn.",
    )


class RunCodeResponse(BaseModel):
    execution_id: str | None = None
    task_id: str | None = None
    status: str = "processing"
    target_filename: str | None = None
    files: list[str] = Field(default_factory=list)
    credits_per_minute: int | None = None
    stream_path: str | None = None
    status_path: str | None = None
    error: str | None = None


def assistant_code_run_authorization_key(chat_id: str, message_id: str, target_embed_id: str) -> str:
    return f"code_run_assistant_authorized:{chat_id}:{message_id}:{target_embed_id}"


def assistant_code_run_attempt_key(chat_id: str, message_id: str, target_embed_id: str) -> str:
    return f"code_run_assistant_attempts:{chat_id}:{message_id}:{target_embed_id}"


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _cache_get(cache_service: Any, key: str) -> Any:
    if cache_service is None:
        return None
    getter = getattr(cache_service, "get", None)
    if callable(getter):
        return await _maybe_await(getter(key))
    client_attr = getattr(cache_service, "client", None)
    client = await _maybe_await(client_attr) if client_attr is not None else None
    if client and hasattr(client, "get"):
        raw = await client.get(key)
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return raw
    return None


async def _cache_set(cache_service: Any, key: str, value: Any, ttl: int) -> bool:
    if cache_service is None:
        return False
    setter = getattr(cache_service, "set", None)
    if callable(setter):
        return bool(await _maybe_await(setter(key, value, ttl=ttl)))
    client_attr = getattr(cache_service, "client", None)
    client = await _maybe_await(client_attr) if client_attr is not None else None
    if client and hasattr(client, "set"):
        return bool(await client.set(key, value, ex=ttl))
    return False


async def _increment_cache_counter(cache_service: Any, key: str, ttl: int) -> int:
    client_attr = getattr(cache_service, "client", None) if cache_service is not None else None
    client = await _maybe_await(client_attr) if client_attr is not None else None
    if client and hasattr(client, "incr"):
        count = int(await client.incr(key))
        if count == 1 and hasattr(client, "expire"):
            await client.expire(key, ttl)
        return count
    current = await _cache_get(cache_service, key)
    try:
        count = int(current or 0) + 1
    except (TypeError, ValueError):
        count = 1
    await _cache_set(cache_service, key, count, ttl)
    return count


async def mark_assistant_code_run_authorized(
    cache_service: Any,
    *,
    chat_id: str,
    message_id: str,
    target_embed_id: str,
    action: str,
) -> bool:
    """Mark an assistant-created/edited code embed as runnable without user confirmation."""
    if not chat_id or not message_id or not target_embed_id:
        return False
    return await _cache_set(
        cache_service,
        assistant_code_run_authorization_key(chat_id, message_id, target_embed_id),
        {"action": action, "created_at": int(time.time())},
        CODE_RUN_ASSISTANT_AUTH_TTL_SECONDS,
    )


async def _authorize_assistant_code_run(
    cache_service: Any,
    *,
    chat_id: str,
    message_id: str,
    target_embed_id: str,
    user_confirmed_unmodified_code: bool,
) -> tuple[bool, str]:
    if user_confirmed_unmodified_code:
        return True, "user_confirmed"
    marker = await _cache_get(
        cache_service,
        assistant_code_run_authorization_key(chat_id, message_id, target_embed_id),
    )
    if not marker:
        return False, "Code Run can auto-run only code the assistant created or edited in this turn. Ask the user before running unmodified user code."
    attempt_count = await _increment_cache_counter(
        cache_service,
        assistant_code_run_attempt_key(chat_id, message_id, target_embed_id),
        CODE_RUN_ASSISTANT_AUTH_TTL_SECONDS,
    )
    if attempt_count > CODE_RUN_ASSISTANT_MAX_AUTO_RUNS:
        return False, "Code Run already used the initial run and two unprompted reruns for this code. Ask the user before running it again."
    return True, "assistant_current_turn"


def create_directus_service(*, cache_service: Any, encryption_service: Any) -> Any:
    from backend.core.api.app.services.directus import DirectusService

    return DirectusService(cache_service=cache_service, encryption_service=encryption_service)


async def collect_code_files_for_assistant(**kwargs: Any) -> tuple[list[dict[str, Any]], str]:
    from backend.core.api.app.routes.code_execution import _collect_code_files

    return await _collect_code_files(**kwargs)


async def start_code_run_for_assistant(**kwargs: Any) -> Any:
    from backend.core.api.app.routes.code_execution import start_code_run_execution

    return await start_code_run_execution(**kwargs)


def _dependency_installs(items: list[dict[str, Any]]) -> list[Any]:
    if not items:
        return []
    from backend.core.api.app.routes.code_execution import CodeRunDependencyInstall

    return [CodeRunDependencyInstall.model_validate(item) for item in items]


class RunCodeSkill(BaseSkill):
    """Run assistant-created or explicitly confirmed code in an E2B sandbox."""

    async def execute(self, request: RunCodeRequest, **kwargs: Any) -> RunCodeResponse:
        chat_id = request.chat_id or kwargs.get("chat_id") or self._current_chat_id
        message_id = kwargs.get("message_id") or self._current_message_id
        user_id = kwargs.get("user_id")
        user_vault_key_id = kwargs.get("user_vault_key_id")
        cache_service = kwargs.get("cache_service")
        encryption_service = kwargs.get("encryption_service")
        if not chat_id or not message_id or not user_id or not user_vault_key_id or cache_service is None or encryption_service is None:
            return RunCodeResponse(status="error", error="Code Run requires chat, message, user, cache, and encryption context.")

        authorized, reason = await _authorize_assistant_code_run(
            cache_service,
            chat_id=str(chat_id),
            message_id=str(message_id),
            target_embed_id=request.target_embed_id,
            user_confirmed_unmodified_code=request.user_confirmed_unmodified_code,
        )
        if not authorized:
            return RunCodeResponse(status="requires_confirmation", error=reason)

        directus_service = create_directus_service(cache_service=cache_service, encryption_service=encryption_service)
        user_fields = await directus_service.get_user_fields_direct(str(user_id), ["credits"])
        credits = int((user_fields or {}).get("credits") or 0)
        current_user = SimpleNamespace(
            id=str(user_id),
            username="assistant-code-run-user",
            vault_key_id=str(user_vault_key_id),
            credits=credits,
        )
        files, target_path = await collect_code_files_for_assistant(
            chat_id=str(chat_id),
            target_embed_id=request.target_embed_id,
            client_files=[],
            client_attachments=[],
            selected_embed_ids=request.selected_embed_ids,
            current_user=current_user,
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
        )
        execution = await start_code_run_for_assistant(
            current_user=current_user,
            cache_service=cache_service,
            files=files,
            target_path=target_path,
            enable_internet=request.enable_internet,
            chat_id=str(chat_id),
            target_embed_id=request.target_embed_id,
            message_id=str(message_id),
            dependency_installs=_dependency_installs(request.dependency_installs),
            api_key_hash=kwargs.get("api_key_hash"),
            device_hash=kwargs.get("device_hash"),
            assistant_async_task=True,
        )
        return RunCodeResponse(
            execution_id=execution.execution_id,
            task_id=execution.execution_id,
            status="processing",
            target_filename=execution.target_filename,
            files=list(execution.files),
            credits_per_minute=execution.credits_per_minute,
            stream_path=f"/v1/code/run/{execution.execution_id}/stream",
            status_path=f"/v1/code/run/{execution.execution_id}",
        )
