"""Public newsletter CORS boundary tests.

These use an in-memory ASGI app; no subscriber record or email is created.
The website is allowed to call subscribe and confirm without credentials.
Unrelated authenticated routes retain the original first-party CORS policy.
"""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from backend.core.api.app.utils.newsletter_public_origin import (
    PublicNewsletterCORSMiddleware,
    get_newsletter_website_origin,
)


WEBSITE = "https://landing.dev.openmates.org"
APP = "https://app.dev.openmates.org"


# contract-test: direct surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.surface.standalone-confirmation
def test_configured_website_must_be_an_exact_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWSLETTER_PUBLIC_WEBSITE_ORIGIN", WEBSITE)
    assert get_newsletter_website_origin() == WEBSITE
    for invalid in ("https://landing.dev.openmates.org/path", "https://other.example@landing.dev.openmates.org", "http://landing.dev.openmates.org"):
        monkeypatch.setenv("NEWSLETTER_PUBLIC_WEBSITE_ORIGIN", invalid)
        with pytest.raises(ValueError):
            get_newsletter_website_origin()


# contract-test: direct surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.surface.standalone-confirmation
@pytest.mark.asyncio
async def test_website_cors_is_credentialless_and_route_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWSLETTER_PUBLIC_WEBSITE_ORIGIN", WEBSITE)

    async def ok(_request):
        return JSONResponse({"success": True})

    app = Starlette(routes=[
        Route("/v1/newsletter/subscribe", ok, methods=["POST"]),
        Route("/v1/newsletter/confirm/{token}", ok, methods=["GET"]),
        Route("/v1/auth/session", ok, methods=["GET"]),
    ])
    global_cors = CORSMiddleware(app, allow_origins=[APP], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    scoped_cors = PublicNewsletterCORSMiddleware(global_cors)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=scoped_cors), base_url="https://api.dev.openmates.org") as client:
        preflight = await client.options("/v1/newsletter/subscribe", headers={
            "Origin": WEBSITE,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == WEBSITE
        assert "access-control-allow-credentials" not in preflight.headers

        subscribed = await client.post("/v1/newsletter/subscribe", headers={"Origin": WEBSITE}, json={})
        confirmed = await client.get("/v1/newsletter/confirm/token", headers={"Origin": WEBSITE})
        for response in (subscribed, confirmed):
            assert response.headers["access-control-allow-origin"] == WEBSITE
            assert "access-control-allow-credentials" not in response.headers

        unrelated = await client.get("/v1/auth/session", headers={"Origin": WEBSITE})
        assert "access-control-allow-origin" not in unrelated.headers
        app_route = await client.get("/v1/auth/session", headers={"Origin": APP})
        assert app_route.headers["access-control-allow-origin"] == APP
