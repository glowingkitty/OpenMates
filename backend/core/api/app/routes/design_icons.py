# backend/core/api/app/routes/design_icons.py
#
# Public Design icon SVG route.
# Clients fetch sanitized Iconify SVGs from OpenMates rather than calling Iconify
# directly or using the preview server. The route accepts only validated Iconify
# identifiers, sanitizes SVG text, rate-limits requests, and caches safe SVGs.

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response as FastAPIResponse

from backend.shared.providers.iconify.client import (
    IconifyClient,
    IconifyProviderError,
    is_valid_iconify_name,
    is_valid_iconify_prefix,
    sanitize_iconify_svg,
)

try:
    from backend.core.api.app.services.limiter import limiter
except ModuleNotFoundError:
    class _NoopLimiter:
        def limit(self, _limit_value: str):
            def decorator(func: Any) -> Any:
                return func

            return decorator

    limiter = _NoopLimiter()


router = APIRouter(prefix="/v1/apps/design/icons", tags=["Design Icons"])
SVG_CACHE_CONTROL = "public, max-age=86400"


def get_iconify_client() -> IconifyClient:
    return IconifyClient()


def _provider_error_status(code: str) -> int:
    if code == "icon_not_found":
        return 404
    if code == "unsafe_svg":
        return 502
    if code == "provider_unavailable":
        return 503
    if code == "invalid_request":
        return 400
    return 502


def _error_detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


@router.get("/iconify/{prefix}/{name}.svg")
@limiter.limit("120/minute")
async def get_design_icon_svg(
    prefix: str,
    name: str,
    request: Request,
    iconify_client: IconifyClient = Depends(get_iconify_client),
) -> FastAPIResponse:
    """Return a sanitized Iconify SVG through the regular OpenMates API."""
    if not is_valid_iconify_prefix(prefix) or not is_valid_iconify_name(name):
        raise HTTPException(status_code=400, detail=_error_detail("invalid_icon_id", "Invalid Iconify icon identifier"))

    cache_key = f"iconify-svg:{prefix}:{name}"
    cache = getattr(request.app.state, "iconify_svg_cache", None)
    if isinstance(cache, dict) and cache_key in cache:
        svg = cache[cache_key]
    else:
        try:
            svg = sanitize_iconify_svg(await iconify_client.fetch_svg(prefix, name))
        except IconifyProviderError as exc:
            raise HTTPException(status_code=_provider_error_status(exc.code), detail=_error_detail(exc.code, exc.message)) from exc
        if isinstance(cache, dict):
            cache[cache_key] = svg

    return FastAPIResponse(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": SVG_CACHE_CONTROL, "X-Content-Type-Options": "nosniff"},
    )
