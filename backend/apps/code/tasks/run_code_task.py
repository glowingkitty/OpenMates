# backend/apps/code/tasks/run_code_task.py
#
# Celery task for Code Run executions.
# Reads a pre-normalized file bundle from the API route, executes it in the
# restricted E2B provider, stores terminal output in Redis, and charges credits
# after completion using minute-rounded sandbox duration.

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from typing import Any

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.tasks.celery_config import app, get_worker_cache_service
from backend.shared.providers.e2b_code_runner import CodeRunFile, get_e2b_api_key_async, run_code_in_e2b


logger = logging.getLogger(__name__)

EXECUTION_TTL_SECONDS = 3600
RUN_CREDITS_PER_MINUTE = 10
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")
CODE_RUN_CHANNEL_PREFIX = "code_run_stream"


def _execution_key(execution_id: str) -> str:
    return f"code_run_execution:{execution_id}"


def _stream_channel(execution_id: str) -> str:
    return f"{CODE_RUN_CHANNEL_PREFIX}:{execution_id}"


def _event(kind: str, text: str, timestamp: float | None = None) -> dict[str, Any]:
    return {"kind": kind, "text": text, "timestamp": timestamp or time.time()}


async def _store_execution(execution_id: str, patch: dict[str, Any]) -> None:
    cache_service = await get_worker_cache_service()
    client = await cache_service.client
    key = _execution_key(execution_id)
    raw = await client.get(key)
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw) if raw else {}
    data.update(patch)
    data["updated_at"] = time.time()
    await client.set(key, json.dumps(data), ex=EXECUTION_TTL_SECONDS)
    await cache_service.publish_event(
        _stream_channel(execution_id),
        {"type": "code_run_update", "payload": {**patch, "updated_at": data["updated_at"]}},
    )


async def _append_output(execution_id: str, kind: str, text: str) -> None:
    cache_service = await get_worker_cache_service()
    client = await cache_service.client
    key = _execution_key(execution_id)
    raw = await client.get(key)
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw) if raw else {}
    events = data.setdefault("events", [])
    event = _event(kind, text)
    events.append(event)
    data["updated_at"] = time.time()
    await client.set(key, json.dumps(data), ex=EXECUTION_TTL_SECONDS)
    await cache_service.publish_event(
        _stream_channel(execution_id),
        {"type": "code_run_event", "payload": event},
    )


async def _charge_run_credits(
    payload: dict[str, Any],
    credits: int,
    execution_id: str,
    usage_details: dict[str, Any],
) -> int:
    charge_payload = {
        "user_id": payload["user_id"],
        "user_id_hash": payload["user_id_hash"],
        "credits": credits,
        "skill_id": "run",
        "app_id": "code",
        "usage_details": {
            "execution_id": execution_id,
            "target_embed_id": payload.get("target_embed_id"),
            "target_filename": payload.get("target_path"),
            "credits_per_minute": RUN_CREDITS_PER_MINUTE,
            "files_count": len(payload.get("files", [])),
            **usage_details,
        },
        "api_key_hash": None,
        "device_hash": None,
    }
    headers = {"Content-Type": "application/json"}
    if INTERNAL_API_SHARED_TOKEN:
        headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{INTERNAL_API_BASE_URL}/internal/billing/charge",
            json=charge_payload,
            headers=headers,
        )
        response.raise_for_status()
    return credits


async def _clear_active_run(payload: dict[str, Any]) -> None:
    active_key = payload.get("active_run_key")
    active_owner = payload.get("active_run_owner")
    if not active_key or not active_owner:
        return
    cache_service = await get_worker_cache_service()
    client = await cache_service.client
    await client.srem(active_key, active_owner)


def _run_code_execution(execution_id: str, payload: dict[str, Any]) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    secrets_manager = SecretsManager()

    def run_async(coro: Any) -> Any:
        return loop.run_until_complete(coro)

    started_at = time.time()
    billing_state = {"charged_credits": 0, "charged_minutes": 0}
    run_async(_store_execution(execution_id, {"status": "preparing_sandbox", "started_at": started_at}))

    def charge_initial_minute() -> None:
        if billing_state["charged_credits"]:
            return
        charged_credits = run_async(
            _charge_run_credits(
                payload,
                RUN_CREDITS_PER_MINUTE,
                execution_id,
                {"billing_phase": "initial_minute", "charged_minutes": 1},
            )
        )
        billing_state["charged_credits"] = charged_credits
        billing_state["charged_minutes"] = 1
        run_async(_store_execution(
            execution_id,
            {"charged_credits": charged_credits, "charged_minutes": 1},
        ))

    def on_output(kind: str, text: str) -> None:
        if kind == "status":
            if text.startswith("User code setup started"):
                charge_initial_minute()
            elif text.startswith("Sandbox started"):
                run_async(_store_execution(execution_id, {"status": "preparing_sandbox"}))
            elif text.startswith("Uploading"):
                run_async(_store_execution(execution_id, {"status": "uploading_files"}))
            elif text.startswith("Installing"):
                run_async(_store_execution(execution_id, {"status": "installing_dependencies"}))
            elif text.startswith("Running"):
                run_async(_store_execution(execution_id, {"status": "running"}))
        run_async(_append_output(execution_id, kind, text))

    try:
        run_async(secrets_manager.initialize())
        api_key = run_async(get_e2b_api_key_async(secrets_manager))
        files = [CodeRunFile(**item) for item in payload["files"]]
        result = run_code_in_e2b(files, payload["target_path"], on_output, api_key)
        duration = result.duration_seconds
        status = "finished" if result.exit_code in (None, 0) else "failed"
        charged_minutes = max(1, math.ceil(duration / 60))
        extra_minutes = max(0, charged_minutes - billing_state["charged_minutes"])
        extra_credits = 0
        if extra_minutes:
            extra_credits = run_async(
                _charge_run_credits(
                    payload,
                    extra_minutes * RUN_CREDITS_PER_MINUTE,
                    execution_id,
                    {
                        "billing_phase": "extra_minutes",
                        "duration_seconds": round(duration, 3),
                        "charged_minutes": extra_minutes,
                        "total_charged_minutes": charged_minutes,
                    },
                )
            )
        credits = billing_state["charged_credits"] + extra_credits
        run_async(_append_output(
            execution_id,
            "status",
            f"Exited with code {result.exit_code if result.exit_code is not None else 0} in {duration:.1f}s. Charged {charged_minutes} minute(s), {credits} credits.\n",
        ))
        if result.output_truncated:
            run_async(_append_output(execution_id, "stderr", "Output was truncated after 100 KB.\n"))
        run_async(_store_execution(
            execution_id,
            {
                "status": status,
                "exit_code": result.exit_code if result.exit_code is not None else 0,
                "duration_seconds": duration,
                "charged_credits": credits,
                "charged_minutes": charged_minutes,
                "sandbox_id": result.sandbox_id,
                "finished_at": time.time(),
            },
        ))
    except Exception as exc:
        logger.error("Code Run execution %s failed: %s", execution_id, exc, exc_info=True)
        run_async(_append_output(execution_id, "stderr", f"Run failed: {exc}\n"))
        run_async(_store_execution(
            execution_id,
            {
                "status": "failed",
                "error": str(exc),
                "duration_seconds": time.time() - started_at,
                "finished_at": time.time(),
            },
        ))
    finally:
        run_async(_clear_active_run(payload))
        run_async(secrets_manager.aclose())
        loop.close()


@app.task(name="code.run_execution", queue="app_code")
def run_code_execution_task(execution_id: str, payload: dict[str, Any]) -> None:
    _run_code_execution(execution_id, payload)
