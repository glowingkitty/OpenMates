"""Publish guard-verified rotation cookies on the actual HTTP response.

Manual model-returning routes and explicit/streaming Response objects must all
carry the same credential selected by the authentication guard. WebSockets do
not rotate here, and an explicit route cookie (including logout deletion) wins.
"""
from __future__ import annotations

import hashlib

from fastapi import Request, Response

_COOKIE_STATE = "verified_rotated_refresh_cookie"
_EXTENDED_TTL = 30 * 86400


def set_refresh_cookie(response: Response, request: Request | None, token: str, ttl: int) -> None:
    cookie_params = {
        "key": "auth_refresh_token", "value": token, "httponly": True,
        "secure": True, "samesite": "lax", "max_age": ttl, "path": "/",
    }
    if request is not None:
        from backend.core.api.app.routes.auth_routes.auth_utils import get_cookie_domain
        domain = get_cookie_domain(request)
        if domain:
            cookie_params["domain"] = domain
    response.set_cookie(**cookie_params)


async def queue_rotated_session_cookie(request: Request | None, cache, token: str,
                                       user_data: dict, *, ttl: int | None = None) -> None:
    """Call only after the guard has authenticated this request's credential."""
    if request is None or token == request.cookies.get("auth_refresh_token"):
        return
    if ttl is None:
        user_id = user_data.get("user_id") or user_data.get("id")
        metadata = await cache.get(f"user_tokens:{user_id}") or {}
        current = metadata.get(hashlib.sha256(token.encode()).hexdigest()) if isinstance(metadata, dict) else None
        stay_logged_in = bool(current.get("stay_logged_in")) if isinstance(current, dict) else bool(user_data.get("stay_logged_in"))
        ttl = _EXTENDED_TTL if stay_logged_in else cache.SESSION_TTL
    response = Response()
    set_refresh_cookie(response, request, token, ttl)
    request.state.verified_rotated_refresh_cookie = next(
        header for header in response.raw_headers if header[0] == b"set-cookie"
    )


class SessionCookiePublicationMiddleware:
    """Intercept response headers without buffering or consuming response bodies."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def publish(message):
            if message["type"] == "http.response.start":
                cookie = scope.get("state", {}).get(_COOKIE_STATE)
                headers = message.get("headers", [])
                explicit = any(
                    name.lower() == b"set-cookie"
                    and value.split(b"=", 1)[0].strip().lower() == b"auth_refresh_token"
                    for name, value in headers
                )
                if cookie and not explicit:
                    message = {**message, "headers": [*headers, cookie]}
            await send(message)

        await self.app(scope, receive, publish)
