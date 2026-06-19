# backend/core/api/app/routes/application_preview_gateway.py
#
# Authorization helpers for the generated-application preview gateway.
# Preview traffic arrives on a separate user-content origin without OpenMates
# auth cookies, so gateway requests must prove possession of a short-lived path
# token scoped to a single viewer-owned sandbox session.

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from backend.core.api.app.routes.application_preview import (
    application_preview_host_key,
    application_preview_session_key,
    get_cache_service,
    hash_preview_gateway_token,
)


router = APIRouter(tags=["Application Preview Gateway"])
logger = logging.getLogger(__name__)

TERMINAL_PREVIEW_STATUSES = {"stopped", "failed", "timeout", "cancelled"}
LEGACY_PREVIEW_GATEWAY_TOKEN_PATTERN = re.compile(r"(/p/[^/]+)/([^/]+)(?=/|$)")
HOST_PREVIEW_GATEWAY_TOKEN_PATTERN = re.compile(r"(/t)/([^/]+)(?=/|$)")
BLOCKED_UPSTREAM_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "set-cookie",
    "transfer-encoding",
    "x-e2b-token",
}
FORWARDED_REQUEST_HEADERS = {"accept", "content-type"}
REWRITABLE_UPSTREAM_CONTENT_TYPES = {
    "text/html",
    "application/javascript",
    "text/javascript",
    "application/x-javascript",
    "text/css",
}
HTML_ROOT_PATH_PATTERN = re.compile(r"(?P<prefix>\b(?:src|href|action)\s*=\s*[\"'])/(?!/|p/)(?P<path>[^\"']+)")
QUOTED_ROOT_PATH_PATTERN = re.compile(r"(?P<prefix>[\"'])/(?!/|p/)(?P<path>[^\"']+)")
CSS_URL_ROOT_PATH_PATTERN = re.compile(r"(?P<prefix>url\(\s*[\"']?)/(?!/|p/)(?P<path>[^)\"'\s]+)")
UPSTREAM_PATH_SEGMENT_SAFE_CHARS = "@"
VITE_HMR_CLIENT_SCRIPT_PATTERN = re.compile(
    r"\s*<script\b(?=[^>]*\bsrc=[\"']/@vite/client[\"'])[^>]*>\s*</script>",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GatewayUpstreamResponse:
    status_code: int
    body: bytes
    headers: dict[str, str]


async def validate_preview_gateway_access(
    cache_service: Any,
    session_id: str,
    preview_token: str,
    *,
    now: float,
    preview_host: str | None = None,
) -> dict[str, Any]:
    client = await cache_service.client
    raw = await client.get(application_preview_session_key(session_id))
    if not raw:
        raise HTTPException(status_code=403, detail="Invalid or expired preview session")

    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    expected_hash = data.get("preview_token_hash")
    if not isinstance(expected_hash, str) or expected_hash != hash_preview_gateway_token(preview_token):
        raise HTTPException(status_code=403, detail="Invalid or expired preview session")
    if data.get("status") in TERMINAL_PREVIEW_STATUSES:
        raise HTTPException(status_code=403, detail="Preview session is no longer active")
    if now > float(data.get("idle_deadline") or 0) or now > float(data.get("hard_deadline") or 0):
        raise HTTPException(status_code=403, detail="Preview session is expired")
    if preview_host is not None and data.get("preview_host") != normalize_preview_host_header(preview_host):
        raise HTTPException(status_code=403, detail="Invalid or expired preview session")

    return data


async def validate_preview_gateway_host_access(
    cache_service: Any,
    preview_host: str,
    preview_token: str,
    *,
    now: float,
) -> dict[str, Any]:
    normalized_host = normalize_preview_host_header(preview_host)
    client = await cache_service.client
    raw_session_id = await client.get(application_preview_host_key(normalized_host))
    if not raw_session_id:
        raise HTTPException(status_code=403, detail="Invalid or expired preview session")

    session_id = raw_session_id.decode("utf-8") if isinstance(raw_session_id, bytes) else str(raw_session_id)
    return await validate_preview_gateway_access(
        cache_service,
        session_id,
        preview_token,
        now=now,
        preview_host=normalized_host,
    )


def normalize_preview_host_header(value: str) -> str:
    host = (value or "").split(",", 1)[0].strip().lower().rstrip(".")
    if not host or "/" in host or "@" in host:
        raise HTTPException(status_code=403, detail="Invalid or expired preview session")
    return host


def redact_preview_gateway_tokens(value: str) -> str:
    redacted = LEGACY_PREVIEW_GATEWAY_TOKEN_PATTERN.sub(r"\1/<REDACTED_PREVIEW_TOKEN>", value)
    return HOST_PREVIEW_GATEWAY_TOKEN_PATTERN.sub(r"\1/<REDACTED_PREVIEW_TOKEN>", redacted)


def preview_gateway_security_headers() -> dict[str, str]:
    return {
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex, nofollow",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), clipboard-read=(), clipboard-write=()",
    }


async def build_preview_gateway_response(
    cache_service: Any,
    session_id: str,
    preview_token: str,
    path: str,
    *,
    now: float,
    method: str = "GET",
    query_string: str = "",
    body: bytes | None = None,
    request_headers: dict[str, str] | None = None,
    preview_host: str | None = None,
    upstream_fetch: Any | None = None,
) -> Response:
    session = await validate_preview_gateway_access(cache_service, session_id, preview_token, now=now, preview_host=preview_host)
    upstream_base_url = _select_upstream_base_url(session, path)
    if not isinstance(upstream_base_url, str) or not upstream_base_url.strip():
        return JSONResponse(
            status_code=202,
            content={
                "status": "sandbox_starting",
                "session_id": session_id,
                "path": path,
            },
            headers=preview_gateway_security_headers(),
        )

    fetch = upstream_fetch or fetch_preview_upstream
    upstream_url = _upstream_url(upstream_base_url, path, query_string=query_string)
    upstream = await fetch(
        upstream_url,
        method,
        body=body,
        headers=_filtered_request_headers(request_headers or {}),
    )
    if upstream.status_code >= 500:
        logger.warning(
            "Application preview upstream returned %s for session %s path %s upstream %s",
            upstream.status_code,
            session_id,
            path or "/",
            upstream_url,
        )
    response_headers = _filtered_upstream_headers(upstream.headers)
    return Response(
        content=_rewrite_root_relative_preview_references(
            upstream.body,
            response_headers,
            session_id=session_id,
            preview_token=preview_token,
            preview_host=preview_host,
        ),
        status_code=upstream.status_code,
        headers={**response_headers, **preview_gateway_security_headers()},
    )


async def fetch_preview_upstream(
    url: str,
    method: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> GatewayUpstreamResponse:
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.request(method, url, content=body, headers=headers)
    return GatewayUpstreamResponse(
        status_code=response.status_code,
        body=response.content,
        headers={key.lower(): value for key, value in response.headers.items()},
    )


def _select_upstream_base_url(session: dict[str, Any], path: str) -> str | None:
    upstreams = session.get("upstream_base_urls") if isinstance(session.get("upstream_base_urls"), dict) else {}
    normalized_path = path.strip("/")
    if normalized_path == "api" or normalized_path.startswith("api/"):
        api_upstream = upstreams.get("api") or upstreams.get("backend")
        if isinstance(api_upstream, str) and api_upstream.strip():
            return api_upstream

    frontend_upstream = upstreams.get("frontend") if isinstance(upstreams, dict) else None
    if isinstance(frontend_upstream, str) and frontend_upstream.strip():
        return frontend_upstream
    value = session.get("upstream_base_url")
    return value if isinstance(value, str) else None


def _upstream_url(upstream_base_url: str, path: str, *, query_string: str = "") -> str:
    base = upstream_base_url.rstrip("/")
    normalized_path = "/".join(quote(part, safe=UPSTREAM_PATH_SEGMENT_SAFE_CHARS) for part in path.strip("/").split("/") if part)
    upstream_url = f"{base}/{normalized_path}" if normalized_path else f"{base}/"
    return f"{upstream_url}?{query_string}" if query_string else upstream_url


def _filtered_upstream_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in BLOCKED_UPSTREAM_HEADERS
    }


def _filtered_request_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() in FORWARDED_REQUEST_HEADERS
    }


