# backend/tests/test_design_icon_svg_route.py
#
# Contract tests for the authenticated OpenMates Design icon SVG route.
# The route must validate Iconify identifiers, fetch server-side, sanitize SVG,
# cache safe SVG text, and never route SVG loading through the preview server.

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.api.app.routes.design_icons import get_iconify_client, require_design_icon_auth, router
from backend.shared.providers.iconify.client import IconifyProviderError


class FakeIconifyClient:
    def __init__(self, svg: str = '<svg width="24" height="24"><path fill="currentColor"/></svg>') -> None:
        self.svg = svg
        self.calls: list[tuple[str, str]] = []

    async def fetch_svg(self, prefix: str, name: str) -> str:
        self.calls.append((prefix, name))
        if name == "missing":
            raise IconifyProviderError("Iconify", "icon_not_found", "Iconify icon not found")
        if name == "unsafe":
            raise IconifyProviderError("Iconify", "unsafe_svg", "Iconify returned unsafe SVG")
        if name == "down":
            raise IconifyProviderError("Iconify", "provider_unavailable", "Iconify unavailable")
        return self.svg


def _app(fake_client: FakeIconifyClient) -> FastAPI:
    app = FastAPI()
    app.state.iconify_svg_cache = {}
    app.include_router(router)
    app.dependency_overrides[get_iconify_client] = lambda: fake_client
    app.dependency_overrides[require_design_icon_auth] = lambda: {"id": "user-1"}
    return app


def test_design_icon_svg_route_returns_sanitized_svg_and_cache_headers() -> None:
    fake_client = FakeIconifyClient('<svg width="24" height="24" onclick="bad()"><path fill="currentColor"/></svg>')
    client = TestClient(_app(fake_client))

    first = client.get("/v1/apps/design/icons/iconify/lucide/home.svg")
    second = client.get("/v1/apps/design/icons/iconify/lucide/home.svg")

    assert first.status_code == 200
    assert first.headers["content-type"].startswith("image/svg+xml")
    assert first.headers["cache-control"] == "public, max-age=86400"
    assert "onclick" not in first.text
    assert "<svg" in first.text
    assert second.status_code == 200
    assert fake_client.calls == [("lucide", "home")]


@pytest.mark.parametrize(
    "path",
    [
        "/v1/apps/design/icons/iconify/bad_prefix/home.svg",
        "/v1/apps/design/icons/iconify/lucide/bad.name.svg",
        "/v1/apps/design/icons/iconify/lucide/../home.svg",
    ],
)
def test_design_icon_svg_route_rejects_invalid_identifiers(path: str) -> None:
    client = TestClient(_app(FakeIconifyClient()))

    response = client.get(path)

    assert response.status_code in {400, 404}
    if response.status_code == 400:
        assert response.json()["detail"]["code"] == "invalid_icon_id"


@pytest.mark.parametrize(
    ("name", "status", "code"),
    [
        ("missing", 404, "icon_not_found"),
        ("unsafe", 502, "unsafe_svg"),
        ("down", 503, "provider_unavailable"),
    ],
)
def test_design_icon_svg_route_maps_provider_errors(name: str, status: int, code: str) -> None:
    client = TestClient(_app(FakeIconifyClient()))

    response = client.get(f"/v1/apps/design/icons/iconify/lucide/{name}.svg")

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_design_icon_svg_route_does_not_return_preview_server_urls() -> None:
    client = TestClient(_app(FakeIconifyClient()))

    response = client.get("/v1/apps/design/icons/iconify/lucide/search.svg")

    assert response.status_code == 200
    assert "preview.openmates.org" not in response.text
    assert "api.iconify.design" not in response.text


def test_design_icon_svg_route_declares_auth_dependency() -> None:
    api_route = next(route for route in router.routes if str(getattr(route, "path", "")).endswith("/iconify/{prefix}/{name}.svg"))
    dependency_calls = {dependency.call for dependency in api_route.dependant.dependencies}

    assert require_design_icon_auth in dependency_calls
