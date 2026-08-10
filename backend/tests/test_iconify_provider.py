# backend/tests/test_iconify_provider.py
#
# Contract tests for the Iconify provider wrapper used by design.search_icons.
# Network calls are mocked so normal tests never depend on Iconify availability.
# The tests pin metadata normalization, license filtering, typed failures, and
# SVG sanitization before the provider implementation lands.

from __future__ import annotations

import httpx
import pytest

from backend.shared.providers.iconify.client import (
    IconifyClient,
    IconifyProviderError,
    is_permissive_license,
    sanitize_iconify_svg,
)


def _client(handler: httpx.MockTransport) -> tuple[IconifyClient, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=handler)
    return IconifyClient(http_client=http_client), http_client


@pytest.mark.asyncio
async def test_search_icons_normalizes_and_filters_permissive_licenses() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api.iconify.design"
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "icons": ["lucide:home", "mdi:home", "logos:home-assistant"],
                    "collections": {
                        "lucide": {"name": "Lucide", "license": {"title": "ISC", "spdx": "ISC", "url": "https://lucide.dev/license"}},
                        "mdi": {"name": "Material Design Icons", "license": {"title": "Apache 2.0", "spdx": "Apache-2.0"}},
                        "logos": {"name": "Logos", "license": {"title": "CC BY-SA 4.0", "spdx": "CC-BY-SA-4.0"}},
                    },
                },
            )
        if request.url.path == "/lucide.json":
            return httpx.Response(200, json={"icons": {"home": {"width": 24, "height": 24, "body": "<path/>"}}})
        if request.url.path == "/mdi.json":
            return httpx.Response(200, json={"icons": {"home": {"width": 24, "height": 24, "body": "<path fill=\"currentColor\"/>"}}})
        raise AssertionError(f"Unexpected request: {request.url}")

    client, http_client = _client(httpx.MockTransport(handler))
    try:
        results = await client.search_icons("home", count=10)
    finally:
        await http_client.aclose()

    assert [result.icon_id for result in results] == ["lucide:home", "mdi:home"]
    assert [result.collection_name for result in results] == ["Lucide", "Material Design Icons"]
    assert results[0].svg_path == "/v1/apps/design/icons/iconify/lucide/home.svg"
    assert results[0].license_spdx == "ISC"
    assert results[1].license_spdx == "Apache-2.0"
    assert all("svg" not in result.model_dump() for result in results)
    assert requests[0].url.params["query"] == "home"
    assert requests[0].url.params["limit"] == "10"


def test_permissive_license_policy_matches_contract() -> None:
    assert is_permissive_license("MIT") is True
    assert is_permissive_license("Apache-2.0") is True
    assert is_permissive_license("BSD-3-Clause") is True
    assert is_permissive_license("CC0-1.0") is True
    assert is_permissive_license("OFL-1.1") is True
    assert is_permissive_license("CC-BY-SA-4.0") is False
    assert is_permissive_license("GPL-3.0") is False
    assert is_permissive_license(None) is False


@pytest.mark.asyncio
async def test_fetch_svg_returns_sanitized_svg_and_typed_missing_error() -> None:
    responses = iter(
        [
            httpx.Response(200, content=b'<svg width="24" height="24" onclick="bad()"><path fill="currentColor"/></svg>', headers={"content-type": "image/svg+xml"}),
            httpx.Response(404, text="Not found"),
        ]
    )

    client, http_client = _client(httpx.MockTransport(lambda _request: next(responses)))
    try:
        svg = await client.fetch_svg("lucide", "home")
        with pytest.raises(IconifyProviderError) as excinfo:
            await client.fetch_svg("lucide", "missing")
    finally:
        await http_client.aclose()

    assert "<svg" in svg
    assert "onclick" not in svg
    assert excinfo.value.code == "icon_not_found"


@pytest.mark.parametrize(
    "unsafe_svg",
    [
        '<svg><script>alert(1)</script></svg>',
        '<svg><foreignObject><p>html</p></foreignObject></svg>',
        '<svg><image href="https://example.test/tracker.png" /></svg>',
        '<svg><a href="&#106;avascript:alert(1)"><path /></a></svg>',
    ],
)
def test_sanitize_iconify_svg_rejects_unsafe_content(unsafe_svg: str) -> None:
    with pytest.raises(IconifyProviderError, match="unsafe"):
        sanitize_iconify_svg(unsafe_svg)


@pytest.mark.asyncio
async def test_search_icons_surfaces_provider_unavailable() -> None:
    client, http_client = _client(httpx.MockTransport(lambda _request: httpx.Response(503, text="unavailable")))
    try:
        with pytest.raises(IconifyProviderError) as excinfo:
            await client.search_icons("home")
    finally:
        await http_client.aclose()

    assert excinfo.value.code == "provider_unavailable"
