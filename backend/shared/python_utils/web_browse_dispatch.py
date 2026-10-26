"""Admitted async dispatch; the broker carries opaque identities, never page data."""

from __future__ import annotations

from typing import Any
import uuid

from backend.shared.python_schemas.web_browse import BrowseJob
from backend.shared.python_utils.app_skill_helpers import execute_skill_via_celery


async def dispatch_browser_job(
    job: BrowseJob,
    *,
    producer: Any,
    user_id: str,
    chat_id: str,
    message_id: str,
    vault_key_id: str,
    embed_id: str | None = None,
    external_request: bool = False,
    same_turn_batch_id: str | None = None,
) -> BrowseJob:
    embed_id = embed_id or str(
        uuid.uuid5(uuid.NAMESPACE_URL, "browse-embed:" + job.run_id)
    )
    if not job.dispatch_required:
        return job.model_copy(update={"embed_id": embed_id})
    await execute_skill_via_celery(
        app_id="web",
        skill_id="browse",
        celery_producer=producer,
        task_uuid=job.task_id,
        arguments={
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "session_id": job.session_id,
            "run_id": job.run_id,
            "embed_id": embed_id,
            "user_vault_key_id": vault_key_id,
            "external_request": external_request,
            "same_turn_batch_id": same_turn_batch_id,
        },
    )
    return job.model_copy(update={"embed_id": embed_id})
