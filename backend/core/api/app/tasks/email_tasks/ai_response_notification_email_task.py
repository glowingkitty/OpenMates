"""ID-only completed-chat notification worker with dispatch-time consent checks."""
import asyncio

from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.email_template import EmailTemplateService


async def initialize_notification_email_services(task: BaseServiceTask) -> None:
    """Prepare only the storage, encryption, and email services used at dispatch."""
    await task.initialize_core_services()
    if task._email_template_service is None:
        task._email_template_service = EmailTemplateService(
            secrets_manager=task._secrets_manager,
        )


@app.task(name="app.tasks.email_tasks.ai_response_notification_email_task.send_ai_response_notification",
          base=BaseServiceTask, bind=True, dedup_enabled=False)
def send_ai_response_notification(self, *legacy_args, user_id: str | None = None,
                                  chat_id: str | None = None, message_id: str | None = None,
                                  **legacy_kwargs) -> str:
    # Pre-transition tasks carried plaintext recipient/content and lacked a
    # completed-message identity. Discard them rather than bypass current consent.
    if legacy_args or legacy_kwargs or not all((user_id, chat_id, message_id)):
        return "legacy_discarded"
    try:
        result = asyncio.run(_send(self, user_id=user_id, chat_id=chat_id, message_id=message_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=(30, 90, 180)[min(self.request.retries, 2)], max_retries=3)
    if result in {"failed", "retry_locked", "retry_unavailable", "grace"}:
        raise self.retry(exc=RuntimeError(result), countdown=(30, 90, 180)[min(self.request.retries, 2)], max_retries=3)
    return result


async def _send(task, *, user_id: str, chat_id: str, message_id: str) -> str:
    from backend.core.api.app.services.chat_email_notification_service import dispatch_chat_email
    try:
        await initialize_notification_email_services(task)
        return await dispatch_chat_email(task, user_id=user_id, chat_id=chat_id, message_id=message_id)
    finally:
        await task.cleanup_services()
