"""The isolated signed Lens replay never reads or changes real credentials."""
# contract-test-file: infrastructure
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.apps.ai.testing.shopping_images_fixture import GROUP, synthetic_http_response
from backend.shared.providers import serpapi
from backend.shared.testing.mock_context import mock_group_var, mock_mode_var

URL = "http://storage.ci.test:9000/dev-openmates-temp-images/reverse_search/0123456789abcdef_0123456789abcdef.png?X-Amz-Signature=synthetic"


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["valid", "unsigned", "production", "wrong-url", "wrong-query", "wrong-count"])
async def test_fixture_key_stays_local_and_every_other_request_uses_existing_lookup(monkeypatch, variant):
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production" if variant == "production" else "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("OPENMATES_CI_AI_FIXTURES", "1")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://storage.ci.test:9000")
    mode = mock_mode_var.set("real" if variant == "unsigned" else "mock")
    group = mock_group_var.set(GROUP)
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(serpapi, "get_serpapi_key_async", lookup)
    monkeypatch.setattr(serpapi, "_serpapi_api_key_cache", "existing-cache-value")
    original_client = httpx.AsyncClient
    seen = []
    def handler(request):
        seen.append(request)
        response = synthetic_http_response(request)
        assert response is not None
        return response
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    try:
        call = serpapi.google_lens_reverse_search(
            URL if variant != "wrong-url" else "https://example.com/image.png",
            query="refinement" if variant == "wrong-query" else None,
            max_results=4 if variant == "wrong-count" else 3)
        if variant == "valid":
            result = await call
            assert len(result["results"]) == 1 and len(seen) == 1
            lookup.assert_not_awaited()
        else:
            with pytest.raises(ValueError, match="key not available"):
                await call
            lookup.assert_awaited_once()
            assert seen == []
        assert serpapi._serpapi_api_key_cache == "existing-cache-value"
    finally:
        mock_group_var.reset(group)
        mock_mode_var.reset(mode)