def _rewrite_root_relative_preview_references(
    body: bytes,
    headers: dict[str, str],
    *,
    session_id: str,
    preview_token: str,
    preview_host: str | None = None,
) -> bytes:
    content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in REWRITABLE_UPSTREAM_CONTENT_TYPES:
        return body

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body

    signed_prefix = f"/t/{preview_token}" if preview_host else f"/p/{session_id}/{preview_token}"

    def rewrite_match(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{signed_prefix}/{match.group('path')}"

    if content_type == "text/html":
        text = VITE_HMR_CLIENT_SCRIPT_PATTERN.sub("", text)
        text = HTML_ROOT_PATH_PATTERN.sub(rewrite_match, text)
    elif content_type == "text/css":
        text = CSS_URL_ROOT_PATH_PATTERN.sub(rewrite_match, text)
    else:
        text = QUOTED_ROOT_PATH_PATTERN.sub(rewrite_match, text)
    return text.encode("utf-8")


@router.api_route("/t/{preview_token}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def application_preview_host_gateway(
    request: Request,
    preview_token: str,
    path: str = "",
    cache_service: Any = Depends(get_cache_service),
) -> Response:
    session = await validate_preview_gateway_host_access(
        cache_service,
        request.headers.get("host", ""),
        preview_token,
        now=time.time(),
    )
    return await build_preview_gateway_response(
        cache_service,
        str(session.get("session_id") or ""),
        preview_token,
        path,
        now=time.time(),
        method=request.method,
        query_string=request.url.query,
        body=await request.body(),
        request_headers=dict(request.headers),
        preview_host=request.headers.get("host", ""),
    )


@router.api_route("/p/{session_id}/{preview_token}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def application_preview_gateway(
    request: Request,
    session_id: str,
    preview_token: str,
    path: str = "",
    cache_service: Any = Depends(get_cache_service),
) -> Response:
    return await build_preview_gateway_response(
        cache_service,
        session_id,
        preview_token,
        path,
        now=time.time(),
        method=request.method,
        query_string=request.url.query,
        body=await request.body(),
        request_headers=dict(request.headers),
    )
