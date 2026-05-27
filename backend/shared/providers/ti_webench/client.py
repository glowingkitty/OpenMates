"""
Pure HTTP client for TI WEBENCH Power Designer.

This integration is reverse-engineered from the public Angular app at
https://webench.ti.com/power-designer/. The endpoints are unauthenticated
today, but they are not an official public API; callers should cache results
and handle provider-side schema or availability changes gracefully.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from backend.shared.providers.ti_webench.models import (
    TIWebenchPowerSearchRequest,
    TIWebenchPowerSolution,
)

logger = logging.getLogger(__name__)

TI_WEBENCH_BASE_URL = "https://webench.ti.com"
POWER_SOLUTIONS_ENDPOINT = "/wb6/restapi/power/solutions"
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_429_RETRIES = 3
DEFAULT_429_RETRY_DELAY_SECONDS = 1.0


def _default_headers() -> Dict[str, str]:
    """Return headers required by the WEBENCH endpoints."""
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": "https://webench.ti.com/power-designer/",
        "User-Agent": "OpenMates Electronics/1.0",
    }


async def _request_with_retry(
    client: httpx.AsyncClient,
    payload: Dict[str, Any],
) -> httpx.Response:
    """POST to WEBENCH with conservative retries for transient throttling."""
    url = f"{TI_WEBENCH_BASE_URL}{POWER_SOLUTIONS_ENDPOINT}"
    for attempt in range(1, MAX_429_RETRIES + 1):
        response = await client.post(url, json=payload, headers=_default_headers())
        if response.status_code != 429:
            response.raise_for_status()
            return response

        if attempt >= MAX_429_RETRIES:
            logger.warning("TI WEBENCH rate limit exhausted after %s attempts", attempt)
            response.raise_for_status()

        retry_after = response.headers.get("Retry-After")
        try:
            wait_seconds = max(float(retry_after), 0.1) if retry_after else DEFAULT_429_RETRY_DELAY_SECONDS
        except ValueError:
            wait_seconds = DEFAULT_429_RETRY_DELAY_SECONDS
        await asyncio.sleep(wait_seconds)

    raise RuntimeError("TI WEBENCH retry loop exited unexpectedly")


async def search_power_solutions(
    request: TIWebenchPowerSearchRequest,
    max_results: int = 10,
    client: Optional[httpx.AsyncClient] = None,
) -> List[TIWebenchPowerSolution]:
    """Search WEBENCH for power converter solutions matching requirements."""
    max_results = max(1, min(50, max_results))
    payload = request.model_dump()

    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)
    try:
        response = await _request_with_retry(http_client, payload)
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("TI WEBENCH returned a non-list solutions response")

        solutions: List[TIWebenchPowerSolution] = []
        for item in data[:max_results]:
            solution = TIWebenchPowerSolution.model_validate(item)
            solution.raw = item
            solutions.append(solution)
        return solutions
    finally:
        if owns_client:
            await http_client.aclose()
