"""End an inference attempt without inventing a product Task completion."""
from typing import Any


async def finalize_user_task_turn(
    task_methods: Any,
    *,
    task_id: str,
    user_id: str,
    chat_id: str,
    team_id: str | None,
    now: int,
) -> None:
    task = await task_methods.get_task(task_id, user_id, team_id)
    # Explicit task tools own Done/Blocked transitions. Also preserve reassignment
    # and moves that happened while inference was running.
    if not task or task.get("status") != "in_progress":
        return
    if task.get("primary_chat_id") != chat_id or task.get("assignee_type") != "openmates":
        return
    if task.get("ai_execution_state") != "running" or task.get("version") is None:
        return
    version = int(task["version"])
    await task_methods.update_task_if_version(
        task_id, user_id,
        {"version": version, "ai_execution_state": "awaiting_resume", "updated_at": now},
        version, team_id=team_id,
    )
