# backend/tests/test_design_icon_svg_route.py
#
# Contract tests for the public OpenMates Design icon SVG route.
# The route must validate Iconify identifiers, fetch server-side, sanitize SVG,
# cache safe SVG text, and never route SVG loading through the preview server.

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.api.app.routes.design_icons import get_iconify_client, router
from backend.core.api.app.routes import design_icons
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
    app.include_router(router)
    app.dependency_overrides[get_iconify_client] = lambda: fake_client
    return app


# contract-test: supporting surface=rest_api assertions=public-example-chats.transcript.safe-rendering
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
    assert second.text == first.text
    assert fake_client.calls == [("lucide", "home")]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=public-example-chats.admission.reviewed-complete,public-example-chats.transcript.safe-rendering
async def test_design_icon_svg_route_coalesces_requests_without_preinitialized_cache() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class DelayedClient(FakeIconifyClient):
        async def fetch_svg(self, prefix: str, name: str) -> str:
            self.calls.append((prefix, name))
            started.set()
            await release.wait()
            return self.svg

    fake = DelayedClient()
    app = _app(fake)
    assert not hasattr(app.state, "iconify_svg_cache")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        pending = [asyncio.create_task(client.get("/v1/apps/design/icons/iconify/tabler/home-filled.svg")) for _ in range(12)]
        await asyncio.wait_for(started.wait(), timeout=1)
        release.set()
        responses = await asyncio.wait_for(asyncio.gather(*pending), timeout=1)
        later = await client.get("/v1/apps/design/icons/iconify/tabler/home-filled.svg")

    assert all(response.status_code == 200 and response.text == later.text for response in responses)
    assert "<path" in later.text
    assert fake.calls == [("tabler", "home-filled")]
    assert not app.state.iconify_svg_cache.in_flight


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=public-example-chats.admission.reviewed-complete
async def test_design_icon_svg_route_coalesces_failures_then_allows_recovery() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class RecoveringClient(FakeIconifyClient):
        failing = True

        async def fetch_svg(self, prefix: str, name: str) -> str:
            self.calls.append((prefix, name))
            started.set()
            await release.wait()
            if self.failing:
                raise IconifyProviderError("Iconify", "provider_error", "Iconify returned HTTP 429")
            return self.svg

    fake = RecoveringClient()
    app = _app(fake)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        pending = [asyncio.create_task(client.get("/v1/apps/design/icons/iconify/tabler/home.svg")) for _ in range(6)]
        await asyncio.wait_for(started.wait(), timeout=1)
        release.set()
        responses = await asyncio.wait_for(asyncio.gather(*pending), timeout=1)
        assert all(response.status_code == 502 and response.json()["detail"]["code"] == "provider_error" for response in responses)
        assert len(fake.calls) == 1
        assert not app.state.iconify_svg_cache.in_flight
        assert not app.state.iconify_svg_cache.entries
        fake.failing = False
        recovered = await client.get("/v1/apps/design/icons/iconify/tabler/home.svg")

    assert recovered.status_code == 200
    assert len(fake.calls) == 2


