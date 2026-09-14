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

from backend.core.api.app.services.workflow_chat_delivery_service import (
    WorkflowChatDelivery,
    WorkflowChatDeliveryService,
)


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
        workflow_service: Any | None = None,
    ) -> None:
        self._workflow_service = workflow_service
        self._cache_service_factory = cache_service_factory
        self._directus_service_factory = directus_service_factory
        self._celery_app = celery_app
        self._chat_delivery_service = chat_delivery_service
        self._chat_delivery_service_injected = chat_delivery_service is not None

    async def preview_message(self, config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Render authored output selections without reservation, persistence or delivery."""
        from backend.core.api.app.services.workflow_template_expressions import resolve_workflow_template
        title = resolve_workflow_template(config.get("title") or "Workflow results", context)
        message = resolve_workflow_template(config.get("message") or "", context)
        if not isinstance(title, str) or not isinstance(message, str):
            raise WorkflowActionExecutionError("WORKFLOW_ACTION_INVALID_CONFIG", "Message title and text must resolve to text")
        blocks = []
        for index, block in enumerate(config.get("blocks") or []):
            condition = block.get("include_if")
            if condition is not None:
                include = resolve_workflow_template(condition, context)
                if not isinstance(include, bool):
                    raise WorkflowActionExecutionError("WORKFLOW_ACTION_INVALID_CONFIG", "Optional message blocks require a boolean Check output")
                if not include:
                    continue
            value = resolve_workflow_template(block["source"], context)
            if value is None:
                raise WorkflowActionExecutionError("WORKFLOW_ACTION_INVALID_CONFIG", "Selected message output is unavailable")
            if block.get("only_new_results") and (not isinstance(value, list) or any(not isinstance(item, dict) for item in value)):
                raise WorkflowActionExecutionError("WORKFLOW_ACTION_INVALID_CONFIG", "Only new results requires a selected result list")
            blocks.append({"id": block.get("id") or str(index), "source": block["source"],
                           "label": block.get("label") or "", "value": value,
                           "only_new_results": bool(block.get("only_new_results"))})
        return {"title": title, "message": message, "blocks": blocks,
                "text": self._render_message(message, blocks), "dispatches": False}

    @staticmethod
    def _render_message(message: str, blocks: list[dict[str, Any]]) -> str:
        def render(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, bool):
                return "Yes" if value else "No"
            if isinstance(value, dict):
                # Retain typed source data in embeds; this deterministic text is also
                # readable by every client without inventing an AI interpretation.
                title = value.get("title") or value.get("name")
                url = value.get("url") or value.get("link") or value.get("source_url")
                if title:
                    summary = value.get("description") or value.get("summary") or ""
                    details = [str(value[key]) for key in ("date_start", "date_end", "location", "price_label", "rooms", "address") if value.get(key) is not None]
                    return "\n".join(str(item) for item in [title, summary, *details, url] if item).strip()
                return "\n".join(f"{key.replace('_', ' ').capitalize()}: {render(item)}" for key, item in value.items() if item is not None)
            if isinstance(value, list):
                return "\n\n".join(render(item) for item in value)
            return str(value)
        sections = [message.strip()] if message.strip() else []
        for block in blocks:
            content = render(block["value"])
            if content:
                sections.append((f"{block['label']}\n" if block.get("label") else "") + content)
        return "\n\n".join(sections)

    async def send_chat_message(self, config: dict[str, Any], context: dict[str, Any], user_id: str) -> dict[str, Any]:
        import uuid
        from starlette.concurrency import run_in_threadpool
        from backend.core.api.app.services.workflow_delivery_history import WorkflowDeliveryHistory, canonical_result_identity, keyed_fingerprint
        execution = context.get("workflow") or {}
        workflow_id, run_id, node_id = (execution.get(key) for key in ("workflow_id", "run_id", "node_id"))
        if not all((workflow_id, run_id, node_id)) or execution.get("step_test"):
            raise WorkflowActionExecutionError("WORKFLOW_ACTION_INVALID_CONTEXT", "Message delivery requires a full workflow run")
        preview = await self.preview_message(config, context)
        delivery_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"openmates:workflow:{run_id}:{node_id}:delivery"))
        chat_id = config.get("chat_id") or str(uuid.uuid5(uuid.NAMESPACE_URL, f"openmates:workflow:{run_id}:{node_id}:chat"))
        message_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"openmates:workflow:{run_id}:{node_id}:message"))
        expires_at = int(time.time()) + min(int(config.get("expires_in_seconds") or 7 * 86400), 7 * 86400)
        if self._workflow_service is None:
            raise WorkflowActionExecutionError("WORKFLOW_ACTION_DELIVERY_UNAVAILABLE", "Workflow result history is unavailable")
        history = WorkflowDeliveryHistory(self._workflow_service)
        key = await run_in_threadpool(history.key, workflow_id, user_id)
        destination = keyed_fingerprint(key, f"destination:v1:{node_id}:" + (f"chat:{config['chat_id']}" if config.get("chat_id") else "new-chat"))
        candidates, candidate_values = [], []
        for block_index, block in enumerate(preview["blocks"]):
            value = block["value"]
            if not isinstance(value, list):
                continue
            for item_index, item in enumerate(value):
                if not isinstance(item, dict):
                    continue
                try:
                    identity = canonical_result_identity(item)
                except Exception:
                    if block["only_new_results"]:
                        raise WorkflowActionExecutionError("WORKFLOW_RESULT_IDENTITY_MISSING", "Only new results requires a provider ID or URL on each selected result")
                    # Weather periods and non-result typed objects do not acquire result membership.
                    continue
                fingerprint = keyed_fingerprint(key, identity)
                candidates.append({"index": len(candidates), "fingerprint": fingerprint, "only_new": block["only_new_results"]})
                candidate_values.append((block_index, item_index, item, fingerprint))
        selected = set(await run_in_threadpool(history.reserve, user_id=user_id, workflow_id=workflow_id,
            run_id=run_id, node_id=node_id, delivery_id=delivery_id, destination_hash=destination,
            candidates=candidates, expires_at=expires_at))
        keep = {(candidate_values[i][0], candidate_values[i][1]) for i in selected}
        considered = {(b, i) for b, i, _, _ in candidate_values}
        blocks = []
        for b, block in enumerate(preview["blocks"]):
            block = dict(block)
            if isinstance(block["value"], list):
                block["value"] = [item for i, item in enumerate(block["value"]) if (b, i) not in considered or (b, i) in keep]
            blocks.append(block)
        text = self._render_message(preview["message"], blocks)
        # A header alone should not produce an empty new chat after list deduplication.
        has_content = any(block["value"] not in (None, [], {}, "") for block in blocks) if config.get("blocks") else bool(preview["message"].strip())
        if not has_content:
            await run_in_threadpool(history.release, delivery_id, workflow_id, user_id)
            return {"type": "send_chat_message", "status": "no_new_results", "message": "No new results", "selected_count": 0}
        embeds = []
        for i in sorted(selected):
            b, _, item, fingerprint = candidate_values[i]
            source = blocks[b]["source"]
            source_node = source.split(".")[1] if source.startswith("$nodes.") else ""
            app_id = (context.get("nodes", {}).get(source_node) or {}).get("app_id")
            content_type = {"news": "website", "events": "event", "home": "listing"}.get(app_id, "workflow-result")
            embeds.append({"embed_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{delivery_id}:embed:{fingerprint}")),
                           "content_type": content_type, "content": item})
        text += f"\n\n[View workflow run](/workflows#workflow-id={workflow_id}&workflow-tab=runs&run-id={run_id})"
        for embed in embeds:
            text += "\n\n```json\n" + json.dumps({"type": embed["content_type"], "embed_id": embed["embed_id"]}, separators=(",", ":")) + "\n```"
        delivery_service = self._get_chat_delivery_service()
        if self._chat_delivery_service_injected:
            delivery_service._delivery_history = history
            self._workflow_service.repository._workflow_deliveries = delivery_service._repository
        kwargs = dict(owner_id=user_id, expires_at=expires_at, chat_id=chat_id, delivery_id=delivery_id,
                      message_id=message_id, workflow_id=workflow_id, run_id=run_id, node_id=node_id)
        try:
            if self._chat_delivery_service_injected:
                delivery = delivery_service.create_delivery(title=preview["title"], message=text, embeds=embeds, **kwargs)
            else:
                encrypted = await self._encrypt_chat_delivery_payload(user_id=user_id, title=preview["title"], message=text, embeds=embeds)
                delivery = await run_in_threadpool(delivery_service.create_encrypted_delivery, encrypted_payload=encrypted, **kwargs)
        except Exception:
            # An uncertain persistence response might have committed the delivery; keep
            # its reservation until retry/expiry instead of enabling a duplicate send.
            raise
        if not self._chat_delivery_service_injected or self._cache_service_factory is not None:
            await self._publish_workflow_chat_delivery_available(user_id=user_id, delivery=delivery)
        return {"type": "send_chat_message", "status": delivery.status, "delivery_id": delivery.delivery_id,
                "chat_id": delivery.chat_id, "message_id": delivery.message_id, "selected_count": len(selected),
                "embed_ids": [embed["embed_id"] for embed in embeds]}

    async def create_chat_report(self, config: dict[str, Any], context: dict[str, Any], user_id: str) -> dict[str, Any]:
        summary = config.get("summary") or config.get("message")
        title = config.get("title") or "Workflow report"
        if not isinstance(summary, str) or not summary.strip() or not isinstance(title, str) or not title.strip():
            raise WorkflowActionExecutionError(
                "WORKFLOW_ACTION_INVALID_CONFIG",
                "Create chat report actions require non-empty title and summary values.",
            )

        delivery = await self.start_new_chat(
            {
                "title": title.strip(),
                "message": summary.strip(),
                "expires_in_seconds": config.get("expires_in_seconds") or 7 * 24 * 60 * 60,
            },
            context,
            user_id,
        )
        delivery["type"] = "create_chat_report"
        delivery["summary"] = summary.strip()
        delivery["report_id"] = delivery.get("delivery_id")
        return delivery

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
        should_publish_delivery = not self._chat_delivery_service_injected or self._cache_service_factory is not None
        if should_publish_delivery:
            await self._publish_workflow_chat_delivery_available(user_id=user_id, delivery=delivery)
        return {
            "type": "send_chat_message",
            "status": delivery.status,
            "delivery_id": delivery.delivery_id,
            "chat_id": delivery.chat_id,
            "message_id": delivery.message_id,
        }

    async def _encrypt_chat_delivery_payload(self, *, user_id: str, title: str, message: str, embeds: list[dict[str, Any]] | None = None) -> str:
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

            plaintext = json.dumps({"title": title, "message": message, "embeds": embeds or []}, separators=(",", ":"), sort_keys=True)
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

    async def _publish_workflow_chat_delivery_available(self, *, user_id: str, delivery: WorkflowChatDelivery) -> None:
        cache_service = self._get_cache_service()
        try:
            client = await cache_service.client
            if not client:
                logger.warning("Workflow chat delivery event could not be published: cache client unavailable")
                return
            if not delivery.owner_hash:
                logger.warning("Workflow chat delivery event could not be published: owner hash missing")
                return
            payload = {
                "event": "workflow_chat_deliveries_available",
                "type": "workflow_chat_deliveries_available",
                "event_for_client": "workflow_chat_deliveries_available",
                "payload": {
                    "user_id": user_id,
                    "deliveries": [
                        {
                            "delivery_id": delivery.delivery_id,
                            "chat_id": delivery.chat_id,
                            "message_id": delivery.message_id,
                            "status": delivery.status,
                            "encrypted_payload": delivery.encrypted_payload,
                            "created_at": delivery.created_at,
                            "expires_at": delivery.expires_at,
                            "claim_generation": delivery.claim_generation,
                        }
                    ],
                },
            }
            await client.publish(
                f"websocket:user:{delivery.owner_hash}",
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
            )
        except Exception:
            logger.exception("Workflow chat delivery event publish failed")
        finally:
            await cache_service.close()

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
