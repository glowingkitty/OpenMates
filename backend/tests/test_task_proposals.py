# backend/tests/test_task_proposals.py
#
# Focused pure-unit tests for Tasks V1 assistant proposal sanitization. These do
# not import the full postprocessor stack, so they run without optional LLM/env
# dependencies.

from backend.apps.ai.processing.task_proposals import (
    sanitize_task_proposals,
    sanitize_task_update_proposals,
)


def test_task_proposals_are_bounded_and_sanitized() -> None:
    result = sanitize_task_proposals(
        [
            {
                "title": "  Draft launch checklist  ",
                "description": "  Include docs and owner review  ",
                "status": "blocked",
                "assignee_type": "ai",
            },
            {"title": "Second task", "status": "not-a-status", "assignee_type": "unknown"},
            {"title": "Third task"},
            {"title": "Fourth task should be ignored"},
        ],
        "test",
    )

    assert [proposal.title for proposal in result] == [
        "Draft launch checklist",
        "Second task",
        "Third task",
    ]
    assert result[0].description == "Include docs and owner review"
    assert result[0].status == "blocked"
    assert result[0].assignee_type == "ai"
    assert result[1].status == "todo"
    assert result[1].assignee_type == "user"


def test_invalid_task_proposals_are_dropped() -> None:
    assert sanitize_task_proposals(
        [None, "not a dict", {"title": "   "}, {"description": "missing title"}],
        "test",
    ) == []


def test_task_update_proposals_require_visible_task_id_and_a_change() -> None:
    result = sanitize_task_update_proposals(
        [
            {"task_id": "task-1", "status": "done"},
            {"task_id": "task-2", "status": "invalid"},
            {"task_id": "   "},
            {"title": "missing id"},
        ],
        "test",
    )

    assert len(result) == 1
    assert result[0].task_id == "task-1"
    assert result[0].status == "done"
