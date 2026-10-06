"""Rejected transient Team names must not enter persistent request error logs."""

import logging
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, Field

from backend.core.api.app.middleware.logging_middleware import LoggingMiddleware


class NameInput(BaseModel):
    name: str = Field(max_length=5)


# contract-test: supporting surface=rest_api assertions=teams.name.transient-policy
@pytest.mark.asyncio
async def test_invalid_team_name_is_not_persisted_in_error_logs(caplog):
    app = FastAPI()
    calls = []
    app.state.metrics_service = SimpleNamespace(
        track_api_request=lambda *args: calls.append(args),
        track_request_duration=lambda *_args: None,
    )
    app.add_middleware(LoggingMiddleware)

    @app.post("/v1/teams/name-approval")
    async def approve(body: NameInput):
        return {"accepted": True}

    @app.post("/ordinary-validation")
    async def ordinary(body: NameInput):
        return {"accepted": True}

    private_name = "Private research team"
    # The middleware logger has propagate=False in the application log config.
    middleware_logger = logging.getLogger(LoggingMiddleware.__module__)
    middleware_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=middleware_logger.name):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                rejected = await client.post("/v1/teams/name-approval", json={"name": private_name})
                assert rejected.status_code == 422
                assert rejected.json()["detail"][0]["input"] == private_name
                assert private_name not in caplog.text
                assert ("POST", "/v1/teams/name-approval", 422) in calls

                ordinary_rejected = await client.post("/ordinary-validation", json={"name": "ordinary input"})
                assert ordinary_rejected.status_code == 422
                assert "ordinary input" in caplog.text
    finally:
        middleware_logger.removeHandler(caplog.handler)
