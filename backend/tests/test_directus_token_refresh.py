# backend/tests/test_directus_token_refresh.py
#
# Regression coverage for Directus API token refresh behavior.

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_get_items_does_not_reuse_stale_regular_token():
    from backend.core.api.app.services.directus.directus import DirectusService

    class _Response:
        status_code = 200
        text = "OK"

        def json(self):
            return {"data": []}

    service = object.__new__(DirectusService)
    service.base_url = "http://cms:8055"
    service.token = "stale-token"
    service._make_api_request = AsyncMock(return_value=_Response())

    await service.get_items("encryption_keys", {"limit": 1})

    _, _, kwargs = service._make_api_request.mock_calls[0]
    assert kwargs["headers"] == {"Cache-Control": "no-store"}
