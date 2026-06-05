# backend/tests/test_base_skill_request_partitioning.py
#
# Regression tests for shared BaseSkill multi-request validation.
# Multi-request app skills must not let one malformed request item fail valid
# sibling items, because each item may map to a separate embed child.
# Architecture context: backend/apps/base_skill.py

import logging

from backend.apps.base_skill import BaseSkill


def _make_skill() -> BaseSkill:
    return BaseSkill(
        app=None,
        app_id="test",
        skill_id="search",
        skill_name="Test Search",
        skill_description="Test search skill",
    )


def test_partition_requests_preserves_valid_siblings_for_missing_field() -> None:
    skill = _make_skill()

    valid, invalid, errors, fatal = skill._partition_requests_by_required_fields(
        requests=[
            {"id": "a", "query": "AI"},
            {"id": "b"},
            {"id": "c", "query": "events"},
        ],
        required_fields=["query"],
        field_display_names={"query": "query"},
        empty_error_message="No requests provided",
        logger=logging.getLogger(__name__),
    )

    assert fatal is None
    assert [request["id"] for request in valid] == ["a", "c"]
    assert invalid == [
        {
            "id": "b",
            "results": [],
            "error": "Request 2 (id: b) is missing required 'query' field",
        }
    ]
    assert errors == ["Request 2 (id: b) is missing required 'query' field"]


def test_merge_grouped_results_preserves_original_request_order() -> None:
    skill = _make_skill()

    merged = skill._merge_grouped_results_preserving_request_order(
        grouped_results=[
            {"id": "a", "results": [{"title": "AI"}]},
            {"id": "c", "results": [{"title": "events"}]},
        ],
        invalid_grouped_results=[{"id": "b", "results": [], "error": "Missing query"}],
        requests=[{"id": "a"}, {"id": "b"}, {"id": "c"}],
    )

    assert [group["id"] for group in merged] == ["a", "b", "c"]
