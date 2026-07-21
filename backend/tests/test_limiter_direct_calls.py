# backend/tests/test_limiter_direct_calls.py
#
# Regression tests for the shared SlowAPI limiter wrapper used by FastAPI
# route modules. Route-level unit tests call decorated handlers directly with
# lightweight fake request objects; those calls must exercise route logic
# without requiring a real Starlette HTTP request.
#
# HTTP requests still pass through SlowAPI when the bound request argument is a
# real starlette.requests.Request instance.

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.core.api.app.services.limiter import OpenMatesLimiter


@pytest.mark.anyio
async def test_limiter_allows_direct_async_route_calls_with_fake_request() -> None:
    limiter = OpenMatesLimiter(key_func=lambda _request: "test-client")

    @limiter.limit("1/minute")
    async def route(request, value: str) -> dict[str, str]:
        return {"value": value, "state": request.app.state.marker}

    response = await route(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(marker="direct"))), "ok")

    assert response == {"value": "ok", "state": "direct"}
