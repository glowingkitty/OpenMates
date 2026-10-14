# contract-test-file: infrastructure
"""Large Directus reads preserve scope and read-only retry/auth behavior."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.core.api.app.services.directus.directus import DirectusService, _directus_search_query


def _service(response=None):
    service = object.__new__(DirectusService)
    service.base_url = "http://cms:8055"
    service.ensure_auth_token = AsyncMock(return_value="approved-admin-token")
    service._make_api_request = AsyncMock(return_value=response or httpx.Response(200, json={"data": []}))
    return service


@pytest.mark.asyncio
async def test_500_hash_query_moves_to_search_body_preserving_owner_scope_and_cache_policy():
    hashes = [f"{number:064x}" for number in range(500)]
    params = {"filter[hashed_project_id][_in]": ",".join(hashes),
              "filter[hashed_user_id][_eq]": "authorized-owner", "fields": "id", "limit": 20,
              "sort": ["id"]}
    original = dict(params)
    service = _service()
    assert await service.get_items("project_items", params, admin_required=True, raise_on_error=True) == []
    args, kwargs = service._make_api_request.call_args
    assert args == ("SEARCH", "http://cms:8055/items/project_items")
    assert "params" not in kwargs
    assert kwargs["headers"] == {"Authorization": "Bearer approved-admin-token", "Cache-Control": "no-store"}
    query = kwargs["json"]["query"]
    assert query["filter"] == {"hashed_project_id": {"_in": hashes}, "hashed_user_id": {"_eq": "authorized-owner"}}
    assert query["limit"] == 20 and query["fields"] == "id" and query["sort"] == "id"
    assert query["_ts"].isdecimal()
    assert params == original


@pytest.mark.asyncio
async def test_small_reads_keep_get_and_do_not_pin_regular_authorization():
    service = _service()
    assert await service.get_items("embeds", {"limit": 20}, no_cache=False) == []
    args, kwargs = service._make_api_request.call_args
    assert args[0] == "GET"
    assert kwargs["headers"] == {} and kwargs["params"] == {"limit": 20}
    service.ensure_auth_token.assert_not_awaited()


def test_search_preserves_nested_scope_and_flat_logic_without_mutating_source():
    params = {"filter": json.dumps({"hashed_user_id": {"_eq": "authorized-owner"}}),
              "filter[_or][0][is_private][_eq]": True,
              "filter[_or][1][is_shared][_eq]": False,
              "filter[id][_nin]": ["seen-one", "seen-two"], "limit": 20}
    query = _directus_search_query(params)
    assert query == {"filter": {"hashed_user_id": {"_eq": "authorized-owner"},
                                "_or": [{"is_private": {"_eq": True}}, {"is_shared": {"_eq": False}}],
                                "id": {"_nin": ["seen-one", "seen-two"]}}, "limit": 20}
    assert isinstance(params["filter"], str)


@pytest.mark.parametrize("params", [
    {"filter": {"owner": {"_eq": "one"}}, "filter[owner][_eq]": "two"},
    {"filter[_or][2][owner][_eq]": "one"},
    {"filter[]": "scope"},
])
def test_ambiguous_search_shapes_fail_without_dropping_scope(params):
    with pytest.raises(ValueError):
        _directus_search_query(params)


@pytest.mark.asyncio
async def test_search_body_bound_fails_before_read_request():
    service = _service()
    with pytest.raises(RuntimeError, match="bounded request size"):
        await service.get_items("project_items", {"filter[hashed_project_id][_in]": "a" * (512 * 1024)}, raise_on_error=True)
    service._make_api_request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 431, 500])
async def test_search_provider_errors_cannot_be_reported_as_successful_complete_reads(status):
    service = _service(httpx.Response(status, json={"errors": [{"message": "read rejected"}]}))
    with pytest.raises(RuntimeError):
        await service.get_items("project_items", {"filter[hashed_project_id][_in]": "a" * 5000}, raise_on_error=True)


@pytest.mark.asyncio
async def test_search_preserves_explicit_forbidden_sentinel_and_no_cache_false():
    service = _service(httpx.Response(403, json={"errors": [{"message": "read rejected"}]}))
    assert await service.get_items(
        "project_items", {"filter[hashed_project_id][_in]": "a" * 5000},
        no_cache=False, return_none_on_403=True,
    ) is None
    kwargs = service._make_api_request.call_args.kwargs
    assert kwargs["headers"] == {} and "_ts" not in kwargs["json"]["query"]


@pytest.mark.asyncio
async def test_search_transport_retries_and_refreshes_auth_without_changing_body(monkeypatch):
    from backend.core.api.app.services.directus.api_methods import _make_api_request

    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("temporary read")
        if len(calls) == 2:
            return httpx.Response(401, text="TOKEN_EXPIRED")
        return httpx.Response(200, json={"data": []})

    service = _service()
    service.max_retries = 3
    service.ensure_auth_token = AsyncMock(side_effect=["old-token", "fresh-token"])
    service.clear_tokens = AsyncMock()
    monkeypatch.setattr("backend.core.api.app.services.directus.api_methods.asyncio.sleep", AsyncMock())
    body = {"query": {"filter": {"owner": {"_eq": "authorized-owner"}}, "limit": 20}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service._client = client
        response = await _make_api_request(service, "SEARCH", "http://cms:8055/items/example", json=body)
    assert response.status_code == 200
    assert len(calls) == 3
    assert all(request.method == "SEARCH" and json.loads(request.content) == body for request in calls)
    assert [request.headers["Authorization"] for request in calls] == ["Bearer old-token", "Bearer old-token", "Bearer fresh-token"]
