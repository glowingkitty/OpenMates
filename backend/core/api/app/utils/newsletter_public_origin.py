"""Exact-origin access for the public website newsletter flow.

The standalone website needs to submit a credentialless form to the API.
Other API routes retain the normal first-party CORS and Origin policy.
The confirmation destination comes from server configuration, never a request.
"""

import os
from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

def get_newsletter_website_origin() -> str:
    environment = os.getenv("SERVER_ENVIRONMENT", "development").lower()
    default = "https://landing.dev.openmates.org" if environment in ("development", "dev", "test") else "https://openmates.org"
    configured = os.getenv("NEWSLETTER_PUBLIC_WEBSITE_ORIGIN", default).rstrip("/")
    parsed = urlsplit(configured)
    if (
        parsed.scheme not in ("https", "http")
        or (parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1"))
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or configured != f"{parsed.scheme}://{parsed.netloc}"
    ):
        raise ValueError("NEWSLETTER_PUBLIC_WEBSITE_ORIGIN must be an exact HTTPS origin")
    return configured


async def verify_newsletter_subscribe_origin(request: Request) -> bool:
    if request.headers.get("origin") == get_newsletter_website_origin():
        return True
    from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin
    return await verify_allowed_origin(request)


class PublicNewsletterCORSMiddleware:
    """Apply credentialless CORS only to public subscribe and confirm requests."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self.website_origin = get_newsletter_website_origin()
        self.website_cors = CORSMiddleware(
            app,
            allow_origins=[self.website_origin],
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
            allow_credentials=False,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "")
        public_route = (
            path == "/v1/newsletter/subscribe" and method in ("POST", "OPTIONS")
        ) or (
            path.startswith("/v1/newsletter/confirm/") and method in ("GET", "OPTIONS")
        )
        origin = next((value.decode("latin-1") for key, value in scope.get("headers", []) if key == b"origin"), None)
        handler = self.website_cors if public_route and origin == self.website_origin else self.app
        if handler is self.app:
            await handler(scope, receive, send)
            return

        async def send_credentialless(message: dict) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    (key, value) for key, value in message.get("headers", [])
                    if key.lower() != b"access-control-allow-credentials"
                ]
            await send(message)

        await handler(scope, receive, send_credentialless)
