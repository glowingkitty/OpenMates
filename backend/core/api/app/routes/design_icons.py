# backend/core/api/app/routes/design_icons.py
#
# Public Design icon SVG route.
# Clients fetch sanitized Iconify SVGs from OpenMates rather than calling Iconify
# directly or using the preview server. The route accepts only validated Iconify
# identifiers, sanitizes SVG text, rate-limits requests, and caches safe SVGs.

from __future__ import annotations

import asyncio
from collections import OrderedDict
from time import monotonic
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
SVG_CACHE_TTL_SECONDS = 86400
SVG_CACHE_MAX_ENTRIES = 512
SVG_CACHE_MAX_BYTES = 8 * 1024 * 1024
SVG_CACHE_MAX_IN_FLIGHT = 64


class _IconSvgCache:
    """Bounded, per-API-process cache of sanitized public SVGs only."""

    def __init__(self) -> None:
        self.entries: OrderedDict[str, tuple[float, str, int]] = OrderedDict()
        self.bytes_used = 0
        self.in_flight: dict[str, asyncio.Task[str]] = {}

    def _remove(self, key: str) -> None:
        self.bytes_used -= self.entries.pop(key)[2]

    async def get_svg(self, key: str, prefix: str, name: str, client: IconifyClient) -> str:
        now = monotonic()
        for expired in [item for item, entry in self.entries.items() if entry[0] <= now]:
            self._remove(expired)
        if key in self.entries:
            self.entries.move_to_end(key)
            return self.entries[key][1]

        task = self.in_flight.get(key)
        if task is None:
            if len(self.in_flight) >= SVG_CACHE_MAX_IN_FLIGHT:
                raise IconifyProviderError("Iconify", "provider_unavailable", "Icon SVG request capacity reached")
            task = asyncio.create_task(self._fetch(key, prefix, name, client))
            self.in_flight[key] = task

            def completed(result: asyncio.Task[str]) -> None:
                self.in_flight.pop(key, None)
                # A disconnected waiter must not cancel another caller's load,
                # nor leave an unobserved failure after all waiters disconnect.
                if not result.cancelled():
                    result.exception()

            task.add_done_callback(completed)
        return await asyncio.shield(task)

    async def _fetch(self, key: str, prefix: str, name: str, client: IconifyClient) -> str:
        svg = sanitize_iconify_svg(await client.fetch_svg(prefix, name))
        size = len(svg.encode("utf-8"))
        if size <= SVG_CACHE_MAX_BYTES:
            while self.entries and (
                len(self.entries) >= SVG_CACHE_MAX_ENTRIES or self.bytes_used + size > SVG_CACHE_MAX_BYTES
            ):
                self._remove(next(iter(self.entries)))
            self.entries[key] = (monotonic() + SVG_CACHE_TTL_SECONDS, svg, size)
            self.bytes_used += size
        return svg


def _get_svg_cache(request: Request) -> _IconSvgCache:
    cache = getattr(request.app.state, "iconify_svg_cache", None)
    if not isinstance(cache, _IconSvgCache):
        # Initialize synchronously before the first await: concurrent requests
        # share one cache even when normal startup supplied no app-state cache.
        cache = _IconSvgCache()
        request.app.state.iconify_svg_cache = cache
    return cache


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
    try:
        svg = await _get_svg_cache(request).get_svg(cache_key, prefix, name, iconify_client)
    except IconifyProviderError as exc:
        raise HTTPException(status_code=_provider_error_status(exc.code), detail=_error_detail(exc.code, exc.message)) from exc

    return FastAPIResponse(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": SVG_CACHE_CONTROL, "X-Content-Type-Options": "nosniff"},
    )
