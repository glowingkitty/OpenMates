# backend/tests/test_workflow_scheduler_owner_contract.py
#
# Scheduler contract for the raw owner reference returned only by Directus.
# It proves the task-side callbacks receive that trusted claim value rather than
# accepting a caller-supplied owner identifier.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

from typing import Any

import pytest

from backend.core.api.app.services.workflow_scheduler_service import WorkflowSchedulerService


class FakeRuntime:
    async def execute(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        if operation == "claim_due_trigger":
            return {
                "accepted": True,
                "run_id": "run-1",
                "workflow_id": "workflow-1",
                "version_id": "version-1",
                "owner_user_id": "owner-from-directus",
                "encrypted_schedule_config_ref": "vault://workflows/workflow_schedule_config/1",
                "claim_token": "claim-token",
                "claim_generation": 1,
            }
        if operation == "start_claimed_run":
            return {"started": True}
        if operation == "advance_claimed_trigger":
            return {"next_run_at": data["next_run_at"]}
        raise AssertionError(operation)


@pytest.mark.asyncio
async def test_scheduler_uses_only_the_owner_returned_by_the_due_claim() -> None:
    seen_owners: list[str] = []

    async def decrypt_and_schedule(owner_user_id: str, config_ref: str) -> int:
        seen_owners.append(owner_user_id)
        assert config_ref == "vault://workflows/workflow_schedule_config/1"
        return 1_800_000_000

    async def execute_run(_run_id: str, _workflow_id: str, _version_id: str, owner_user_id: str) -> None:
        seen_owners.append(owner_user_id)

    result = await WorkflowSchedulerService(FakeRuntime()).execute_due_trigger(
        "trigger-1",
        decrypt_and_schedule,
        execute_run,
    )

    assert result == {"accepted": True, "run_id": "run-1", "next_run_at": 1_800_000_000}
    assert seen_owners == ["owner-from-directus", "owner-from-directus"]
