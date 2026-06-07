# backend/apps/code/tasks/run_application_preview_task.py
#
# Worker lifecycle for generated application previews.
# The public API creates viewer-owned session records; this worker resolves a
# prepared payload into E2B planning/provider calls and updates the same Redis
# session with sandbox metadata consumed by the preview gateway.

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

from backend.core.api.app.routes.application_preview import (
    APPLICATION_PREVIEW_SESSION_TTL_SECONDS,
    application_preview_session_key,
)
from backend.shared.providers.e2b_application_preview import (
    ApplicationPreviewEntrypoint,
    ApplicationPreviewFile,
    ApplicationPreviewRuntime,
    kill_application_preview_sandbox_in_e2b,
    plan_application_preview_startup,
    start_application_preview_in_e2b,
)


logger = logging.getLogger(__name__)

try:  # pragma: no cover - local unit tests do not install Celery.
    from backend.core.api.app.tasks.celery_config import app, get_worker_cache_service
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async, redact_execution_output
except ModuleNotFoundError:  # pragma: no cover - exercised by lightweight unit imports.
    app = None
    get_worker_cache_service = None
    SecretsManager = None
    get_e2b_api_key_async = None

    def redact_execution_output(value: str) -> str:
        return value


ProviderStart = Callable[..., ApplicationPreviewRuntime | Awaitable[ApplicationPreviewRuntime]]
ProviderStop = Callable[..., bool | Awaitable[bool]]


async def run_application_preview_session(
    *,
    cache_service: Any,
    session_id: str,
    payload: dict[str, Any],
    provider_start: ProviderStart | None = None,
    now: float | None = None,
) -> None:
    started_at = now if now is not None else time.time()
    await _patch_session(
        cache_service,
        session_id,
        {
            "status": "starting",
            "updated_at": started_at,
            "events+": [{"kind": "status", "text": "Starting application preview sandbox...", "timestamp": started_at}],
        },
    )

    try:
        files = [_file_from_payload(item) for item in payload.get("files", []) if isinstance(item, dict)]
        entrypoints = [_entrypoint_from_payload(item) for item in payload.get("entrypoints", []) if isinstance(item, dict)]
        plan_application_preview_startup(files=files, entrypoints=entrypoints)
        runtime = await _start_runtime(
            provider_start,
            files=files,
            entrypoints=entrypoints,
            api_key=str(payload.get("api_key") or ""),
            enable_internet=bool(payload.get("enable_internet", True)),
        )
        running_at = now if now is not None else time.time()
        await _patch_session(
            cache_service,
            session_id,
            {
                "status": "running",
                "sandbox_id": runtime.sandbox_id,
                "upstream_base_url": runtime.upstream_base_url,
                "upstream_base_urls": runtime.upstream_base_urls or {},
                "ports": runtime.ports,
                "latest_screenshot_url": runtime.latest_screenshot_url,
                "latest_screenshot_captured_at": running_at if runtime.latest_screenshot_url else None,
                "updated_at": running_at,
                "billing_state.billable_started_at": running_at,
                "events+": [{"kind": "status", "text": "Application preview is running.", "timestamp": running_at}],
            },
        )
    except Exception as exc:
        safe_error = redact_execution_output(str(exc))
        logger.error("Application preview session %s failed: %s", session_id, safe_error, exc_info=True)
        await _patch_session(
            cache_service,
            session_id,
            {
                "status": "failed",
                "error": safe_error,
                "updated_at": time.time() if now is None else now,
                "events+": [{"kind": "error", "text": safe_error, "timestamp": time.time() if now is None else now}],
            },
        )


async def stop_application_preview_sandbox(
    *,
    cache_service: Any,
    session_id: str,
    sandbox_id: str,
    api_key: str,
    provider_stop: ProviderStop | None = None,
    now: float | None = None,
) -> None:
    stopped_at = now if now is not None else time.time()
    try:
        stopped = await _stop_runtime(provider_stop, sandbox_id=sandbox_id, api_key=api_key)
        text = "Application preview sandbox stopped." if stopped else "Application preview sandbox stop was requested."
        await _patch_session(
            cache_service,
            session_id,
            {
                "sandbox_stopped_at": stopped_at,
                "updated_at": stopped_at,
                "events+": [{"kind": "status", "text": text, "timestamp": stopped_at}],
            },
        )
    except Exception as exc:
        safe_error = redact_execution_output(str(exc))
        logger.error("Application preview sandbox stop %s failed: %s", session_id, safe_error, exc_info=True)
        await _patch_session(
            cache_service,
            session_id,
            {
                "sandbox_stop_error": safe_error,
                "updated_at": stopped_at,
                "events+": [{"kind": "error", "text": safe_error, "timestamp": stopped_at}],
            },
        )