# contract-test: supporting surface=rest_api assertions=public-example-chats.transcript.safe-rendering
def test_design_icon_svg_route_expires_successes(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    monkeypatch.setattr(design_icons, "monotonic", lambda: now[0])
    monkeypatch.setattr(design_icons, "SVG_CACHE_TTL_SECONDS", 10)
    fake = FakeIconifyClient()
    client = TestClient(_app(fake))
    assert client.get("/v1/apps/design/icons/iconify/tabler/home.svg").status_code == 200
    now[0] = 9
    assert client.get("/v1/apps/design/icons/iconify/tabler/home.svg").status_code == 200
    assert len(fake.calls) == 1
    now[0] = 10
    assert client.get("/v1/apps/design/icons/iconify/tabler/home.svg").status_code == 200
    assert len(fake.calls) == 2


@pytest.mark.parametrize("bound", ["entries", "bytes"])
# contract-test: supporting surface=rest_api assertions=public-example-chats.transcript.safe-rendering
def test_design_icon_svg_route_evicts_within_bounds(bound: str, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeIconifyClient()
    svg_size = len(design_icons.sanitize_iconify_svg(fake.svg).encode("utf-8"))
    if bound == "entries":
        monkeypatch.setattr(design_icons, "SVG_CACHE_MAX_ENTRIES", 1)
    else:
        monkeypatch.setattr(design_icons, "SVG_CACHE_MAX_BYTES", svg_size)
    app = _app(fake)
    client = TestClient(app)
    for name in ["home", "settings", "home"]:
        assert client.get(f"/v1/apps/design/icons/iconify/tabler/{name}.svg").status_code == 200
    assert fake.calls == [("tabler", "home"), ("tabler", "settings"), ("tabler", "home")]
    assert len(app.state.iconify_svg_cache.entries) == 1
    assert app.state.iconify_svg_cache.bytes_used == svg_size


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=public-example-chats.admission.reviewed-complete,public-example-chats.transcript.safe-rendering
async def test_design_icon_svg_route_bounds_in_flight_and_survives_cancelled_waiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(design_icons, "SVG_CACHE_MAX_IN_FLIGHT", 1)
    started = asyncio.Event()
    release = asyncio.Event()

    class DelayedClient(FakeIconifyClient):
        async def fetch_svg(self, prefix: str, name: str) -> str:
            self.calls.append((prefix, name))
            started.set()
            await release.wait()
            return self.svg

    fake = DelayedClient()
    app = _app(fake)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = asyncio.create_task(client.get("/v1/apps/design/icons/iconify/tabler/home.svg"))
        await asyncio.wait_for(started.wait(), timeout=1)
        other = await client.get("/v1/apps/design/icons/iconify/tabler/settings.svg")
        assert other.status_code == 503
        assert len(fake.calls) == 1
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        response = await asyncio.wait_for(client.get("/v1/apps/design/icons/iconify/tabler/home.svg"), timeout=1)

    assert response.status_code == 200
    assert fake.calls == [("tabler", "home")]
    assert not app.state.iconify_svg_cache.in_flight


@pytest.mark.parametrize(
    "path",
    [
        "/v1/apps/design/icons/iconify/bad_prefix/home.svg",
        "/v1/apps/design/icons/iconify/lucide/bad.name.svg",
        "/v1/apps/design/icons/iconify/lucide/../home.svg",
    ],
)
# contract-test: supporting surface=rest_api assertions=public-example-chats.transcript.safe-rendering
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
# contract-test: supporting surface=rest_api assertions=public-example-chats.admission.reviewed-complete
def test_design_icon_svg_route_maps_provider_errors(name: str, status: int, code: str) -> None:
    client = TestClient(_app(FakeIconifyClient()))

    response = client.get(f"/v1/apps/design/icons/iconify/lucide/{name}.svg")

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


# contract-test: supporting surface=rest_api assertions=public-example-chats.transcript.safe-rendering
def test_design_icon_svg_route_does_not_return_preview_server_urls() -> None:
    client = TestClient(_app(FakeIconifyClient()))

    response = client.get("/v1/apps/design/icons/iconify/lucide/search.svg")

    assert response.status_code == 200
    assert "preview.openmates.org" not in response.text
    assert "api.iconify.design" not in response.text


# contract-test: supporting surface=rest_api assertions=public-example-chats.admission.reviewed-complete,public-example-chats.transcript.safe-rendering
def test_design_icon_svg_route_is_public() -> None:
    api_route = next(route for route in router.routes if str(getattr(route, "path", "")).endswith("/iconify/{prefix}/{name}.svg"))
    dependency_calls = {dependency.call for dependency in api_route.dependant.dependencies}

    assert get_iconify_client in dependency_calls
    assert len(dependency_calls) == 1
