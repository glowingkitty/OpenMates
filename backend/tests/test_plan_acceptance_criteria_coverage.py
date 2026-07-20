"""Tests for Plans V1 acceptance-criteria coverage and check evidence gates."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods
from backend.core.api.app.services.user_plan_service import UserPlanService


@pytest.mark.asyncio
async def test_uncovered_and_ambiguous_required_criteria_block_completion() -> None:
    plan_methods = SimpleNamespace(
        list_criteria=AsyncMock(return_value=[
            {"criterion_id": "AC-1", "required": True, "status": "satisfied", "coverage_status": "uncovered"},
            {"criterion_id": "AC-2", "required": True, "status": "satisfied", "coverage_status": "ambiguous"},
        ]),
        list_verifications=AsyncMock(return_value=[]),
        list_assumptions=AsyncMock(return_value=[]),
        list_reference_patterns=AsyncMock(return_value=[]),
    )

    blockers = await UserPlanService(plan_methods).completion_blockers("plan-1")

    assert {blocker["id"] for blocker in blockers if blocker["kind"] == "criterion_coverage"} == {"AC-1", "AC-2"}


@pytest.mark.asyncio
async def test_ai_validation_and_runnable_checks_store_distinct_metadata() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(side_effect=[
        (True, {"verification_id": "AI-1", "kind": "ai_evaluation", "linked_sub_chat_id": "chat-eval"}),
        (True, {"verification_id": "RUN-1", "kind": "automated_test", "runner_kind": "internal_sandbox", "source_hash": "abc"}),
    ])

    methods = UserPlanMethods(directus)
    ai = await methods.create_verification("plan-1", {
        "verification_id": "AI-1",
        "kind": "ai_evaluation",
        "linked_sub_chat_id": "chat-eval",
        "encrypted_description": "cipher-description",
        "encrypted_evaluator_instructions": "cipher-instructions",
        "created_at": 100,
    })
    runnable = await methods.create_verification("plan-1", {
        "verification_id": "RUN-1",
        "kind": "automated_test",
        "runner_kind": "internal_sandbox",
        "source_hash": "abc",
        "source_embed_id": "embed-source",
        "encrypted_command": "cipher-command",
        "created_at": 100,
    })

    assert ai["linked_sub_chat_id"] == "chat-eval"
    assert runnable["runner_kind"] == "internal_sandbox"
    ai_record = directus.create_item.await_args_list[0].args[1]
    run_record = directus.create_item.await_args_list[1].args[1]
    assert ai_record["lifecycle_status"] == "proposed"
    assert run_record["source_hash"] == "abc"


@pytest.mark.asyncio
async def test_verification_run_details_return_run_and_artifacts() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(side_effect=[
        [{"id": "plan-row", "plan_id": "plan-1"}],
        [{"run_id": "run-1", "runner_kind": "internal_sandbox", "status": "failed"}],
        [{"artifact_id": "artifact-1", "artifact_kind": "stdout"}],
    ])

    result = await UserPlanService(UserPlanMethods(directus)).get_verification_run("plan-1", "user-1", "V-1", "run-1")

    assert result["run"]["run_id"] == "run-1"
    assert result["artifacts"][0]["artifact_kind"] == "stdout"
