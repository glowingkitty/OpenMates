# backend/tests/test_workflow_action_adapter.py
#
# Focused contracts for real Workflows V1 platform-action dispatch. These tests
# ensure the runner records actual push task submission without exposing stored
# subscriptions and rejects actions that do not have a safe server-side service.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import json

import pytest

from backend.core.api.app.services.workflow_action_adapter import (
    WorkflowActionAdapter,
    WorkflowActionExecutionError,
)
from backend.core.api.app.services.workflow_chat_delivery_service import WorkflowChatDeliveryService


class _TaskResult:
    id = "push-task-1"


class _CeleryApp:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send_task(self, **kwargs: object) -> _TaskResult:
        self.calls.append(kwargs)
        return _TaskResult()


class _FailingCeleryApp:
    def send_task(self, **kwargs: object) -> _TaskResult:
        del kwargs
        raise RuntimeError("broker unavailable")


class _CacheService:
    def __init__(self, user: dict | None) -> None:
        self.user = user
        self.closed = False

    async def get_user_by_id(self, user_id: str) -> dict | None:
        assert user_id == "alice"
        return self.user

    async def close(self) -> None:
        self.closed = True


class _PublishingCacheService(_CacheService):
    def __init__(self) -> None:
        super().__init__(None)
        self.redis = _PublishingRedis()

    @property
    async def client(self) -> "_PublishingRedis":
        return self.redis


class _PublishingRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))


class _FakeDeliveryCipher:
    def encrypt_delivery(self, *, owner_id: str, delivery_id: str, payload: dict[str, str]) -> str:
        del payload
        return f"ciphertext:{owner_id}:{delivery_id}"


class _DirectusService:
    def __init__(self, user: dict | None) -> None:
        self.user = user
        self.calls: list[tuple[str, list[str]]] = []
        self.closed = False

    async def get_user_fields_direct(self, user_id: str, fields: list[str]) -> dict | None:
        self.calls.append((user_id, fields))
        return self.user

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_push_action_falls_back_to_directus_and_queues_existing_push_task() -> None:
    cache = _CacheService(None)
    directus = _DirectusService(
        {
            "push_notification_enabled": True,
            "push_notification_subscription": '{"endpoint":"https://push.example/subscription"}',
        }
    )
    celery = _CeleryApp()
    adapter = WorkflowActionAdapter(
        cache_service_factory=lambda: cache,
        directus_service_factory=lambda _: directus,
        celery_app=celery,
    )

    result = await adapter.send_notification(
        {"title": "Rain today", "body": "Take an umbrella."},
        "send_notification",
        "alice",
    )

    assert result == {
        "type": "send_notification",
        "status": "queued",
        "task_id": "push-task-1",
    }
    assert directus.calls == [
        ("alice", ["push_notification_enabled", "push_notification_subscription"])
    ]
    assert celery.calls == [
        {
            "name": "app.tasks.push_notification_task.send_push_notification",
            "kwargs": {
                "subscription_json": '{"endpoint":"https://push.example/subscription"}',
                "title": "Rain today",
                "body": "Take an umbrella.",
                "user_id": "alice",
            },
            "queue": "push",
        }
    ]
    assert cache.closed is True
    assert directus.closed is True


@pytest.mark.anyio
async def test_push_action_records_a_visible_skip_when_owner_has_no_subscription() -> None:
    cache = _CacheService({"push_notification_enabled": False})
    directus = _DirectusService(None)
    celery = _CeleryApp()
    adapter = WorkflowActionAdapter(
        cache_service_factory=lambda: cache,
        directus_service_factory=lambda _: directus,
        celery_app=celery,
    )

    result = await adapter.send_notification(
        {"title": "Rain today", "body": "Take an umbrella."},
        "send_notification",
        "alice",
    )

    assert result == {
        "type": "send_notification",
        "skipped": True,
        "skipped_reason": "push_notifications_not_enabled",
    }
    assert celery.calls == []
    assert directus.calls == []


