"""
Health-check orchestration for core services and provider summaries.
Architecture: Independent checker, reads provider status from core API /v1/health.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status service tests not added yet)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import (
    CORE_SERVICES,
    ENV_DEV,
    ENV_PROD,
    GROUP_AI,
    HTTP_TIMEOUT_SECONDS,
    STATUS_DEGRADED,
    STATUS_DOWN,
    STATUS_OPERATIONAL,
    STATUS_UNKNOWN,
    get_base_urls,
    get_group_for_external_service,
)
from .database import ServiceStatusRecord, add_response_time_sample, record_status_event_if_changed, upsert_service_status


@dataclass
class CheckResult:
    status: str
    response_time_ms: float | None
    error_message: str | None


def _normalize_health_status(raw_status: str) -> str:
    if raw_status in {"healthy", "operational"}:
        return STATUS_OPERATIONAL
    if raw_status == "degraded":
        return STATUS_DEGRADED
    if raw_status == "unknown":
        return STATUS_UNKNOWN
    return STATUS_DOWN


def _latest_response_time(payload: dict[str, Any]) -> float | None:
    response_times = payload.get("response_times_ms")
    if not isinstance(response_times, dict) or not response_times:
        return None
    try:
        latest_timestamp = max(response_times.keys(), key=lambda key: float(key))
        value = response_times[latest_timestamp]
        return float(value)
    except Exception:
        return None


async def _check_http_ok(client: httpx.AsyncClient, url: str) -> CheckResult:
    if not url:
        return CheckResult(status=STATUS_UNKNOWN, response_time_ms=None, error_message="missing_url")
    started_at = time.perf_counter()
    try:
        response = await client.get(url)
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        if response.status_code >= 500:
            return CheckResult(status=STATUS_DOWN, response_time_ms=elapsed_ms, error_message=f"http_{response.status_code}")
        if response.status_code >= 400:
            return CheckResult(
                status=STATUS_DEGRADED,
                response_time_ms=elapsed_ms,
                error_message=f"http_{response.status_code}",
            )
        return CheckResult(status=STATUS_OPERATIONAL, response_time_ms=elapsed_ms, error_message=None)
    except httpx.TimeoutException:
        return CheckResult(status=STATUS_DOWN, response_time_ms=None, error_message="timeout")
    except httpx.HTTPError as exc:
        return CheckResult(status=STATUS_DOWN, response_time_ms=None, error_message=f"http_error:{type(exc).__name__}")


async def _persist_result(
    db_path: str,
    *,
    environment: str,
    group_name: str,
    service_id: str,
    service_name: str,
    status: str,
    response_time_ms: float | None,
    error_message: str | None,
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    await record_status_event_if_changed(
        db_path,
        environment=environment,
        group_name=group_name,
        service_id=service_id,
        service_name=service_name,
        new_status=status,
        response_time_ms=response_time_ms,
        error_message=error_message,
    )
    await upsert_service_status(
        db_path,
        ServiceStatusRecord(
            environment=environment,
            group_name=group_name,
            service_id=service_id,
            service_name=service_name,
            status=status,
            response_time_ms=response_time_ms,
            last_error=error_message,
            last_check_at=timestamp,
        ),
    )
    await add_response_time_sample(
        db_path,
        environment=environment,
        service_id=service_id,
        response_time_ms=response_time_ms,
    )


async def _persist_core_provider_data(
    db_path: str,
    *,
    environment: str,
    payload: dict[str, Any] | None,
    core_api_available: bool,
) -> None:
    providers = (payload or {}).get("providers", {})
    external_services = (payload or {}).get("external_services", {})

    async def persist_unknown(service_id: str, service_name: str, group_name: str) -> None:
        await _persist_result(
            db_path,
            environment=environment,
            group_name=group_name,
            service_id=service_id,
            service_name=service_name,
            status=STATUS_UNKNOWN,
            response_time_ms=None,
            error_message="core_api_unreachable",
        )

    if not core_api_available:
        all_ids = set(providers.keys()) | set(external_services.keys())
        for service_id in all_ids:
            group_name = GROUP_AI if service_id in providers else get_group_for_external_service(service_id)
            await persist_unknown(service_id, service_id.replace("_", " ").title(), group_name)
        return

    for provider_id, provider_data in providers.items():
        provider_status = _normalize_health_status(str(provider_data.get("status", "unknown")))
        provider_response_ms = _latest_response_time(provider_data)
        provider_error = provider_data.get("last_error")
        await _persist_result(
            db_path,
            environment=environment,
            group_name=GROUP_AI,
            service_id=provider_id,
            service_name=provider_id.replace("_", " ").title(),
            status=provider_status,
            response_time_ms=provider_response_ms,
            error_message=str(provider_error) if provider_error else None,
        )

    for service_id, service_data in external_services.items():
        service_status = _normalize_health_status(str(service_data.get("status", "unknown")))
        service_response_ms = _latest_response_time(service_data)
        service_error = service_data.get("last_error")
        await _persist_result(
            db_path,
            environment=environment,
            group_name=get_group_for_external_service(service_id),
            service_id=service_id,
            service_name=service_id.replace("_", " ").title(),
            status=service_status,
            response_time_ms=service_response_ms,
            error_message=str(service_error) if service_error else None,
        )


async def _check_environment(db_path: str, environment: str, urls: dict[str, str]) -> None:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
        core_health_payload: dict[str, Any] | None = None
        core_api_is_available = False

        for service in CORE_SERVICES:
            target_url = urls[service.service_id]
            if service.service_id == "core_api":
                target_url = f"{target_url.rstrip('/')}/v1/health"
            elif service.service_id in {"upload_server", "preview_server"}:
                target_url = f"{target_url.rstrip('/')}/health" if target_url else ""

            result = await _check_http_ok(client, target_url)
            await _persist_result(
                db_path,
                environment=environment,
                group_name=service.group_name,
                service_id=service.service_id,
                service_name=service.service_name,
                status=result.status,
                response_time_ms=result.response_time_ms,
                error_message=result.error_message,
            )

            if service.service_id == "core_api" and result.status != STATUS_DOWN:
                core_api_is_available = True
                try:
                    response = await client.get(target_url)
                    core_health_payload = response.json()
                except Exception:
                    core_api_is_available = False

        await _persist_core_provider_data(
            db_path,
            environment=environment,
            payload=core_health_payload,
            core_api_available=core_api_is_available,
        )


async def run_health_checks_once(db_path: str) -> None:
    urls = get_base_urls()
    await asyncio.gather(
        _check_environment(db_path, ENV_PROD, urls[ENV_PROD]),
        _check_environment(db_path, ENV_DEV, urls[ENV_DEV]),
    )
