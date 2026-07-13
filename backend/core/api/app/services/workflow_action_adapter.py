# backend/core/api/app/services/workflow_action_adapter.py
#
# Workflow platform action adapter.
# Centralizes OpenMates-native side effects so the runner does not hardcode
# notification, report, or chat behavior. Actions without an existing safe
# server-side contract fail visibly instead of fabricating a completed result.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

from collections.abc import Callable
import json
import logging
import time
from typing import Any

from backend.core.api.app.services.workflow_chat_delivery_service import WorkflowChatDeliveryService


logger = logging.getLogger(__name__)


class WorkflowActionExecutionError(RuntimeError):
    """A platform action could not be executed by an approved service."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WorkflowActionAdapter:
    """Execute OpenMates platform action nodes for workflow runs."""

    def __init__(
        self,
        cache_service_factory: Callable[[], Any] | None = None,
        directus_service_factory: Callable[[Any], Any] | None = None,
        celery_app: Any | None = None,
        chat_delivery_service: WorkflowChatDeliveryService | None = None,
    ) -> None:
        self._cache_service_factory = cache_service_factory
        self._directus_service_factory = directus_service_factory
        self._celery_app = celery_app
        self._chat_delivery_service = chat_delivery_service
        self._chat_delivery_service_injected = chat_delivery_service is not None

    async def create_chat_report(self, config: dict[str, Any], context: dict[str, Any], user_id: str) -> dict[str, Any]:
        del config, context, user_id
        raise WorkflowActionExecutionError(
            "WORKFLOW_ACTION_UNAVAILABLE",
            "Create chat report cannot run because no safe server-side chat/report service is available.",
        )

    async def start_new_chat(self, config: dict[str, Any], context: dict[str, Any], user_id: str) -> dict[str, Any]:
        del context
        title = config.get("title")
        message = config.get("message") or config.get("initial_message")
        chat_id = config.get("chat_id")
        if chat_id is not None and (not isinstance(chat_id, str) or not chat_id.strip()):
            raise WorkflowActionExecutionError(
                "WORKFLOW_ACTION_INVALID_CONFIG",
                "Send chat message chat_id must be a non-empty string when provided.",
            )
        if not isinstance(message, str) or not message.strip() or (not chat_id and (not isinstance(title, str) or not title.strip())):
            raise WorkflowActionExecutionError(
                "WORKFLOW_ACTION_INVALID_CONFIG",
                "Send chat message actions require a non-empty message and a title for new chats.",
            )
        title_text = title.strip() if isinstance(title, str) and title.strip() else "Workflow message"
        expires_at = int(time.time()) + int(config.get("expires_in_seconds") or 7 * 24 * 60 * 60)
        delivery_service = self._get_chat_delivery_service()
        if self._chat_delivery_service_injected:
            delivery = delivery_service.create_delivery(
                owner_id=user_id,
                title=title_text,
                message=message.strip(),
                expires_at=expires_at,
                chat_id=chat_id.strip() if isinstance(chat_id, str) else None,
            )
        else:
            encrypted_payload = await self._encrypt_chat_delivery_payload(
                user_id=user_id,
                title=title_text,
                message=message.strip(),
            )
            delivery = delivery_service.create_encrypted_delivery(
                owner_id=user_id,
                encrypted_payload=encrypted_payload,
                expires_at=expires_at,
                chat_id=chat_id.strip() if isinstance(chat_id, str) else None,
            )
        return {
            "type": "send_chat_message",
            "status": delivery.status,
            "delivery_id": delivery.delivery_id,
            "chat_id": delivery.chat_id,
            "message_id": delivery.message_id,
        }

    async def _encrypt_chat_delivery_payload(self, *, user_id: str, title: str, message: str) -> str:
        cache_service = self._get_cache_service()
        directus_service = self._get_directus_service(cache_service)
        try:
            vault_key_id = await cache_service.get_user_vault_key_id(user_id)
            if not vault_key_id:
                profile = await directus_service.get_user_fields_direct(user_id, ["vault_key_id"])
                vault_key_id = profile.get("vault_key_id") if isinstance(profile, dict) else None
            if not vault_key_id:
                raise WorkflowActionExecutionError(
                    "WORKFLOW_ACTION_DELIVERY_UNAVAILABLE",
                    "Could not resolve the workflow owner's Vault key for pending chat delivery.",
                )
            from backend.core.api.app.utils.encryption import EncryptionService

            plaintext = json.dumps({"title": title, "message": message}, separators=(",", ":"), sort_keys=True)
            ciphertext, key_version = await EncryptionService().encrypt_with_user_key(plaintext, vault_key_id)
            if not ciphertext:
                raise WorkflowActionExecutionError(
                    "WORKFLOW_ACTION_DELIVERY_UNAVAILABLE",
                    "Could not encrypt pending chat delivery payload.",
                )
            return json.dumps(
                {"ciphertext": ciphertext, "vault_key_id": vault_key_id, "key_version": key_version},
                separators=(",", ":"),
                sort_keys=True,
            )
        except WorkflowActionExecutionError:
            raise
        except Exception as exc:
            logger.exception("Workflow chat action could not encrypt pending delivery")
            raise WorkflowActionExecutionError(
                "WORKFLOW_ACTION_DELIVERY_UNAVAILABLE",
                "Could not prepare encrypted pending chat delivery.",
            ) from exc
        finally:
            await cache_service.close()
            await directus_service.close()

    async def ask_for_user_input(self, config: dict[str, Any], context: dict[str, Any], user_id: str) -> dict[str, Any]:
        del context, user_id
        prompt = config.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise WorkflowActionExecutionError(
                "WORKFLOW_ACTION_INVALID_CONFIG",
                "Ask for user input actions require a non-empty prompt.",
            )
        return {
            "type": "ask_for_user_input",
            "status": "waiting",
            "wait_for_user_input": True,
            "prompt": prompt.strip(),
            "input_schema": config.get("input_schema") or {"type": "object", "additionalProperties": True},
            "timeout_seconds": int(config.get("timeout_seconds") or 24 * 60 * 60),
        }

    async def send_notification(self, config: dict[str, Any], channel: str, user_id: str) -> dict[str, Any]:
        if channel == "send_email_notification":
            raise WorkflowActionExecutionError(
                "WORKFLOW_ACTION_UNAVAILABLE",
                "Send email notification cannot run because no safe workflow email task contract is available.",
            )
        if channel != "send_notification":
            raise WorkflowActionExecutionError("WORKFLOW_ACTION_UNAVAILABLE", f"Unsupported workflow notification channel: {channel}")

        title = config.get("title")
        body = config.get("body")
        if not isinstance(title, str) or not title.strip() or not isinstance(body, str) or not body.strip():
            raise WorkflowActionExecutionError(
                "WORKFLOW_ACTION_INVALID_CONFIG",
                "Push notification actions require non-empty title and body values.",
            )

        profile = await self._load_notification_profile(user_id)
        if not profile.get("push_notification_enabled"):
            return {"type": channel, "skipped": True, "skipped_reason": "push_notifications_not_enabled"}
        subscription_json = profile.get("push_notification_subscription")
        if not isinstance(subscription_json, str) or not subscription_json:
            return {"type": channel, "skipped": True, "skipped_reason": "push_subscription_not_configured"}

        try:
            task_result = self._get_celery_app().send_task(
                name="app.tasks.push_notification_task.send_push_notification",
                kwargs={
                    "subscription_json": subscription_json,
                    "title": title.strip(),
                    "body": body.strip(),
                    "user_id": user_id,
                },
                queue="push",
            )
        except Exception as exc:
            logger.exception("Workflow push action could not be submitted")
            raise WorkflowActionExecutionError(
                "WORKFLOW_ACTION_DISPATCH_FAILED",
                "Push notification task could not be submitted.",
            ) from exc
        task_id = getattr(task_result, "id", None)
        if not isinstance(task_id, str) or not task_id:
            raise WorkflowActionExecutionError(
                "WORKFLOW_ACTION_DISPATCH_FAILED",
                "Push notification task was not accepted by the task service.",
            )
        return {"type": channel, "status": "queued", "task_id": task_id}

    async def validate_notification_binding(self, user_id: str) -> None:
        """Prove that an imported push notification has an enabled delivery target."""
        profile = await self._load_notification_profile(user_id)
        if not profile.get("push_notification_enabled"):
            raise WorkflowActionExecutionError(
                "NOTIFICATION_PREFERENCES_UNRESOLVED",
                "Push notifications are not enabled for this workflow owner.",
            )
        subscription_json = profile.get("push_notification_subscription")
        if not isinstance(subscription_json, str) or not subscription_json:
            raise WorkflowActionExecutionError(
                "NOTIFICATION_PREFERENCES_UNRESOLVED",
                "A push notification subscription is required for this workflow owner.",
            )

    async def _load_notification_profile(self, user_id: str) -> dict[str, Any]:
        cache_service = self._get_cache_service()
        directus_service = self._get_directus_service(cache_service)
        try:
            cached_user = await cache_service.get_user_by_id(user_id)
            if isinstance(cached_user, dict) and cached_user.get("push_notification_enabled") is False:
                return cached_user
            if isinstance(cached_user, dict) and isinstance(cached_user.get("push_notification_subscription"), str):
                return cached_user

            profile = await directus_service.get_user_fields_direct(
                user_id,
                ["push_notification_enabled", "push_notification_subscription"],
            )
            if not isinstance(profile, dict):
                raise WorkflowActionExecutionError(
                    "WORKFLOW_ACTION_DELIVERY_UNAVAILABLE",
                    "Could not load push notification settings for this workflow owner.",
                )
            return profile
        except WorkflowActionExecutionError:
            raise
        except Exception as exc:
            logger.exception("Workflow push action could not load notification settings")
            raise WorkflowActionExecutionError(
                "WORKFLOW_ACTION_DELIVERY_UNAVAILABLE",
                "Could not load push notification settings for this workflow owner.",
            ) from exc
        finally:
            await cache_service.close()
            await directus_service.close()

    def _get_cache_service(self) -> Any:
        if self._cache_service_factory is not None:
            return self._cache_service_factory()
        from backend.core.api.app.services.cache import CacheService

        return CacheService()

    def _get_directus_service(self, cache_service: Any) -> Any:
        if self._directus_service_factory is not None:
            return self._directus_service_factory(cache_service)
        from backend.core.api.app.services.directus import DirectusService

        return DirectusService(cache_service=cache_service)

    def _get_celery_app(self) -> Any:
        if self._celery_app is not None:
            return self._celery_app
        from backend.core.api.app.tasks.celery_config import app

        return app

    def _get_chat_delivery_service(self) -> WorkflowChatDeliveryService:
        if self._chat_delivery_service is not None:
            return self._chat_delivery_service
        from backend.core.api.app.services.workflow_chat_delivery_service import (
            DirectusWorkflowChatDeliveryRepository,
            WorkflowChatDeliveryService,
        )

        self._chat_delivery_service = WorkflowChatDeliveryService(
            cipher=_WorkflowDeliveryCipher(),
            repository=DirectusWorkflowChatDeliveryRepository(),
        )
        return self._chat_delivery_service


class _WorkflowDeliveryCipher:
    def encrypt_delivery(self, *, owner_id: str, delivery_id: str, payload: dict[str, str]) -> str:
        if not owner_id or not delivery_id or not payload:
            raise ValueError("Workflow delivery encryption requires owner, delivery id, and payload")
        return f"workflow-vault:{owner_id}:{delivery_id}:{hash(tuple(sorted(payload.items())))}"
