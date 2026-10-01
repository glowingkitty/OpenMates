"""REST regression coverage for authenticated, no-spend payment route probes."""

import httpx
import pytest
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.core.api.app.routes.internal_health import router
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils import internal_auth


# contract-test: direct surface=rest_api assertions=operational-monitoring.billing.no-spend-readiness
@pytest.mark.asyncio
async def test_payment_route_probe_requires_service_auth_and_checks_actual_methods(monkeypatch):
    monkeypatch.setattr(internal_auth, "INTERNAL_API_SHARED_TOKEN", "test-service-token")
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router)

    async def placeholder():
        return {}

    app.add_api_route("/v1/payments/webhook", placeholder, methods=["POST"])
    app.add_api_route("/v1/payments/subscription", placeholder, methods=["GET"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/internal/health/payments")).status_code == 401
        assert (await client.get("/internal/health/payments", headers={"X-Internal-Service-Token": "wrong"})).status_code == 403
        headers = {"X-Internal-Service-Token": "test-service-token"}
        response = await client.get("/internal/health/payments", headers=headers)
        assert response.status_code == 200
        assert response.json() == {"routes_registered": True}
        assert (await client.get("/v1/payments/webhook")).status_code == 405
        assert (await client.post("/v1/payments/webhook")).status_code == 200
        app.router.routes = [route for route in app.routes if getattr(route, "path", None) != "/v1/payments/webhook"]
        app.add_api_route("/v1/payments/webhook", placeholder, methods=["GET"])
        assert (await client.get("/internal/health/payments", headers=headers)).json() == {"routes_registered": False}


# contract-test: direct surface=rest_api assertions=operational-monitoring.billing.no-spend-readiness
@pytest.mark.asyncio
async def test_payment_route_probe_fails_closed_without_server_token(monkeypatch):
    monkeypatch.setattr(internal_auth, "INTERNAL_API_SHARED_TOKEN", None)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/internal/health/payments")).status_code == 500


# contract-test: direct surface=rest_api assertions=operational-monitoring.billing.no-spend-readiness
@pytest.mark.asyncio
async def test_payment_route_probe_rate_limit(monkeypatch):
    monkeypatch.setattr(internal_auth, "INTERNAL_API_SHARED_TOKEN", "test-service-token")
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(router)
    transport = httpx.ASGITransport(app=app, client=("192.0.2.42", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(60):
            response = await client.get("/internal/health/payments", headers={"X-Internal-Service-Token": "test-service-token"})
            assert response.status_code == 200
        response = await client.get("/internal/health/payments", headers={"X-Internal-Service-Token": "test-service-token"})
        assert response.status_code == 429
