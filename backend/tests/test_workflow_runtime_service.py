# backend/tests/test_workflow_runtime_service.py
#
# Unit contract for the backend client of Workflow's internal transaction API.
# It proves only typed metadata crosses the boundary and error codes stay visible.
#
# Spec: docs/specs/workflows-v1/spec.yml (TASK-3)

import pytest

from backend.core.api.app.services.workflow_runtime_service import (
    WorkflowRuntimeProtocolError,
    WorkflowRuntimeService,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class FakeDirectus:
    base_url = "http://cms:8055"

    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.request: dict[str, object] | None = None

    async def _make_api_request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.request = {"method": method, "url": url, **kwargs}
        return self.response


@pytest.mark.asyncio
async def test_executes_typed_workflow_transaction_with_internal_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "service-token")
    directus = FakeDirectus(FakeResponse(200, {"data": {"accepted": True, "run_id": "run-1"}}))

    result = await WorkflowRuntimeService(directus).execute(
        "claim_due_trigger", {"trigger_id": "trigger-1"}
    )

    assert result == {"accepted": True, "run_id": "run-1"}
    assert directus.request == {
        "method": "POST",
        "url": "http://cms:8055/workflow-runtime-transaction",
        "headers": {"X-Internal-Service-Token": "service-token"},
        "json": {
            "operation": "claim_due_trigger",
            "data": {"protocol_version": 1, "trigger_id": "trigger-1"},
        },
    }


@pytest.mark.asyncio
async def test_surfaces_transaction_rejection_without_silent_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "service-token")
    directus = FakeDirectus(FakeResponse(409, {"error": {"code": "trigger_not_due"}}))

    with pytest.raises(WorkflowRuntimeProtocolError, match="trigger_not_due") as error:
        await WorkflowRuntimeService(directus).execute("claim_due_trigger", {"trigger_id": "trigger-1"})

    assert error.value.status_code == 409
    assert error.value.code == "trigger_not_due"
