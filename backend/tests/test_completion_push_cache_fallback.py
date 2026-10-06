"""Pure completion/registration regression tests with synthetic push targets."""

import ast
import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.core.api.app.services.push_notification_service import apns_topic_for_platform
from backend.core.api.app.services.push_subscription_targets import merge_push_subscription_target


ROOT = Path(__file__).resolve().parents[1] / "core/api/app/routes"


def load_coroutines(filename, names, namespace):
    """Execute complete production coroutines without unrelated route bootstrap."""
    source = ROOT / filename
    tree = ast.parse(source.read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
    assert {node.name for node in nodes} == set(names)
    for node in nodes:
        node.decorator_list = []
        node.returns = None
        node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
        for argument in node.args.args:
            argument.annotation = None
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(source), "exec"), namespace)
    return [namespace[name] for name in names]


@pytest.fixture
def dispatch(monkeypatch):
    celery = SimpleNamespace(send_task=Mock())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", SimpleNamespace(app=celery))
    namespace = {"logger": logging.getLogger(__name__)}
    function, = load_coroutines("websockets.py", ["_send_push_notification_if_enabled"], namespace)
    return function, celery


# contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle,apple-notifications.delivery.idempotent-visible,apple-notifications.payload.privacy-safe
def test_watch_registration_cache_miss_then_background_completion_dispatches(monkeypatch, dispatch, caplog):
    durable = {"push_notification_enabled": False, "push_notification_preferences": {"aiResponses": True}}
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value=dict(durable)),
                            delete_user_cache=AsyncMock(), update_user=AsyncMock(),
                            add_pending_reminder_delivery=AsyncMock())

    async def update_cache(user_id, values):
        cache.get_user_by_id.return_value.update(values)

    async def read_fields(user_id, fields):
        return {key: durable.get(key) for key in fields}

    async def save(user_id, values):
        durable.update(values)
        return True

    cache.update_user.side_effect = update_cache
    directus = SimpleNamespace(get_user_fields_direct=AsyncMock(side_effect=read_fields),
                               update_user=AsyncMock(side_effect=save))

    @asynccontextmanager
    async def lock(*args):
        yield object()

    namespace = {"logger": logging.getLogger(__name__), "apns_topic_for_platform": apns_topic_for_platform,
                 "merge_push_subscription_target": merge_push_subscription_target,
                 "push_subscription_write_lock": lock, "require_push_subscription_lock": AsyncMock(),
                 "PushSubscribeResponse": lambda **kwargs: SimpleNamespace(**kwargs)}
    existing, register = load_coroutines("push.py", ["_get_existing_subscription_json", "register_native_device"], namespace)
    namespace["_get_existing_subscription_json"] = existing
    target = SimpleNamespace(token="synthetic-watch-token", platform="watchos", environment="sandbox",
                             device_id="synthetic-watch-installation", notification_public_key=None,
                             encryption_version=None)
    push, celery = dispatch
    events = AsyncMock()
    namespace = {"logger": logging.getLogger(__name__), "asyncio": SimpleNamespace(sleep=AsyncMock()),
                 "NotificationEventService": lambda _: SimpleNamespace(create_chat_assistant_message_event=events),
                 "_send_push_notification_if_enabled": push, "_send_offline_email_notification": AsyncMock()}
    notify, = load_coroutines("websockets.py", ["_check_user_offline_and_send_email"], namespace)
    manager = SimpleNamespace(has_foreground_connection_for_chat=lambda *_: False,
                              is_user_completion_capable_active=lambda _: True, is_user_active=lambda _: True)
    app = SimpleNamespace(state=SimpleNamespace(cache_service=cache, directus_service=directus))

    async def exercise():
        response = await register(target, SimpleNamespace(id="synthetic-user"), directus, cache)
        assert response.success is True
        assert cache.get_user_by_id.return_value["push_notification_enabled"] is True
        assert cache.get_user_by_id.return_value["push_notification_preferences"] == {"aiResponses": True}
        # Independent expiry still exercises the durable fallback; registration
        # itself must preserve authenticated-session and chat cache state.
        cache.get_user_by_id.return_value = None
        await notify(app, manager, "synthetic-user", "synthetic-chat", "synthetic-private-preview", max_attempts=1)

    asyncio.run(exercise())
    cache.delete_user_cache.assert_not_awaited()
    cache.update_user.assert_awaited_once_with("synthetic-user", {
        "push_notification_enabled": True,
        "push_notification_subscription": durable["push_notification_subscription"],
    })
    directus.get_user_fields_direct.assert_awaited_with("synthetic-user", [
        "push_notification_enabled", "push_notification_subscription", "push_notification_preferences"])
    celery.send_task.assert_called_once()
    queued = celery.send_task.call_args.kwargs
    assert queued["queue"] == "push"
    targets = json.loads(queued["kwargs"]["subscription_json"])["targets"]
    assert [(target["platform"], target["topic"], target["environment"]) for target in targets] == [
        ("watchos", "org.openmates.app.watch", "sandbox")]
    events.assert_awaited_once_with(user_id="synthetic-user", chat_id="synthetic-chat", has_encrypted_preview=False)
    assert "synthetic-private-preview" not in caplog.text


# contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
@pytest.mark.parametrize("durable", [None, {}, {"push_notification_enabled": False},
    {"push_notification_enabled": True, "push_notification_subscription": None},
    {"push_notification_enabled": True, "push_notification_subscription": "synthetic-subscription",
     "push_notification_preferences": {"aiResponses": False}}])
def test_cache_miss_preserves_durable_disabled_missing_and_preference_gates(dispatch, durable):
    push, celery = dispatch
    directus = SimpleNamespace(get_user_fields_direct=AsyncMock(return_value=durable))
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value=None))
    app = SimpleNamespace(state=SimpleNamespace(cache_service=cache, directus_service=directus))
    assert asyncio.run(push(app, "synthetic-user", "synthetic-chat", "")) is False
    celery.send_task.assert_not_called()


# contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
def test_cached_disabled_profile_does_not_trigger_durable_reload(dispatch):
    push, celery = dispatch
    directus = SimpleNamespace(get_user_fields_direct=AsyncMock())
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={"push_notification_enabled": False}))
    app = SimpleNamespace(state=SimpleNamespace(cache_service=cache, directus_service=directus))
    assert asyncio.run(push(app, "synthetic-user", "synthetic-chat", "")) is False
    directus.get_user_fields_direct.assert_not_awaited()
    celery.send_task.assert_not_called()
