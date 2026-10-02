"""Actual outgoing HTTP cookies for manual auth and explicit/SSE responses."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import asyncio
import sys

import httpx
import pytest
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse

from backend.core.api.app.middleware.logging_middleware import LoggingMiddleware
from backend.core.api.app.middleware.session_cookie_publication import SessionCookiePublicationMiddleware
from backend.core.api.app.services import session_security_state as state
from backend.core.api.app.utils import session_refresh as refresh
from backend.tests.test_session_refresh_coordination import (
    FakeCache, FakeDirectus, _load_auth_guards, _load_session_management,
    publish, session_key,
)
from backend.tests.test_auth_2fa_setup_assurance import _load_route as _load_setup_route


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement,auth.secrets.lifecycle
@pytest.mark.parametrize("surface", ["provider", "stream", "explicit", "logout", "forbidden", "revoked", "device_mismatch"])
@pytest.mark.parametrize("stay_logged_in", [False, True])
def test_actual_http_response_publishes_only_guard_approved_successor(monkeypatch, surface, stay_logged_in):
    common, dependencies = _load_auth_guards(monkeypatch)
    setup = _load_setup_route(monkeypatch)
    setup.verify_authenticated_user = common.verify_authenticated_user
    _load_session_management(monkeypatch)  # Isolate only heavyweight runtime service imports.
    monkeypatch.setattr(sys.modules["backend.core.api.app.routes.auth_routes.auth_utils"], "get_cookie_domain", lambda _request: ".openmates.test")
    path = Path(__file__).parents[1] / "core/api/app/routes/notifications.py"
    spec = spec_from_file_location("cookie_notification_route_under_test", path)
    notifications = module_from_spec(spec)
    spec.loader.exec_module(notifications)
    monkeypatch.setattr(common, "generate_device_fingerprint_hash", lambda *_args: ("known-device", None, None, None, None, None, None, None))

    async def run():
        clock = [1000.0]
        monkeypatch.setattr(refresh.time, "time", lambda: clock[0])
        cache = FakeCache()
        directus = FakeDirectus(refresh_token=AsyncMock(return_value=(True, {"cookies": {"directus_refresh_token": "new-secret"}}, "OK")))
        directus.get_user_device_hashes = AsyncMock(return_value=[] if surface == "device_mismatch" else ["known-device"])
        directus.get_user_fields_direct = AsyncMock(return_value={"signup_completed": False, "last_opened": "/signup/one-time-codes"})
        directus.update_user = AsyncMock(return_value=True)
        cache.update_user = AsyncMock(return_value=True)
        encryption = SimpleNamespace(encrypt_with_user_key=AsyncMock(return_value=("opaque-provider-fixture", None)))
        await refresh.refresh_session_token(cache, directus, "old-secret")
        await publish(cache, "old-secret", "new-secret")
        profile = cache.values[session_key("new-secret")]
        profile.update(username="example", vault_key_id="fixture-vault", stay_logged_in=stay_logged_in, last_opened="/signup/one-time-codes")
        cache.values["user_tokens:user-1"] = {state.token_hash("new-secret"): {"stay_logged_in": stay_logged_in}}
        if surface == "revoked":
            directus.rows[state.token_hash("new-secret")]["revoked"] = True
        pubsub = SimpleNamespace(
            subscribe=AsyncMock(), unsubscribe=AsyncMock(), close=AsyncMock(),
            get_message=AsyncMock(side_effect=RuntimeError("bounded test stream complete")),
        )
        cache.redis.pubsub = lambda: pubsub
        app = FastAPI()
        app.state.metrics_service = MagicMock()
        app.state.cache_service = cache
        app.add_middleware(LoggingMiddleware)
        app.add_middleware(SessionCookiePublicationMiddleware)

        @app.post("/v1/auth/2fa/setup/provider")
        async def provider(request: Request):
            return await setup.setup_2fa_provider(
                request, setup.Setup2FAProviderRequest(provider="fixture-provider"),
                directus_service=directus, cache_service=cache, encryption_service=encryption,
            )

        async def guard(request, temporary):
            return await dependencies.get_current_user(
                directus_service=directus, cache_service=cache,
                refresh_token=request.cookies.get("auth_refresh_token"), response=temporary, request=request,
            )

        @app.get("/v1/notifications/stream")
        async def stream(request: Request, response: Response):
            user = await guard(request, response)
            return await notifications.stream_notifications(request, current_user=user, cache_service=cache)

        @app.get("/explicit")
        async def explicit(request: Request, response: Response):
            await guard(request, response)
            # This own response discards FastAPI's temporary dependency headers.
            return JSONResponse({"success": True})

        @app.get("/forbidden")
        async def forbidden(request: Request, response: Response):
            await guard(request, response)
            raise HTTPException(403, "Fixture action forbidden")

        @app.post("/logout")
        async def logout(request: Request, response: Response):
            await guard(request, response)
            outgoing = JSONResponse({"success": True})
            outgoing.delete_cookie("auth_refresh_token", path="/", domain=".openmates.test", httponly=True, secure=True, samesite="lax")
            outgoing.set_cookie("auth_other", "fixture", httponly=True, secure=True)
            return outgoing

        @app.get("/next")
        async def next_request(request: Request, response: Response):
            user = await guard(request, response)
            return {"user_id": user.id}

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.openmates.test") as client:
            client.cookies.set("auth_refresh_token", "old-secret", domain=".openmates.test", path="/")
            if surface in ("provider", "device_mismatch"):
                result = await client.post("/v1/auth/2fa/setup/provider")
            elif surface == "logout":
                result = await client.post("/logout")
            elif surface == "stream":
                result = await client.get("/v1/notifications/stream")
                assert result.headers["content-type"].startswith("text/event-stream")
                assert result.text.startswith(": connected")
            elif surface == "revoked":
                result = await client.get("/explicit")
            else:
                result = await client.get("/" + surface)
            cookies = result.headers.get_list("set-cookie")
            refresh_cookies = [cookie for cookie in cookies if cookie.startswith("auth_refresh_token=")]
            if surface in ("revoked", "device_mismatch"):
                assert result.status_code == (401 if surface == "revoked" else 200)
                assert not refresh_cookies
                if surface == "device_mismatch":
                    assert result.json()["success"] is False
            elif surface == "logout":
                assert len(cookies) == 2  # Logging must preserve repeated Set-Cookie.
                assert len(refresh_cookies) == 1 and "Max-Age=0" in refresh_cookies[0]
                assert "new-secret" not in refresh_cookies[0]
            else:
                assert result.status_code == (403 if surface == "forbidden" else 200)
                assert len(refresh_cookies) == 1
                cookie = refresh_cookies[0]
                assert "auth_refresh_token=new-secret" in cookie
                assert "Domain=.openmates.test" in cookie and "Path=/" in cookie
                assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
                assert f"Max-Age={2592000 if stay_logged_in else cache.SESSION_TTL}" in cookie
                assert "new-secret" not in result.text
                clock[0] += refresh.ROTATION_GRACE_SECONDS + 1
                # The outgoing cookie, automatically stored by the HTTP client,
                # now authenticates even after the old credential's grace ends.
                following = await client.get("/next")
                assert following.status_code == 200 and following.json()["user_id"] == "user-1"
            assert directus.refresh_token.await_count == 1

    asyncio.run(run())
