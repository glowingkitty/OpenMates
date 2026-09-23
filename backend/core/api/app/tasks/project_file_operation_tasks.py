"""Bounded wait callbacks for client-executed Project file operations."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from backend.core.api.app.services.email_delivery_guard import send_email_once
from backend.core.api.app.services.project_file_operation_service import (
    PROJECT_FILE_OPERATION_PAUSE_SECONDS,
    PROJECT_FILE_OPERATION_WAIT_EMAIL_SECONDS,
    ProjectFileOperationError,
    ProjectFileOperationService,
)
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app


logger = logging.getLogger(__name__)


def schedule_project_file_operation_deadlines(
    *,
    user_id: str,
    operation_id: str,
    episode_id: str,
) -> None:
    """Schedule fixed episode callbacks; reconnects and claims never reset them."""
    app.send_task(
        "app.tasks.email_tasks.project_file_operation_wait_notification",
        kwargs={
            "user_id": user_id,
            "operation_id": operation_id,
            "episode_id": episode_id,
        },
        queue="email",
        countdown=PROJECT_FILE_OPERATION_WAIT_EMAIL_SECONDS,
        task_id=f"project-file-email-{operation_id}-{episode_id}",
    )
    app.send_task(
        "app.tasks.project_file_operations.pause_if_due",
        kwargs={
            "user_id": user_id,
            "operation_id": operation_id,
            "episode_id": episode_id,
        },
        queue="persistence",
        countdown=PROJECT_FILE_OPERATION_PAUSE_SECONDS,
        task_id=f"project-file-pause-{operation_id}-{episode_id}",
    )


@app.task(
    name="app.tasks.email_tasks.project_file_operation_wait_notification",
    base=BaseServiceTask,
    bind=True,
)
def project_file_operation_wait_notification(
    self: BaseServiceTask,
    *,
    user_id: str,
    operation_id: str,
    episode_id: str,
) -> bool:
    return asyncio.run(
        _project_file_operation_wait_notification(
            self,
            user_id=user_id,
            operation_id=operation_id,
            episode_id=episode_id,
        )
    )


async def _project_file_operation_wait_notification(
    task: BaseServiceTask,
    *,
    user_id: str,
    operation_id: str,
    episode_id: str,
) -> bool:
    await task.initialize_services()
    service = ProjectFileOperationService(task.cache_service)
    try:
        job = await service.get_job(user_id=user_id, operation_id=operation_id)
    except ProjectFileOperationError:
        return False
    now = int(time.time())
    if (
        job.get("episode_id") != episode_id
        or now < int(job.get("email_due_at") or 0)
        or now >= int(job.get("pause_at") or 0)
    ):
        return False

    chat_id = job.get("chat_id")
    if not isinstance(chat_id, str) or not chat_id:
        return False
    try:
        cached_chat = await task.cache_service.get(f"chat:{chat_id}:metadata")
    except Exception:
        logger.warning(
            "Skipping Project file wait notification because chat deletion state could not be verified",
            exc_info=True,
        )
        return False
    if isinstance(cached_chat, dict) and cached_chat.get("deleted") is True:
        return False
    try:
        chats = await task.directus_service.get_items(
            "chats",
            params={
                "fields": "id",
                "filter": {"id": {"_eq": chat_id}},
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
    except Exception:
        logger.warning(
            "Skipping Project file wait notification because chat existence could not be verified",
            exc_info=True,
        )
        return False
    if not any(isinstance(chat, dict) and chat.get("id") == chat_id for chat in chats or []):
        return False

    users = await task.directus_service.get_items(
        "directus_users",
        params={
            "fields": (
                "id,language,darkmode,vault_key_id,encrypted_notification_email,"
                "encrypted_email_address,email_notifications_enabled,email_notification_preferences"
            ),
            "filter": {"id": {"_eq": user_id}},
            "limit": 1,
        },
        admin_required=True,
    )
    user = users[0] if users else None
    if not isinstance(user, dict) or not user.get("email_notifications_enabled", False):
        return False
    preferences = user.get("email_notification_preferences") or {}
    if isinstance(preferences, str):
        try:
            preferences = json.loads(preferences)
        except Exception:
            preferences = {}
    if not isinstance(preferences, dict) or not preferences.get("aiResponses", True):
        return False
    encrypted_email = user.get("encrypted_notification_email") or user.get("encrypted_email_address")
    vault_key_id = user.get("vault_key_id")
    if not encrypted_email or not vault_key_id:
        return False
    recipient_email = await task.encryption_service.decrypt_with_user_key(
        encrypted_email, vault_key_id
    )
    if not recipient_email:
        return False
    if not await service.mark_email_sent(
        user_id=user_id,
        operation_id=operation_id,
        episode_id=episode_id,
        now=now,
    ):
        return False

    from backend.shared.python_utils.frontend_url import get_frontend_base_url

    sent, _status = await send_email_once(
        directus=task.directus_service,
        email_template_service=task.email_template_service,
        email_type="project_file_wait",
        campaign_key="projectFileWait",
        recipient_kind="directus_user",
        recipient_id=user_id,
        recipient_email=recipient_email,
        template="ai-response-notification",
        context={
            "darkmode": bool(user.get("darkmode", False)),
            "response_preview": "Open OpenMates to continue a pending Project file request.",
            "chat_title": None,
            "chat_url": f"{get_frontend_base_url()}/chat/{job['chat_id']}",
        },
        lang=user.get("language") or "en",
        stage=episode_id,
        metadata={"operation_id": operation_id, "chat_id": job["chat_id"]},
    )
    return sent


@app.task(
    name="app.tasks.project_file_operations.pause_if_due",
    base=BaseServiceTask,
    bind=True,
)
def pause_project_file_operation_if_due(
    self: BaseServiceTask,
    *,
    user_id: str,
    operation_id: str,
    episode_id: str,
) -> bool:
    return asyncio.run(
        _pause_project_file_operation_if_due(
            self,
            user_id=user_id,
            operation_id=operation_id,
            episode_id=episode_id,
        )
    )


async def _pause_project_file_operation_if_due(
    task: BaseServiceTask,
    *,
    user_id: str,
    operation_id: str,
    episode_id: str,
) -> bool:
    await task.initialize_core_services()
    service = ProjectFileOperationService(task.cache_service)
    try:
        paused = await service.pause_if_due(
            user_id=user_id,
            operation_id=operation_id,
            episode_id=episode_id,
        )
    except ProjectFileOperationError:
        return False
    if paused:
        from backend.apps.ai.tasks.async_skill_continuation import async_skill_continuation_key

        await task.cache_service.delete(async_skill_continuation_key(operation_id))
    return paused
