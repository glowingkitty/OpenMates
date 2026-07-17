"""Task app-skill embed contract tests.

These tests define the backend-only first slice for the Tasks app skill. The
skill returns embed-ready child task results for the existing EmbedService parent
`app_skill_use` flow; browser rendering and fullscreen UI are intentionally out
of scope for this slice.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.apps.tasks.skills.create_skill import CreateSkill
from backend.apps.ai.processing.task_tool_executor import should_keep_tasks_create_payload_as_single_request


class FakeTaskStageService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def stage_create(
        self,
        *,
        user_id: str,
        chat_id: str | None,
        message_id: str | None,
        title: str,
        description: str,
        assignee_type: str,
        status: str,
    ) -> dict[str, Any]:
        call = {
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "title": title,
            "description": description,
            "assignee_type": assignee_type,
            "status": status,
        }
        self.calls.append(call)
        index = len(self.calls)
        return {
            "task_id": f"task-{index}",
            "short_id": f"TASK-{index}",
            "status": status,
            "assignee_type": assignee_type,
            "task_update_job_id": f"job-{index}",
        }


def _skill() -> CreateSkill:
    return CreateSkill(
        app=None,
        app_id="tasks",
        skill_id="create",
        skill_name="Create tasks",
        skill_description="Create one or more tasks.",
    )


@pytest.mark.anyio
async def test_task_create_returns_embed_ready_children_without_system_events() -> None:
    stage_service = FakeTaskStageService()

    response = await _skill().execute(
        tasks=[
            {"title": "Draft checklist", "description": "List launch steps"},
            {"title": "Draft announcement", "assignee": "openmates"},
        ],
        user_id="user-1",
        chat_id="chat-1",
        message_id="message-1",
        task_stage_service=stage_service,
    )
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["app_id"] == "tasks"
    assert payload["skill_id"] == "create"
    assert payload["result_count"] == 2
    assert "taskEvents" not in payload
    assert "pendingTaskUpdateJobs" not in payload
    assert [result["type"] for result in payload["results"]] == ["task", "task"]
    assert [result["parent_app_skill_type"] for result in payload["results"]] == ["app_skill_use", "app_skill_use"]
    assert [result["task_update_job_id"] for result in payload["results"]] == ["job-1", "job-2"]
    assert payload["results"][0]["assignee"] == "user"
    assert payload["results"][1]["assignee"] == "openmates"

    assert stage_service.calls[0]["assignee_type"] == "user"
    assert stage_service.calls[1]["assignee_type"] == "ai"


@pytest.mark.anyio
async def test_task_create_accepts_flat_single_task_arguments() -> None:
    stage_service = FakeTaskStageService()

    response = await _skill().execute(
        title="Review risks",
        description="Check launch blockers",
        assignee="user",
        user_id="user-1",
        chat_id="chat-1",
        message_id="message-1",
        task_stage_service=stage_service,
    )

    assert response.success is True
    assert response.result_count == 1
    assert response.results[0]["title"] == "Review risks"
    assert stage_service.calls == [
        {
            "user_id": "user-1",
            "chat_id": "chat-1",
            "message_id": "message-1",
            "title": "Review risks",
            "description": "Check launch blockers",
            "assignee_type": "user",
            "status": "todo",
        }
    ]


def test_task_create_multiple_tasks_stay_in_single_skill_payload() -> None:
    assert should_keep_tasks_create_payload_as_single_request(
        "tasks",
        "create",
        {"tasks": [{"title": "One"}, {"title": "Two"}]},
    )
    assert not should_keep_tasks_create_payload_as_single_request(
        "web",
        "search",
        {"query": ["one", "two"]},
    )
