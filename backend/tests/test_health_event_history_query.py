"""Regression: health history URL must not contain a raw '+' (decoded as space -> Directus 400)."""
# contract-test-file: infrastructure
import asyncio
from unittest.mock import AsyncMock, MagicMock

from backend.core.api.app.services.directus.health_event_methods import HealthEventMethods


def test_since_filter_has_no_plus_offset():
    ds = MagicMock(base_url="http://cms")
    ds._make_api_request = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"data": []}))
    m = HealthEventMethods(ds)
    asyncio.run(m.get_health_history(since_timestamp=1_700_000_000))
    url = ds._make_api_request.await_args.args[1]
    assert "+" not in url
    assert "filter[created_at][_gte]=2023-11-14T22:13:20Z" in url
