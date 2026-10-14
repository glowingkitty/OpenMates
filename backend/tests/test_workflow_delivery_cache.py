"""Workflow transaction reads must bypass Directus response caching."""
from __future__ import annotations

import httpx
import pytest

from backend.core.api.app.services.workflow_chat_delivery_service import DirectusWorkflowChatDeliveryRepository
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository


# contract-test: supporting surface=rest_api assertions=workflows.chat-delivery.claim-fenced,workflows.history.persisted-recovery,workflows.execution.lifecycle-visible
@pytest.mark.parametrize("repository_type", [DirectusWorkflowChatDeliveryRepository, DirectusWorkflowRepository])
@pytest.mark.parametrize("refresh_auth", [False, True])
def test_reads_observe_atomic_delivery_changes_despite_cached_response(repository_type, refresh_auth):
    """A cached pre-claim revision must not cause a false persistence CAS conflict."""
    current = {"revision": 1, "status": "delivery_pending"}
    cached = dict(current)
    reads = []

    def handle(request):
        if request.method == "GET":
            reads.append(request)
            if refresh_auth and len(reads) == 1:
                return httpx.Response(401, json={"errors": []})
            fresh = request.headers.get("Cache-Control") == "no-store"
            return httpx.Response(200, json={"data": [dict(current if fresh else cached)]})
        assert request.url.path == "/workflow-runtime-transaction"
        current.update(revision=2, status="claimed")
        return httpx.Response(200, json={"data": {"delivery": dict(current)}})

    repository = repository_type(base_url="http://cms.example", token="test-token")
    repository._client.close()
    repository._client = httpx.Client(transport=httpx.MockTransport(handle))
    repository._admin_login_token = lambda: "refreshed-test-token"

    def read():
        if isinstance(repository, DirectusWorkflowRepository):
            return repository._get_items("workflow_chat_deliveries", {})[0]
        return repository._get_items({})[0]

    try:
        assert read() == {"revision": 1, "status": "delivery_pending"}
        repository._request("POST", "/workflow-runtime-transaction", json={})
        assert read() == {"revision": 2, "status": "claimed"}
        assert all(request.headers.get("Cache-Control") == "no-store" for request in reads)
    finally:
        repository._client.close()


# contract-test: supporting surface=rest_api assertions=workflows.chat-delivery.pending-private
def test_delivery_repository_reuses_refreshed_admin_token_after_unauthorized_read():
    requests = []

    def handle(request):
        requests.append((request.method, request.url.path, request.headers.get("Authorization")))
        if request.url.path == "/auth/login":
            return httpx.Response(200, json={"data": {"access_token": "refreshed-token"}})
        assert request.url.path == "/items/workflow_chat_deliveries"
        if request.headers.get("Authorization") == "Bearer stale-token":
            return httpx.Response(401, json={"errors": []})
        assert request.headers.get("Authorization") == "Bearer refreshed-token"
        return httpx.Response(200, json={"data": []})

    repository = DirectusWorkflowChatDeliveryRepository(base_url="http://cms.example", token="stale-token")
    repository.admin_email = "admin@example.test"
    repository.admin_password = "test-password"
    repository._client.close()
    repository._client = httpx.Client(transport=httpx.MockTransport(handle))
    try:
        assert repository._get_items({}) == []
        assert repository._get_items({}) == []
        assert requests == [
            ("GET", "/items/workflow_chat_deliveries", "Bearer stale-token"),
            ("POST", "/auth/login", None),
            ("GET", "/items/workflow_chat_deliveries", "Bearer refreshed-token"),
            ("GET", "/items/workflow_chat_deliveries", "Bearer refreshed-token"),
        ]
    finally:
        repository._client.close()
