"""Synthetic completion-to-push coverage without provider or worker bootstrap.

Execute the complete production notification coroutine with its dispatch
boundaries substituted. Socket visibility/recovery use the real manager.
"""

import ast
import asyncio
import logging
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketState

from backend.core.api.app.routes.connection_manager import ConnectionManager


def notification_pipeline(events, push, email, sleep):
    source = Path(__file__).resolve().parents[1] / "core/api/app/routes/websockets.py"
    tree = ast.parse(source.read_text())
    coroutine = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                     and node.name == "_check_user_offline_and_send_email")
    namespace = {
        "Optional": Optional, "FastAPI": object, "CacheService": object,
        "ConnectionManager": ConnectionManager, "time": time, "uuid": uuid,
        "logger": logging.getLogger(__name__), "asyncio": SimpleNamespace(sleep=sleep),
        "NotificationEventService": lambda cache: SimpleNamespace(create_chat_assistant_message_event=events),
        "_send_push_notification_if_enabled": push, "_send_offline_email_notification": email,
    }
    exec(compile(ast.Module(body=[coroutine], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[coroutine.name]


# contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible,apple-notifications.payload.privacy-safe,chats.completion.recovery-takeover
@pytest.mark.parametrize("socket_state,in_grace,expected_pushes", [
    (WebSocketState.CONNECTED, False, 0),
    (WebSocketState.CONNECTED, True, 1),
    (WebSocketState.DISCONNECTED, True, 1),
    (WebSocketState.DISCONNECTED, False, 1),
])
def test_completion_dispatches_push_when_only_stale_foreground_viewer_remains(socket_state, in_grace, expected_pushes):
    manager = ConnectionManager()
    user, device, chat = "synthetic-user", "synthetic-device", "synthetic-chat"
    manager.active_connections[user] = {device: SimpleNamespace(application_state=socket_state)}
    manager.active_chat_per_connection[(user, device)] = chat
    manager.connection_foreground_state[(user, device)] = True
    if in_grace:
        manager.grace_period_tasks[(user, device)] = SimpleNamespace(done=lambda: False)
    events, push, email, sleep = AsyncMock(), AsyncMock(return_value=True), AsyncMock(), AsyncMock()
    pending_delivery = AsyncMock()
    app = SimpleNamespace(state=SimpleNamespace(cache_service=SimpleNamespace(add_pending_reminder_delivery=pending_delivery)))
    notify = notification_pipeline(events, push, email, sleep)

    asyncio.run(notify(app, manager, user, chat, "synthetic response", task_id="synthetic-message", max_attempts=1))

    assert push.await_count == expected_pushes
    assert events.await_count == expected_pushes
    if expected_pushes:
        push.assert_awaited_once_with(app=app, user_id=user, chat_id=chat, response_preview="synthetic response")
        events.assert_awaited_once_with(user_id=user, chat_id=chat, has_encrypted_preview=False)
    # The same retained session still owns completion recovery. Notification
    # visibility must not change that storage decision or duplicate the queue.
    pending_delivery.assert_not_awaited()
    email.assert_not_awaited()
