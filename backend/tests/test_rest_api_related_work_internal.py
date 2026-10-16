"""Product HTTP proof that memory-only summary IPC rejects public credentials.

Run through the isolated coordinator REST suite; no inference or private state.
"""

import os

import httpx
import pytest


# contract-test: direct surface=rest_api assertions=chats.context.memory-only-summary
@pytest.mark.integration
@pytest.mark.parametrize("path", ["completion", "active", "write", "read", "context/seal", "context/open"])
@pytest.mark.parametrize("authorization", [None, "Bearer invalid-public-api-key"])
def test_recent_summary_runtime_ipc_rejects_public_access(path, authorization):
    base_url = os.getenv("OPENMATES_E2E_API_URL") or os.getenv("OPENMATES_API_URL")
    if not base_url:
        pytest.skip("Coordinator-provided isolated API URL required")
    headers = {"Authorization": authorization} if authorization else {}
    with httpx.Client(base_url=base_url, timeout=10) as client:
        response = client.post(f"/internal/recent-work/{path}", headers=headers,
                               json={"text": "synthetic-private-sentinel"})
    assert response.status_code in {401, 403, 404}
    assert "synthetic-private-sentinel" not in response.text
