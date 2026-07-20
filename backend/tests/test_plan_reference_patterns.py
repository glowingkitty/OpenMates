"""Tests for Plans V1 reference-pattern records and blockers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods
from backend.core.api.app.services.user_plan_service import UserPlanService


@pytest.mark.asyncio
async def test_required_reference_patterns_block_implementation_until_inspected() -> None:
    plan_methods = SimpleNamespace(
        list_assumptions=AsyncMock(return_value=[]),
        list_reference_patterns=AsyncMock(return_value=[
            {"pattern_id": "PAT-1", "required_before": "implementation", "status": "required"},
            {"pattern_id": "PAT-2", "required_before": "implementation", "status": "inspected"},
        ]),
    )

    blockers = await UserPlanService(plan_methods).implementation_blockers("plan-1")

    assert blockers == [{"kind": "reference_pattern", "id": "PAT-1", "status": "required"}]


@pytest.mark.asyncio
async def test_completion_required_reference_patterns_block_until_matched_or_waived() -> None:
    plan_methods = SimpleNamespace(
        list_criteria=AsyncMock(return_value=[]),
        list_verifications=AsyncMock(return_value=[]),
        list_assumptions=AsyncMock(return_value=[]),
        list_reference_patterns=AsyncMock(return_value=[
            {"pattern_id": "PAT-1", "required_before": "completion", "status": "drift_detected"},
            {"pattern_id": "PAT-2", "required_before": "completion", "status": "matched"},
        ]),
    )

    blockers = await UserPlanService(plan_methods).completion_blockers("plan-1")

    assert blockers == [{"kind": "reference_pattern", "id": "PAT-1", "status": "drift_detected"}]


@pytest.mark.asyncio
async def test_reference_pattern_records_store_sources_rules_and_anti_patterns() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(return_value=(True, {"pattern_id": "PAT-1", "status": "required"}))

    created = await UserPlanMethods(directus).create_reference_pattern("plan-1", {
        "pattern_id": "PAT-1",
        "category": "cli",
        "status": "required",
        "required_before": "implementation",
        "source_count": 2,
        "encrypted_title": "cipher-title",
        "encrypted_sources": "cipher-sources",
        "encrypted_match_rules": "cipher-rules",
        "encrypted_anti_patterns": "cipher-anti-patterns",
        "created_at": 100,
        "updated_at": 100,
    })

    assert created["status"] == "required"
    record = directus.create_item.await_args.args[1]
    assert record["encrypted_sources"] == "cipher-sources"
    assert record["encrypted_match_rules"] == "cipher-rules"
    assert record["encrypted_anti_patterns"] == "cipher-anti-patterns"
