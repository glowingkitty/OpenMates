"""Direct preview fetches preserve successful images and source access denials."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest


@pytest.fixture
def fetch_module(monkeypatch):
    package = ModuleType("_preview_boundary.services")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, package.__name__, package)
    config = ModuleType("_preview_boundary.config")
    config.settings = SimpleNamespace(
        user_agent="OpenMates-Preview/1.0", request_timeout_seconds=10,
        max_image_size_bytes=1024, allowed_image_types=["image/png"],
    )
    monkeypatch.setitem(sys.modules, config.__name__, config)
    name = "_preview_boundary.services.fetch_service"
    path = Path(__file__).parents[1] / "preview/app/services/fetch_service.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


# contract-test: infrastructure
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["image", "html"])
@pytest.mark.parametrize("status", [200, 403, 415])
async def test_direct_fetch_does_not_retry_source_denials(fetch_module, kind, status):
    calls = []

    def origin(request):
        calls.append(request)
        assert request.headers["user-agent"] == "OpenMates-Preview/1.0"
        assert "referer" not in request.headers
        return httpx.Response(
            status, headers={"content-type": "image/png" if kind == "image" else "text/html"},
            content=b"image" if kind == "image" else b"<title>Supported page</title>",
        )

    async def validated(url):
        return url

    service = fetch_module.FetchService.__new__(fetch_module.FetchService)
    service._validate_url = validated
    async with httpx.AsyncClient(transport=httpx.MockTransport(origin)) as client:
        service._client = client
        operation = service.fetch_image if kind == "image" else service.fetch_html
        if status == 200:
            result = await operation("https://source.example/content")
            assert result == ((b"image", "image/png") if kind == "image" else "<title>Supported page</title>")
        else:
            with pytest.raises(fetch_module.FetchError) as error:
                await operation("https://source.example/content")
            assert error.value.status_code == status
    assert len(calls) == 1
    assert not hasattr(service, "_proxy_client")
    await fetch_module.fetch_service.close()
