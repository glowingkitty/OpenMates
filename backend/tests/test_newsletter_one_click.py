"""Exercise the production one-click handler through in-memory HTTP requests.

Directus and recipients are synthetic; no email or live subscription is touched.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import hashlib

import httpx
import pytest
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from backend.core.api.app.utils.newsletter_unsubscribe import (
    MAX_ONE_CLICK_BODY_BYTES,
    ONE_CLICK_PATH,
    build_newsletter_one_click_url,
    newsletter_one_click_headers,
    process_newsletter_one_click,
)

TOKEN = "synthetic_recipient_secret_" + "a" * 20


def make_client(directus):
    app = FastAPI()

    @app.post(ONE_CLICK_PATH + "{token}")
    async def handler(request: Request, token: str):
        return await process_newsletter_one_click(request, token, directus)

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.example.test")


def response(status, data=None):
    return SimpleNamespace(status_code=status, json=lambda: {"data": data or []})


# contract-test: direct surface=rest_api assertions=newsletter.lifecycle.unsubscribe-resubscribe,newsletter.privacy.identity-and-token-boundary
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_credentialless_form_deletes_only_newsletter_and_replays_neutrally():
    directus = SimpleNamespace(base_url="https://directus.invalid", _make_api_request=AsyncMock(side_effect=[
        response(200, [{"id": "synthetic-subscriber"}]), response(204), response(200), response(200),
    ]))
    async with make_client(directus) as client:
        scanned = await client.get(ONE_CLICK_PATH + TOKEN, follow_redirects=False)
        assert scanned.status_code == 405
        assert directus._make_api_request.call_count == 0
        unsubscribed = await client.post(ONE_CLICK_PATH + TOKEN, data={"List-Unsubscribe": "One-Click"})
        replay = await client.post(ONE_CLICK_PATH + TOKEN, files={"List-Unsubscribe": (None, "One-Click")})
        unknown = await client.post(ONE_CLICK_PATH + "b" * 43, data={"List-Unsubscribe": "One-Click"})
    assert unsubscribed.status_code == replay.status_code == unknown.status_code == 200
    assert unsubscribed.json() == replay.json() == unknown.json()
    assert "location" not in unsubscribed.headers
    calls = directus._make_api_request.call_args_list
    assert calls[0].kwargs["params"] == {"filter[unsubscribe_token][_eq]": TOKEN, "fields": "id", "limit": 1}
    assert calls[1].args == ("DELETE", "https://directus.invalid/items/newsletter_subscribers/synthetic-subscriber")
    assert all("ignored_emails" not in str(call) and "/users" not in str(call) for call in calls)


# contract-test: direct surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary
@pytest.mark.asyncio
@pytest.mark.parametrize("body,content_type,status", [
    (b"List-Unsubscribe=wrong", "application/x-www-form-urlencoded", 400),
    (b"List-Unsubscribe=One-Click&List-Unsubscribe=One-Click", "application/x-www-form-urlencoded", 400),
    (b'{"List-Unsubscribe":"One-Click"}', "application/json", 400),
    (b"List-Unsubscribe=One-Click", "text/plain", 400),
    (b"bad", "multipart/form-data; boundary=missing", 400),
    (b"x" * (MAX_ONE_CLICK_BODY_BYTES + 1), "application/x-www-form-urlencoded", 413),
])
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_invalid_forms_never_query_or_mutate(body, content_type, status):
    directus = SimpleNamespace(base_url="https://directus.invalid", _make_api_request=AsyncMock())
    async with make_client(directus) as client:
        result = await client.post(ONE_CLICK_PATH + TOKEN, content=body, headers={"Content-Type": content_type})
    assert result.status_code == status
    directus._make_api_request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [response(500), response(200, [{}])])
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_upstream_failure_can_be_retried_without_redirect(result):
    directus = SimpleNamespace(base_url="https://directus.invalid", _make_api_request=AsyncMock(return_value=result))
    async with make_client(directus) as client:
        failed = await client.post(ONE_CLICK_PATH + TOKEN, data={"List-Unsubscribe": "One-Click"})
    assert failed.status_code == 503
    assert "location" not in failed.headers
    assert TOKEN not in failed.text


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_malformed_token_never_reaches_directus():
    directus = SimpleNamespace(base_url="https://directus.invalid", _make_api_request=AsyncMock())
    async with make_client(directus) as client:
        invalid = await client.post(ONE_CLICK_PATH + "short", data={"List-Unsubscribe": "One-Click"})
    assert invalid.status_code == 400
    directus._make_api_request.assert_not_called()


# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
def test_headers_advertise_only_trusted_https_post_endpoint(monkeypatch):
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.delenv("NEWSLETTER_PUBLIC_API_ORIGIN", raising=False)
    url = build_newsletter_one_click_url(TOKEN)
    assert url == "https://api.dev.openmates.org" + ONE_CLICK_PATH + TOKEN
    assert newsletter_one_click_headers(url) == {
        "List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    for invalid in (
        "https://app.dev.openmates.org/#settings/newsletter/unsubscribe/" + TOKEN,
        "https://app.dev.openmates.org/#settings/email/block/test@example.invalid",
        url.replace("https:", "http:"), url + "?token=extra", url + "#fragment",
        url.replace("api.dev.openmates.org", "untrusted.invalid"), None,
    ):
        assert newsletter_one_click_headers(invalid) == {}
    monkeypatch.setenv("NEWSLETTER_PUBLIC_API_ORIGIN", "http://api.example.test")
    with pytest.raises(ValueError):
        build_newsletter_one_click_url(TOKEN)


# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
def test_recipient_token_urls_are_redacted_in_logs():
    from backend.core.api.app.utils.log_filters import SensitiveDataFilter, redact_newsletter_token_urls

    for path in (ONE_CLICK_PATH, "/v1/newsletter/unsubscribe/", "/v1/newsletter/confirm/", "/#settings/newsletter/unsubscribe/"):
        value = "https://api.example.test" + path + TOKEN
        assert TOKEN not in redact_newsletter_token_urls(value)
        assert TOKEN not in SensitiveDataFilter()._redact_sensitive_data(value)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_logging_metrics_and_failure_headers_hide_recipient_token(caplog):
    from backend.core.api.app.middleware import logging_middleware

    LoggingMiddleware = logging_middleware.LoggingMiddleware

    metrics = SimpleNamespace(track_api_request=AsyncMock(), track_request_duration=AsyncMock())
    # Metrics methods are synchronous in the real middleware.
    paths = []
    metrics.track_api_request = lambda _method, path, _status: paths.append(path)
    metrics.track_request_duration = lambda _method, path, _duration: paths.append(path)
    app = FastAPI()
    app.state.metrics_service = metrics

    @app.post(ONE_CLICK_PATH + "{token}")
    async def fail():
        return JSONResponse({"detail": "Invalid one-click unsubscribe form"}, status_code=400)

    app.add_middleware(LoggingMiddleware)
    # API/task bootstrap can replace the root handlers during suite imports.
    # Capture this production logger explicitly instead of relying on propagation.
    already_attached = caplog.handler in logging_middleware.logger.handlers
    if not already_attached:
        logging_middleware.logger.addHandler(caplog.handler)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.example.test") as client:
            await client.post(ONE_CLICK_PATH + TOKEN, headers={"Referer": "https://api.example.test" + ONE_CLICK_PATH + TOKEN})
    finally:
        if not already_attached:
            logging_middleware.logger.removeHandler(caplog.handler)
    assert paths and all(TOKEN not in path for path in paths)
    records = [record for record in caplog.records if hasattr(record, "request_headers_subset")]
    assert records
    assert all(TOKEN not in str(record.request_headers_subset) and TOKEN not in record.getMessage() for record in records)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_shared_mailbox_ip_allows_distinct_tokens_and_bounds_replay():
    pytest.importorskip("slowapi")
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from backend.core.api.app.routes import newsletter
    from backend.core.api.app.utils.newsletter_unsubscribe import newsletter_one_click_rate_key

    rows = {f"synthetic_recipient_{index:024d}": f"synthetic-subscriber-{index}" for index in range(7)}
    original_tokens = list(rows)

    async def api_request(method, url, **kwargs):
        if method == "GET":
            token = kwargs["params"]["filter[unsubscribe_token][_eq]"]
            row = rows.get(token)
            return response(200, [{"id": row}] if row else [])
        if method == "DELETE":
            row_id = url.rsplit("/", 1)[-1]
            for token, existing_id in list(rows.items()):
                if existing_id == row_id:
                    del rows[token]
            return response(204)
        raise AssertionError("One-click must only access newsletter subscriber state")

    directus = SimpleNamespace(base_url="https://directus.invalid", _make_api_request=AsyncMock(side_effect=api_request))
    app = FastAPI()
    app.state.limiter = newsletter.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.dependency_overrides[newsletter.get_directus_service] = lambda: directus
    app.include_router(newsletter.router)
    newsletter.limiter.reset()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("198.51.100.5", 12345)),
                                     base_url="https://api.example.test") as client:
            for token in original_tokens:
                result = await client.post(ONE_CLICK_PATH + token, data={"List-Unsubscribe": "One-Click"})
                assert result.status_code == 200
            assert rows == {}
            # The first recipient request already used one of its five slots.
            for _ in range(4):
                replay = await client.post(ONE_CLICK_PATH + original_tokens[0], data={"List-Unsubscribe": "One-Click"})
                assert replay.status_code == 200
            limited = await client.post(ONE_CLICK_PATH + original_tokens[0], data={"List-Unsubscribe": "One-Click"})
            assert limited.status_code == 429
            storage_keys = list(newsletter.limiter._storage.storage)
            assert storage_keys and all(token not in key for key in storage_keys for token in original_tokens)
            # The fixed IP scope must aggregate requests across token URLs.
            # Eleven earlier accepted requests used its first eleven slots.
            extra_accepted = 0
            for index in range(300):
                token = f"synthetic_unknown_{index:024d}"
                result = await client.post(ONE_CLICK_PATH + token, data={"List-Unsubscribe": "One-Click"})
                if result.status_code == 429:
                    break
                assert result.status_code == 200
                extra_accepted += 1
            assert extra_accepted == 289
            assert result.status_code == 429
        request = Request({"type": "http", "path_params": {"token": original_tokens[0]}})
        rate_key = newsletter_one_click_rate_key(request)
        assert original_tokens[0] not in rate_key
        assert rate_key == "newsletter-one-click:" + hashlib.sha256(original_tokens[0].encode()).hexdigest()
    finally:
        newsletter.limiter.reset()
