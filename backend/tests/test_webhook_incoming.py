# backend/tests/test_webhook_incoming.py
#
# Integration tests for the incoming webhook endpoint and the AI dispatch helper.
#
# Coverage:
#   - Default path: chat is pre-created in Directus, plaintext is broadcast over
#     the WebSocket, the AI ask-skill is dispatched, response carries the
#     processing status.
#   - Offline path: when no device is live, an email notification is queued
#     instead of (in addition to) the WS broadcast.
#   - require_confirmation path: AI dispatch is skipped, response status is
#     "pending_confirmation".
#   - Vault encryption failure short-circuits with HTTP 500.
#
# These complement test_webhook_auth.py (which only covers the auth service).
# Run: python -m pytest backend/tests/test_webhook_incoming.py -v

import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# webhook_incoming imports `routes.websockets` and `tasks.celery_config` lazily
# inside the function body. Both pull in payment_service → polar_sdk, which may
# or may not be installed depending on the env. Force the lazy imports to
# resolve to lightweight stubs in sys.modules so tests get the same fake
# manager / celery app regardless of whether the real modules would have loaded.

_FAKE_WS_MANAGER = MagicMock(name="fake_ws_manager")
_FAKE_WS_MANAGER.is_user_active = MagicMock(return_value=True)
_FAKE_WS_MANAGER.broadcast_to_user = AsyncMock()

_FAKE_CELERY_APP = MagicMock(name="fake_celery_app")
_FAKE_CELERY_APP.send_task = MagicMock()


def _force_stub_leaf_module(dotted_name: str, **attrs) -> types.ModuleType:
    """Force-replace the leaf module in sys.modules with a stub.

    Works in both environments:
      - Local dev: the real parent package may fail to import (e.g.
        backend.core.api.app.tasks.__init__ pulls in polar_sdk via the email
        task chain). Fall back to a minimal stub parent so the lazy
        `from x.y.z import w` inside webhook_incoming still finds something.
      - CI / production: the real parent imports cleanly. We still replace the
        leaf so tests get a deterministic fake manager / celery app instead of
        whatever the real package put in sys.modules.

    We never touch parent packages that already exist — that would shadow real
    sibling submodules (e.g. `routers` would become unreachable if we replaced
    `backend.core.api.app` itself).
    """
    parent_name, _, leaf = dotted_name.rpartition(".")
    if parent_name not in sys.modules:
        try:
            __import__(parent_name)
        except Exception:
            stub_parent = types.ModuleType(parent_name)
            stub_parent.__path__ = []
            sys.modules[parent_name] = stub_parent
    parent = sys.modules[parent_name]
    stub = types.ModuleType(dotted_name)
    for key, value in attrs.items():
        setattr(stub, key, value)
    sys.modules[dotted_name] = stub
    setattr(parent, leaf, stub)
    return stub


_force_stub_leaf_module(
    "backend.core.api.app.routes.websockets",
    manager=_FAKE_WS_MANAGER,
)
_force_stub_leaf_module(
    "backend.core.api.app.tasks.celery_config",
    app=_FAKE_CELERY_APP,
)

