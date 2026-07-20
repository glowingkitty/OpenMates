"""Tests for Plans V1 assumption blockers and failed-check loops."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods
from backend.core.api.app.services.user_plan_service import UserPlanService


@pytest.mark.asyncio
async def test_required_assumptions_block_implementation_until_resolved() -> None:
    plan_methods = SimpleNamespace(
        list_assumptions=AsyncMock(return_value=[
            {"assumption_id": "ASM-1", "required_before": "implementation", "status": "unchecked"},
            {"assumption_id": "ASM-2", "required_before": "implementation", "status": "corrected"},
        ]),
        list_reference_patterns=AsyncMock(return_value=[]),
    )

    blockers = await UserPlanService(plan_methods).implementation_blockers("plan-1")

    assert blockers == [{"kind": "assumption", "id": "ASM-1", "status": "unchecked"}]


@pytest.mark.asyncio
async def test_assumption_result_merge_persists_corrections_and_sources() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[
        [{"id": "plan-row", "plan_id": "plan-1"}],
        [{"id": "assumption-row", "version": 1}],
    ])
    directus.update_item = AsyncMock(return_value={"assumption_id": "ASM-1", "status": "corrected", "version": 2})

    service = UserPlanService(UserPlanMethods(directus))
    updated = await service.update_assumption(
        "plan-1",
        "user-1",
        "ASM-1",
        {
            "status": "corrected",
            "encrypted_corrected_text": "cipher-corrected",
            "encrypted_evidence_summary": "cipher-evidence",
            "encrypted_sources": "cipher-sources",
            "source_count": 2,
        },
    )

    assert updated["status"] == "corrected"
    patch = directus.update_item.await_args.args[2]
    assert patch["encrypted_corrected_text"] == "cipher-corrected"
    assert patch["encrypted_sources"] == "cipher-sources"


@pytest.mark.asyncio
async def test_failed_required_check_moves_plan_back_to_blocked_loop() -> None:
    plan_methods = SimpleNamespace()
    plan_methods.get_plan = AsyncMock(return_value={"id": "plan-row", "plan_id": "plan-1", "version": 1, "status": "running_checks"})
    plan_methods.update_verification = AsyncMock(return_value={"verification_id": "V-1", "status": "failed", "required_for_done": True})
    plan_methods.update_plan = AsyncMock(return_value={"plan_id": "plan-1", "status": "blocked"})

    updated = await UserPlanService(plan_methods).add_verification_evidence("plan-1", "user-1", "V-1", {"status": "failed"})

    assert updated["status"] == "failed"
    plan_methods.update_plan.assert_awaited_once_with("plan-1", "user-1", {"status": "blocked", "continuation_state": "blocked"})
