"""Durable review deadline for remote command approval episodes."""

from __future__ import annotations

import asyncio
import time

from backend.core.api.app.services.remote_command_service import (
    REMOTE_COMMAND_REVIEW_SECONDS,
    RemoteCommandError,
    RemoteCommandService,
)
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app


def schedule_remote_command_review_expiration(
    *, user_id: str, execution_id: str, created_at: int
) -> None:
    app.send_task(
        "app.tasks.remote_commands.expire_review",
        kwargs={
            "user_id": user_id,
            "execution_id": execution_id,
            "created_at": created_at,
        },
        queue="persistence",
        countdown=REMOTE_COMMAND_REVIEW_SECONDS,
        task_id=f"remote-command-review-expire-{execution_id}",
    )


@app.task(
    name="app.tasks.remote_commands.expire_review",
    base=BaseServiceTask,
    bind=True,
)
def expire_remote_command_review(
    self: BaseServiceTask,
    *,
    user_id: str,
    execution_id: str,
    created_at: int,
) -> bool:
    return asyncio.run(
        _expire_remote_command_review(
            self,
            user_id=user_id,
            execution_id=execution_id,
            created_at=created_at,
        )
    )


async def _expire_remote_command_review(
    task: BaseServiceTask,
    *,
    user_id: str,
    execution_id: str,
    created_at: int,
) -> bool:
    await task.initialize_services()
    try:
        outcome = await RemoteCommandService(task.cache_service).expire_review(
            user_id=user_id,
            execution_id=execution_id,
            created_at=created_at,
            now=int(time.time()),
        )
    except RemoteCommandError:
        return False
    if not outcome.get("expired") or outcome.get("replayed"):
        return False
    job = outcome["job"]
    from backend.apps.ai.tasks.async_skill_continuation import (
        dispatch_async_skill_continuation,
    )

    await dispatch_async_skill_continuation(
        cache_service=task.cache_service,
        async_task_id=str(job.get("continuation_task_id") or ""),
        completed_results=[{
            "execution_id": execution_id,
            "status": "expired",
            "error": "Remote command review expired before approval.",
        }],
        result_status="failed",
        request_metadata={
            "project_id": job.get("project_id"),
            "chat_id": job.get("chat_id"),
            "source_id": job.get("source_id"),
        },
    )
    return True