try:
    from backend.core.api.app.routers.webhooks import (
        webhook_incoming,
        _dispatch_webhook_ai_request,
        WebhookIncomingRequest,
        WEBHOOK_TASK_TEMPLATE,
        PENDING_WEBHOOK_CHAT_TTL,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(cache_service, encryption_service, directus_service):
    """Build a fake FastAPI Request object with the bits webhook_incoming + slowapi poke at.

    slowapi's @limiter.limit decorator inspects request.client and request.scope
    to extract a client identifier; the rest of the body uses request.app.state.
    """
    state = SimpleNamespace(
        cache_service=cache_service,
        encryption_service=encryption_service,
        directus_service=directus_service,
    )
    app = SimpleNamespace(state=state)
    request = SimpleNamespace(
        app=app,
        client=SimpleNamespace(host="127.0.0.1", port=0),
        scope={
            "type": "http",
            "method": "POST",
            "path": "/v1/webhooks/incoming",
            "client": ("127.0.0.1", 0),
            "headers": [],
        },
        headers={},
    )
    return request


def _make_webhook_info(require_confirmation: bool = False):
    return {
        "webhook_id": "wh_test_id",
        "user_id": "user_test_id",
        "hashed_user_id": "hashed_user_test_id",
        "require_confirmation": require_confirmation,
        "permissions": ["trigger_chat"],
        "key_hash": "fake_hash",
    }


def _make_cache_service(user_online: bool = True):
    cache = AsyncMock()
    cache.get_user_by_id = AsyncMock(return_value={"vault_key_id": "vk_test"})
    cache.set = AsyncMock()
    cache.delete = AsyncMock()
    cache.add_chat_to_ids_versions = AsyncMock()
    cache.get_user_timezone = AsyncMock(return_value="UTC")
    cache.set_active_ai_task = AsyncMock()
    return cache


def _make_directus_service():
    directus = AsyncMock()
    chat_methods = AsyncMock()
    chat_methods.create_chat_in_directus = AsyncMock(
        return_value=({"chat_id": "stub"}, False)
    )
    directus.chat = chat_methods
    return directus


def _make_encryption_service(succeed: bool = True):
    enc = AsyncMock()
    if succeed:
        enc.encrypt_with_user_key = AsyncMock(
            return_value=("vault_encrypted_blob", "v1")
        )
    else:
        enc.encrypt_with_user_key = AsyncMock(side_effect=Exception("vault down"))
    return enc


# ---------------------------------------------------------------------------
# Default path — online user, no confirmation required
# ---------------------------------------------------------------------------

def _reset_stubs(user_online: bool = True):
    """Reset the WS manager + celery stubs between tests so call counts don't leak."""
    _FAKE_WS_MANAGER.is_user_active.reset_mock()
    _FAKE_WS_MANAGER.is_user_active.return_value = user_online
    _FAKE_WS_MANAGER.broadcast_to_user.reset_mock()
    _FAKE_CELERY_APP.send_task.reset_mock()


@pytest.mark.asyncio
async def test_webhook_incoming_default_path_dispatches_ai_and_broadcasts():
    _reset_stubs(user_online=True)
    cache = _make_cache_service()
    enc = _make_encryption_service()
    directus = _make_directus_service()
    request = _make_request(cache, enc, directus)
    payload = WebhookIncomingRequest(message="Build failed on main")
    webhook_info = _make_webhook_info(require_confirmation=False)

    fake_registry = MagicMock()
    fake_registry.dispatch_skill = AsyncMock(return_value={"task_id": "ai_task_123"})

    with patch(
        "backend.core.api.app.services.skill_registry.get_global_registry",
        return_value=fake_registry,
    ):
        response = await webhook_incoming.__wrapped__(
            request=request,
            payload=payload,
            webhook_info=webhook_info,
        )

    # Response shape
    assert response.status == "processing"
    assert response.chat_id  # uuid set

    # Chat pre-created in Directus
    directus.chat.create_chat_in_directus.assert_awaited_once()
    minimal = directus.chat.create_chat_in_directus.await_args.args[0]
    assert minimal["hashed_user_id"] == "hashed_user_test_id"
    assert minimal["title_v"] == 0
    assert minimal["unread_count"] == 1

    # chat_ids_versions sorted set updated
    cache.add_chat_to_ids_versions.assert_awaited_once()

    # Vault-encrypted offline copy cached
    cache.set.assert_awaited_once()
    pending_key, raw_value = cache.set.await_args.args[0], cache.set.await_args.args[1]
    assert pending_key.startswith("webhook_pending_chat:user_test_id:")
    cached_record = json.loads(raw_value)
    assert cached_record["role"] == "system"
    assert cached_record["source"] == "webhook"
    assert cached_record["encrypted_content"] == "vault_encrypted_blob"
    assert cache.set.await_args.kwargs.get("ttl") == PENDING_WEBHOOK_CHAT_TTL

    # WebSocket broadcast carries PLAINTEXT content (mirrors reminder_fired)
    _FAKE_WS_MANAGER.broadcast_to_user.assert_awaited_once()
    broadcast_kwargs = _FAKE_WS_MANAGER.broadcast_to_user.await_args.kwargs
    msg = broadcast_kwargs["message"]
    assert msg["type"] == "webhook_chat"
    assert msg["payload"]["content"] == "Build failed on main"
    assert msg["payload"]["status"] == "processing"
    assert msg["payload"]["source"] == "webhook"

    # AI dispatch was called with the wrapped task template
    fake_registry.dispatch_skill.assert_awaited_once()
    args = fake_registry.dispatch_skill.await_args.args
    assert args[0] == "ai"
    assert args[1] == "ask"
    ask_request = args[2]
    assert ask_request["chat_id"] == response.chat_id
    assert ask_request["chat_has_title"] is False
    assert len(ask_request["message_history"]) == 1
    user_turn = ask_request["message_history"][0]
    assert user_turn["role"] == "user"
    assert "Build failed on main" in user_turn["content"]
    assert "[Incoming Webhook" in user_turn["content"]

    # Active AI task tracked in cache
    cache.set_active_ai_task.assert_awaited_once_with(response.chat_id, "ai_task_123")


# ---------------------------------------------------------------------------
# Offline user — queues email instead of WS broadcast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_incoming_offline_user_queues_email_and_still_dispatches_ai():
    _reset_stubs(user_online=False)
    cache = _make_cache_service()
    cache.get_user_by_id = AsyncMock(return_value={
        "vault_key_id": "vk_test",
        "email_notifications_enabled": True,
        "encrypted_notification_email": "enc_email",
        "language": "en",
        "darkmode": False,
        "email_notification_preferences": {"webhookChats": True},
    })
    enc = _make_encryption_service()
    directus = _make_directus_service()
    request = _make_request(cache, enc, directus)
    payload = WebhookIncomingRequest(message="Cron heartbeat")
    webhook_info = _make_webhook_info(require_confirmation=False)

    fake_registry = MagicMock()
    fake_registry.dispatch_skill = AsyncMock(return_value={"task_id": "ai_task_offline"})

    with patch(
        "backend.core.api.app.services.skill_registry.get_global_registry",
        return_value=fake_registry,
    ):
        response = await webhook_incoming.__wrapped__(
            request=request,
            payload=payload,
            webhook_info=webhook_info,
        )

    assert response.status == "processing"

    # No live WS broadcast went out
    _FAKE_WS_MANAGER.broadcast_to_user.assert_not_called()

    # Email Celery task queued instead
    _FAKE_CELERY_APP.send_task.assert_called_once()
    call_kwargs = _FAKE_CELERY_APP.send_task.call_args.kwargs
    assert "send_webhook_chat_notification" in call_kwargs["name"]
    assert call_kwargs["queue"] == "email"
    assert call_kwargs["kwargs"]["chat_id"] == response.chat_id

    # AI is still dispatched even though no device is online — server-side
    # processing must run regardless of presence (matches reminder semantics).
    fake_registry.dispatch_skill.assert_awaited_once()


# ---------------------------------------------------------------------------
# require_confirmation — AI dispatch is skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_incoming_require_confirmation_skips_ai_dispatch():
    _reset_stubs(user_online=True)
    cache = _make_cache_service()
    enc = _make_encryption_service()
    directus = _make_directus_service()
    request = _make_request(cache, enc, directus)
    payload = WebhookIncomingRequest(message="needs approval")
    webhook_info = _make_webhook_info(require_confirmation=True)

    fake_registry = MagicMock()
    fake_registry.dispatch_skill = AsyncMock()

    with patch(
        "backend.core.api.app.services.skill_registry.get_global_registry",
        return_value=fake_registry,
    ):
        response = await webhook_incoming.__wrapped__(
            request=request,
            payload=payload,
            webhook_info=webhook_info,
        )

    assert response.status == "pending_confirmation"
    _FAKE_WS_MANAGER.broadcast_to_user.assert_awaited_once()
    broadcast_msg = _FAKE_WS_MANAGER.broadcast_to_user.await_args.kwargs["message"]
    assert broadcast_msg["payload"]["status"] == "pending_confirmation"

    # AI must NOT be dispatched while the chat is awaiting approval
    fake_registry.dispatch_skill.assert_not_called()
    cache.set_active_ai_task.assert_not_called()


# ---------------------------------------------------------------------------
# Vault encryption failure short-circuits with HTTP 500
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_incoming_vault_encryption_failure_returns_500():
    from fastapi import HTTPException

    _reset_stubs(user_online=True)
    cache = _make_cache_service()
    enc = _make_encryption_service(succeed=False)
    directus = _make_directus_service()
    request = _make_request(cache, enc, directus)
    payload = WebhookIncomingRequest(message="will fail")
    webhook_info = _make_webhook_info()

    with pytest.raises(HTTPException) as exc_info:
        await webhook_incoming.__wrapped__(
            request=request,
            payload=payload,
            webhook_info=webhook_info,
        )

    assert exc_info.value.status_code == 500
    assert "Encryption failed" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# _dispatch_webhook_ai_request helper directly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_webhook_ai_request_builds_wrapped_user_turn():
    cache = _make_cache_service()
    fake_registry = MagicMock()
    fake_registry.dispatch_skill = AsyncMock(return_value={"task_id": "tk1"})

    with patch(
        "backend.core.api.app.services.skill_registry.get_global_registry",
        return_value=fake_registry,
    ):
        await _dispatch_webhook_ai_request(
            user_id="u1",
            chat_id="c1",
            message_id="m1",
            message="hello world",
            cache_service=cache,
        )

    fake_registry.dispatch_skill.assert_awaited_once()
    args = fake_registry.dispatch_skill.await_args.args
    assert args[0] == "ai"
    assert args[1] == "ask"
    ask_request = args[2]
    assert ask_request["chat_id"] == "c1"
    assert ask_request["message_id"] == "m1"
    assert ask_request["chat_has_title"] is False
    assert len(ask_request["message_history"]) == 1
    assert "hello world" in ask_request["message_history"][0]["content"]
    assert ask_request["user_preferences"].get("timezone") == "UTC"
    cache.set_active_ai_task.assert_awaited_once_with("c1", "tk1")


@pytest.mark.asyncio
async def test_dispatch_webhook_ai_request_warns_on_missing_task_id():
    cache = _make_cache_service()
    fake_registry = MagicMock()
    fake_registry.dispatch_skill = AsyncMock(return_value={})  # no task_id

    with patch(
        "backend.core.api.app.services.skill_registry.get_global_registry",
        return_value=fake_registry,
    ):
        await _dispatch_webhook_ai_request(
            user_id="u1",
            chat_id="c1",
            message_id="m1",
            message="hi",
            cache_service=cache,
        )

    cache.set_active_ai_task.assert_not_called()


def test_webhook_task_template_contains_marker():
    rendered = WEBHOOK_TASK_TEMPLATE.format(message="do the thing")
    assert "[Incoming Webhook" in rendered
    assert "do the thing" in rendered
