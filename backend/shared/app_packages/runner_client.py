"""HTTP client for the isolated ``app-packages-runner`` service.

The runner serves HTTP only on a Unix domain socket in the dedicated
``app-packages-runner-socket`` volume; it shares no Docker network with
OpenMates services. Secrets are sent in the request body for the single call
and never logged.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from backend.shared.app_packages.loader import InstalledProvider

logger = logging.getLogger(__name__)

RUNNER_SOCKET_ENV = "OPENMATES_APP_PACKAGES_RUNNER_SOCKET"
DEFAULT_RUNNER_SOCKET = "/run/app-packages-runner/runner.sock"
RUNNER_BASE_URL = "http://app-packages-runner"
DEFAULT_TIMEOUT_SECONDS = 30
HTTP_TIMEOUT_MARGIN_SECONDS = 5
RUNNER_UNAVAILABLE = "RUNNER_UNAVAILABLE"
KNOWN_ERROR_CODES = frozenset({
    "PACKAGE_UNAVAILABLE", "EXECUTION_FAILED", "TIMEOUT", "OUTPUT_TOO_LARGE",
    "INVALID_OUTPUT", "PROVIDER_ERROR", "INVALID_REQUEST", RUNNER_UNAVAILABLE,
})


@dataclass
class RunnerResult:
    ok: bool
    results: List[Any] = field(default_factory=list)
    error_code: Optional[str] = None
    message: Optional[str] = None


def runner_socket_path() -> str:
    return os.getenv(RUNNER_SOCKET_ENV) or DEFAULT_RUNNER_SOCKET


async def run_provider(
    provider: InstalledProvider,
    input_item: Dict[str, Any],
    secrets: Dict[str, str],
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    client: Optional[httpx.AsyncClient] = None,
) -> RunnerResult:
    """Execute one installed provider call and return a typed result."""
    body = {
        "package_id": provider.package_id,
        "version": provider.package_version,
        "provider_id": provider.provider_id,
        # One id may serve several skills of a package; the target picks the contribution.
        "app_id": provider.app_id,
        "skill_id": provider.skill_id,
        "contract": provider.contract,
        "input": input_item,
        "secrets": secrets,
        "timeout_seconds": timeout_seconds,
    }
    url = f"{RUNNER_BASE_URL}/v1/run"
    owned = client is None
    http = client or httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(uds=runner_socket_path()),
        timeout=timeout_seconds + HTTP_TIMEOUT_MARGIN_SECONDS,
    )
    try:
        response = await http.post(url, json=body)
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("[AppPackages] Runner call failed for provider '%s': %s", provider.provider_id, type(exc).__name__)
        return RunnerResult(ok=False, error_code=RUNNER_UNAVAILABLE)
    finally:
        if owned:
            await http.aclose()
    if not isinstance(payload, dict):
        return RunnerResult(ok=False, error_code=RUNNER_UNAVAILABLE)
    if payload.get("ok") is True and isinstance(payload.get("results"), list):
        return RunnerResult(ok=True, results=payload["results"])
    code = payload.get("error") if payload.get("error") in KNOWN_ERROR_CODES else RUNNER_UNAVAILABLE
    message = payload.get("message") if isinstance(payload.get("message"), str) else None
    return RunnerResult(ok=False, error_code=code, message=message[:300] if message else None)