@pytest.mark.anyio
async def test_notification_binding_requires_an_enabled_push_subscription() -> None:
    adapter = WorkflowActionAdapter(
        cache_service_factory=lambda: _CacheService(
            {
                "push_notification_enabled": True,
                "push_notification_subscription": '{"endpoint":"https://push.example/subscription"}',
            }
        ),
        directus_service_factory=lambda _: _DirectusService(None),
    )

    await adapter.validate_notification_binding("alice")

    unresolved = WorkflowActionAdapter(
        cache_service_factory=lambda: _CacheService({"push_notification_enabled": False}),
        directus_service_factory=lambda _: _DirectusService(None),
    )
    with pytest.raises(WorkflowActionExecutionError) as exc_info:
        await unresolved.validate_notification_binding("alice")

    assert exc_info.value.code == "NOTIFICATION_PREFERENCES_UNRESOLVED"


@pytest.mark.anyio
@pytest.mark.parametrize("method_name", ["create_chat_report"])
async def test_chat_actions_fail_when_no_safe_server_side_contract_exists(method_name: str) -> None:
    adapter = WorkflowActionAdapter()

    with pytest.raises(WorkflowActionExecutionError) as exc_info:
        await getattr(adapter, method_name)({}, {}, "alice")

    assert exc_info.value.code == "WORKFLOW_ACTION_UNAVAILABLE"


@pytest.mark.anyio
async def test_start_new_chat_requires_message_and_title_or_existing_chat_id() -> None:
    adapter = WorkflowActionAdapter()

    with pytest.raises(WorkflowActionExecutionError) as exc_info:
        await adapter.start_new_chat({}, {}, "alice")

    assert exc_info.value.code == "WORKFLOW_ACTION_INVALID_CONFIG"


@pytest.mark.anyio
async def test_start_new_chat_publishes_pending_delivery_to_connected_clients() -> None:
    cache = _PublishingCacheService()
    delivery_service = WorkflowChatDeliveryService(cipher=_FakeDeliveryCipher(), clock=lambda: 100)
    adapter = WorkflowActionAdapter(
        cache_service_factory=lambda: cache,
        chat_delivery_service=delivery_service,
    )

    result = await adapter.start_new_chat(
        {"title": "Workflow output", "message": "Rain is likely.", "expires_in_seconds": 100},
        {},
        "alice",
    )

    assert result["status"] == "delivery_pending"
    assert cache.closed is True
    assert len(cache.redis.published) == 1
    channel, published = cache.redis.published[0]
    assert channel == (
        "websocket:user:"
        "2bd806c97f0e00af1a1fc3328fa763a9269723c8db8fac4f93af71db186d6e90"
    )
    event = json.loads(published)
    assert event["event_for_client"] == "workflow_chat_deliveries_available"
    assert event["payload"]["user_id"] == "alice"
    delivery = event["payload"]["deliveries"][0]
    assert delivery["delivery_id"] == result["delivery_id"]
    assert delivery["encrypted_payload"].startswith("ciphertext:alice:")


@pytest.mark.anyio
async def test_email_action_fails_when_no_safe_workflow_email_contract_exists() -> None:
    adapter = WorkflowActionAdapter()

    with pytest.raises(WorkflowActionExecutionError) as exc_info:
        await adapter.send_notification({"title": "Rain", "body": "Umbrella"}, "send_email_notification", "alice")

    assert exc_info.value.code == "WORKFLOW_ACTION_UNAVAILABLE"


@pytest.mark.anyio
async def test_push_dispatch_failure_is_a_typed_visible_execution_error() -> None:
    cache = _CacheService(
        {
            "push_notification_enabled": True,
            "push_notification_subscription": '{"endpoint":"https://push.example/subscription"}',
        }
    )
    adapter = WorkflowActionAdapter(
        cache_service_factory=lambda: cache,
        directus_service_factory=lambda _: _DirectusService(None),
        celery_app=_FailingCeleryApp(),
    )

    with pytest.raises(WorkflowActionExecutionError) as exc_info:
        await adapter.send_notification({"title": "Rain", "body": "Umbrella"}, "send_notification", "alice")

    assert exc_info.value.code == "WORKFLOW_ACTION_DISPATCH_FAILED"