def _file_from_payload(item: dict[str, Any]) -> ApplicationPreviewFile:
    return ApplicationPreviewFile(
        path=str(item.get("path") or ""),
        content=str(item.get("content") or ""),
        content_base64=item.get("content_base64") if isinstance(item.get("content_base64"), str) else None,
        mime_type=item.get("mime_type") if isinstance(item.get("mime_type"), str) else None,
        source_embed_id=item.get("source_embed_id") if isinstance(item.get("source_embed_id"), str) else None,
    )


def _entrypoint_from_payload(item: dict[str, Any]) -> ApplicationPreviewEntrypoint:
    return ApplicationPreviewEntrypoint(
        name=str(item.get("name") or ""),
        command=str(item.get("command") or ""),
        port=int(item.get("port") or 0),
    )


async def _start_runtime(
    provider_start: ProviderStart | None,
    **kwargs: Any,
) -> ApplicationPreviewRuntime:
    starter = provider_start or start_application_preview_in_e2b
    result = starter(**kwargs)
    if asyncio.iscoroutine(result):
        return await result
    return result


async def _stop_runtime(
    provider_stop: ProviderStop | None,
    **kwargs: Any,
) -> bool:
    stopper = provider_stop or kill_application_preview_sandbox_in_e2b
    result = stopper(**kwargs)
    if asyncio.iscoroutine(result):
        return bool(await result)
    return bool(result)


async def _patch_session(cache_service: Any, session_id: str, patch: dict[str, Any]) -> None:
    client = await cache_service.client
    key = application_preview_session_key(session_id)
    raw = await client.get(key)
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw) if raw else {}
    events = patch.pop("events+", [])
    for key_path, value in patch.items():
        if "." in key_path:
            parent, child = key_path.split(".", 1)
            container = data.setdefault(parent, {})
            if isinstance(container, dict):
                container[child] = value
        else:
            data[key_path] = value
    if events:
        data.setdefault("events", []).extend(events)
    await client.set(application_preview_session_key(session_id), json.dumps(data), ex=APPLICATION_PREVIEW_SESSION_TTL_SECONDS)


def _run_application_preview_session_sync(session_id: str, payload: dict[str, Any]) -> None:
    if get_worker_cache_service is None or SecretsManager is None or get_e2b_api_key_async is None:
        raise RuntimeError("Application preview worker dependencies are not available")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    secrets_manager = SecretsManager()
    try:
        cache_service = loop.run_until_complete(get_worker_cache_service())
        loop.run_until_complete(secrets_manager.initialize())
        api_key = loop.run_until_complete(get_e2b_api_key_async(secrets_manager))
        loop.run_until_complete(run_application_preview_session(
            cache_service=cache_service,
            session_id=session_id,
            payload={**payload, "api_key": api_key},
        ))
    finally:
        loop.run_until_complete(secrets_manager.aclose())
        loop.close()


def _stop_application_preview_sandbox_sync(session_id: str, sandbox_id: str) -> None:
    if get_worker_cache_service is None or SecretsManager is None or get_e2b_api_key_async is None:
        raise RuntimeError("Application preview worker dependencies are not available")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    secrets_manager = SecretsManager()
    try:
        cache_service = loop.run_until_complete(get_worker_cache_service())
        loop.run_until_complete(secrets_manager.initialize())
        api_key = loop.run_until_complete(get_e2b_api_key_async(secrets_manager))
        loop.run_until_complete(stop_application_preview_sandbox(
            cache_service=cache_service,
            session_id=session_id,
            sandbox_id=sandbox_id,
            api_key=api_key,
        ))
    finally:
        loop.run_until_complete(secrets_manager.aclose())
        loop.close()


if app is not None:  # pragma: no cover - registration path runs in worker image.
    @app.task(name="code.run_application_preview", queue="app_code")
    def run_application_preview_task(session_id: str, payload: dict[str, Any]) -> None:
        _run_application_preview_session_sync(session_id, payload)


    @app.task(name="code.stop_application_preview", queue="app_code")
    def stop_application_preview_task(session_id: str, sandbox_id: str) -> None:
        _stop_application_preview_sandbox_sync(session_id, sandbox_id)
