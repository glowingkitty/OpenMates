"""Run bounded, provider-free runtime checks for CLI-managed servers.

The host CLI invokes this module through Docker Compose after container
readiness and from its independent systemd monitor. It never exposes an HTTP
endpoint and never enters model inference or payment mutation paths.
Spec: docs/specs/post-update-runtime-health-alerting/spec.yml.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
import json
import os
import sys
import time
import uuid
from typing import Awaitable, Callable, Optional

import httpx

from backend.core.api.app.utils.server_mode import RuntimeDeploymentMode, resolve_runtime_deployment_mode


GLOBAL_DEADLINE_SECONDS = 60
CheckRunner = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class CheckDefinition:
    id: str
    timeout_seconds: float
    runner: Optional[CheckRunner] = None
    required: bool = True


@dataclass
class CheckResult:
    id: str
    status: str
    required: bool
    duration_ms: int
    label: Optional[str] = None
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    failure_class: Optional[str] = None
    sanitized_reason: Optional[str] = None
    cleanup_status: str = "not_required"


_ROLE_CHECKS = {
    "core": (
        ("compose.required_services", 15),
        ("http.role_health", 10),
        ("core.database", 10),
        ("core.cache", 10),
        ("core.vault", 10),
        ("core.worker_queue", 15),
        ("core.scheduler_freshness", 5),
        ("core.chat_plumbing", 20),
    ),
    "upload": (
        ("compose.required_services", 15),
        ("http.role_health", 10),
        ("core.vault", 10),
        ("upload.antivirus", 10),
    ),
    "preview": (
        ("compose.required_services", 15),
        ("http.role_health", 10),
        ("preview.renderer", 15),
    ),
}

_BILLING_CHECKS = (
    ("billing.mode_enabled", 5),
    ("billing.stripe_account_read", 15),
    ("billing.routes_registered", 5),
    ("billing.workers_registered", 10),
    ("billing.webhook_configured", 5),
    ("billing.health_freshness", 5),
)


def build_check_inventory(role: str, mode: RuntimeDeploymentMode) -> list[CheckDefinition]:
    if role not in _ROLE_CHECKS:
        raise ValueError(f"unsupported_role:{role}")
    checks = [CheckDefinition(check_id, timeout) for check_id, timeout in _ROLE_CHECKS[role]]
    if role == "core" and mode.billing_enabled:
        checks.extend(CheckDefinition(check_id, timeout) for check_id, timeout in _BILLING_CHECKS)
    return checks


async def _execute_one(check: CheckDefinition) -> CheckResult:
    started = time.monotonic()
    started_at = int(time.time())
    if check.runner is None:
        return CheckResult(check.id, "skipped", check.required, 0, check.id, started_at, int(time.time()), "runner_unavailable", "runner_unavailable")
    try:
        await asyncio.wait_for(check.runner(), timeout=check.timeout_seconds)
        return CheckResult(check.id, "passed", check.required, int((time.monotonic() - started) * 1000), check.id, started_at, int(time.time()))
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        return CheckResult(check.id, "failed", check.required, int((time.monotonic() - started) * 1000), check.id, started_at, int(time.time()), "timeout", "check_timed_out", "completed")
    except Exception as exc:
        failure_class = getattr(exc, "failure_class", type(exc).__name__.lower())
        return CheckResult(check.id, "failed", check.required, int((time.monotonic() - started) * 1000), check.id, started_at, int(time.time()), str(failure_class), "check_failed", "completed")


async def execute_checks(
    checks: list[CheckDefinition],
    *,
    global_deadline_seconds: float = GLOBAL_DEADLINE_SECONDS,
) -> list[CheckResult]:
    tasks = [asyncio.create_task(_execute_one(check), name=check.id) for check in checks]
    done, pending = await asyncio.wait(tasks, timeout=global_deadline_seconds)
    results = [task.result() for task in done]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
        required_by_id = {check.id: check.required for check in checks}
        results.extend(
            CheckResult(task.get_name(), "failed", required_by_id[task.get_name()], int(global_deadline_seconds * 1000), task.get_name(), None, int(time.time()), "timeout", "global_deadline_exceeded", "completed")
            for task in pending
        )
    return sorted(results, key=lambda result: [check.id for check in checks].index(result.id))


async def _http_get(url: str) -> None:
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
        response = await client.get(url)
        response.raise_for_status()


def _cache_client():
    import redis.asyncio as redis

    raw_url = os.getenv("DRAGONFLY_URL", "cache:6379").removeprefix("redis://")
    host, _, raw_port = raw_url.partition(":")
    return redis.Redis(
        host=host,
        port=int(raw_port or "6379"),
        password=os.getenv("DRAGONFLY_PASSWORD"),
        socket_connect_timeout=5,
        socket_timeout=5,
        decode_responses=True,
    )


async def _check_cache() -> None:
    client = _cache_client()
    try:
        if not await client.ping():
            raise RuntimeError("cache_ping_failed")
    finally:
        await client.aclose()


async def _check_vault() -> None:
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
        response = await client.get(f"{os.getenv('VAULT_URL', 'http://vault:8200')}/v1/sys/health")
        if response.status_code not in {200, 429, 472, 473}:
            response.raise_for_status()


async def _check_tcp(host: str, port: int) -> None:
    _reader, writer = await asyncio.open_connection(host, port)
    writer.close()
    await writer.wait_closed()


async def _check_required_services(role: str) -> None:
    if role == "core":
        await asyncio.gather(_http_get("http://localhost:8000/v1/health"), _http_get("http://cms:8055/server/ping"), _check_cache(), _check_vault())
    elif role == "upload":
        await asyncio.gather(_http_get("http://app-uploads:8000/health"), _check_vault())
    else:
        await _http_get("http://preview:8080/health")


async def _check_worker_queue() -> None:
    probe_id = uuid.uuid4().hex
    task_name = "runtime_health.worker_probe"
    if os.getenv("SERVER_ENVIRONMENT") == "development":
        task_name = os.getenv("OPENMATES_RUNTIME_HEALTH_PROBE_TASK", task_name)

    def dispatch_probe() -> dict:
        from backend.core.api.app.tasks.celery_config import app

        result = app.send_task(task_name, args=[probe_id], queue="app_ai")
        try:
            return result.get(timeout=10, propagate=True)
        finally:
            result.forget()

    payload = await asyncio.to_thread(dispatch_probe)
    if payload.get("probe_id") != probe_id:
        raise RuntimeError("worker_probe_mismatch")


async def _check_scheduler_freshness() -> None:
    client = _cache_client()
    try:
        raw_timestamp = await client.get("runtime_health:scheduler:last_seen")
        if raw_timestamp is not None and time.time() - int(raw_timestamp) <= 15 * 60:
            return
    finally:
        await client.aclose()

    def dispatch_heartbeat() -> None:
        from backend.core.api.app.tasks.celery_config import app

        result = app.send_task("runtime_health.scheduler_heartbeat", queue="health_check")
        try:
            result.get(timeout=10, propagate=True)
        finally:
            result.forget()

    await asyncio.to_thread(dispatch_heartbeat)


async def _check_chat_plumbing() -> None:
    """Exercise the same app_ai dispatch/result transport without model inference."""
    await _check_worker_queue()


async def _check_billing_mode() -> None:
    if not resolve_runtime_deployment_mode().billing_enabled:
        raise RuntimeError("billing_mode_disabled")


async def _check_stripe_account_read() -> None:
    import stripe
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    environment = resolve_runtime_deployment_mode().environment
    secret_key = "production_secret_key" if environment == "production" else "sandbox_secret_key"
    api_key = await SecretsManager().get_secret("kv/data/providers/stripe", secret_key)
    if not api_key:
        raise RuntimeError("stripe_credential_missing")

    def retrieve_account() -> None:
        stripe.api_key = api_key
        stripe.Account.retrieve()

    await asyncio.to_thread(retrieve_account)


async def _check_billing_routes() -> None:
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
        response = await client.get("http://localhost:8000/openapi.json")
        response.raise_for_status()
        paths = response.json().get("paths", {})
    if not any("billing" in path or "payment" in path for path in paths):
        raise RuntimeError("billing_routes_missing")


async def _check_billing_workers() -> None:
    from backend.core.api.app.tasks.celery_config import app

    registered = await asyncio.to_thread(lambda: app.control.inspect(timeout=5).registered() or {})
    tasks = {task for worker_tasks in registered.values() for task in worker_tasks}
    if not any("billing" in task or "payment" in task for task in tasks):
        raise RuntimeError("billing_workers_missing")


async def _check_billing_webhook() -> None:
    if not any(os.getenv(key) for key in ("STRIPE_WEBHOOK_SECRET", "SECRET__STRIPE__WEBHOOK_SECRET")):
        raise RuntimeError("billing_webhook_unconfigured")


async def _check_billing_freshness() -> None:
    client = _cache_client()
    try:
        raw = await client.get("health_check:external:stripe")
        payload = json.loads(raw) if raw else {}
        if payload.get("status") != "healthy" or time.time() - int(payload.get("last_check", 0)) > 60 * 60:
            raise RuntimeError("billing_health_stale")
    finally:
        await client.aclose()


def _runtime_runners(role: str) -> dict[str, CheckRunner]:
    health_url = {"core": "http://localhost:8000/v1/health", "upload": "http://app-uploads:8000/health", "preview": "http://preview:8080/health"}[role]
    return {
        "compose.required_services": lambda: _check_required_services(role),
        "http.role_health": lambda: _http_get(health_url),
        "core.database": lambda: _http_get("http://cms:8055/server/health"),
        "core.cache": _check_cache,
        "core.vault": _check_vault,
        "core.worker_queue": _check_worker_queue,
        "core.scheduler_freshness": _check_scheduler_freshness,
        "core.chat_plumbing": _check_chat_plumbing,
        "upload.antivirus": lambda: _check_tcp("clamav", 3310),
        "preview.renderer": lambda: _http_get("http://preview:8080/health"),
        "billing.mode_enabled": _check_billing_mode,
        "billing.stripe_account_read": _check_stripe_account_read,
        "billing.routes_registered": _check_billing_routes,
        "billing.workers_registered": _check_billing_workers,
        "billing.webhook_configured": _check_billing_webhook,
        "billing.health_freshness": _check_billing_freshness,
    }


async def run_verifier(role: str) -> dict[str, object]:
    mode = resolve_runtime_deployment_mode()
    runners = _runtime_runners(role)
    checks = [
        CheckDefinition(check.id, check.timeout_seconds, runners.get(check.id), check.required)
        for check in build_check_inventory(role, mode)
    ]
    started = time.monotonic()
    baseline_ids = {"compose.required_services", "http.role_health"}
    baseline = [check for check in checks if check.id in baseline_ids]
    dependent = [check for check in checks if check.id not in baseline_ids]
    results = await execute_checks(baseline, global_deadline_seconds=GLOBAL_DEADLINE_SECONDS)
    if any(result.required and result.status != "passed" for result in results):
        now = int(time.time())
        results.extend(
            CheckResult(check.id, "skipped", check.required, 0, check.id, now, now, "dependency_failed", "baseline_dependency_failed")
            for check in dependent
        )
    else:
        remaining = max(0.001, GLOBAL_DEADLINE_SECONDS - (time.monotonic() - started))
        results.extend(await execute_checks(dependent, global_deadline_seconds=remaining))
    order = {check.id: index for index, check in enumerate(checks)}
    results.sort(key=lambda result: order[result.id])
    passed = all(result.status == "passed" or not result.required for result in results)
    return {
        "schema_version": 1,
        "role": role,
        "effective_mode": mode.effective_mode,
        "mode_status": mode.status,
        "status": "passed" if passed else "failed",
        "completed_at": int(time.time()),
        "checks": [asdict(result) for result in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=sorted(_ROLE_CHECKS), default="core")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    with redirect_stdout(sys.stderr):
        result = asyncio.run(run_verifier(args.role))
    print(json.dumps(result, separators=(",", ":")) if args.json else json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
