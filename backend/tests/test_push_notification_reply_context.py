"""Encrypted reply routing is bound to the authenticated registration/event.

Pure fake-provider tests; these do not call product REST, WebSocket, or APNs.
"""
import ast
import asyncio
import base64
import hashlib
import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.core.api.app.services.push_notification_service import (
    APNS_CHAT_CATEGORY, APNS_ENCRYPTION_INFO, APNS_ENCRYPTION_VERSION,
    PushNotificationService, apns_topic_for_platform,
)
from backend.core.api.app.services.push_reply_context import (
    build_reply_context, reply_workspace, valid_reply_registration,
)
from backend.core.api.app.services.push_subscription_targets import merge_push_subscription_target

class HTTPException(Exception):
    """Route error stand-in keeps pure coroutine tests independent of FastAPI."""
    def __init__(self, status_code, detail):
        self.status_code = status_code
        super().__init__(detail)


USER = "11111111-1111-4111-8111-111111111111"
OTHER_USER = "22222222-2222-4222-8222-222222222222"
CHAT = "33333333-3333-4333-8333-333333333333"
MESSAGE = "44444444-4444-4444-8444-444444444444"
CONTEXT = "55555555-5555-4555-8555-555555555555"
TEAM_HASH = "a" * 64
SERVICES = Path(__file__).resolve().parents[1] / "core/api/app"


def load_functions(relative, names, namespace):
    path = SERVICES / relative
    nodes = [node for node in ast.parse(path.read_text()).body
             if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == set(names)
    for node in nodes:
        node.decorator_list = []
        node.returns = None
        for argument in node.args.args:
            argument.annotation = None
        # Dependency defaults are unrelated to directly executing route logic.
        node.args.defaults = [ast.Constant(None) if isinstance(value, ast.Call) else value
                              for value in node.args.defaults]
    namespace.setdefault("Optional", object)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), "exec"), namespace)
    return [namespace[name] for name in names]


def target_and_key(context=CONTEXT, owner=USER):
    private = x25519.X25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    target = {"type": "apns", "platform": "ios", "token": "fixture-device",
              "device_id": "fixture-installation", "environment": "production",
              "notification_public_key": base64.urlsafe_b64encode(public).decode().rstrip("="),
              "encryption_version": APNS_ENCRYPTION_VERSION, "reply_context_id": context,
              "reply_context_owner_id": owner}
    return target, private


def decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def decrypted(payload, private):
    envelope = payload["encrypted_notification"]
    ephemeral = x25519.X25519PublicKey.from_public_bytes(decode(envelope["ephemeral_public_key"]))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=APNS_ENCRYPTION_INFO).derive(private.exchange(ephemeral))
    return json.loads(AESGCM(key).decrypt(decode(envelope["nonce"]), decode(envelope["ciphertext"]), None))


@pytest.fixture
def apns(monkeypatch):
    calls = []

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json, headers):
            calls.append((url, json, headers))
            return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr("httpx.Client", Client)
    monkeypatch.setenv("APNS_TEAM_ID", "fixture-team")
    monkeypatch.setenv("APNS_KEY_ID", "fixture-key")
    monkeypatch.setenv("APNS_PRIVATE_KEY", "fixture-key-material")
    monkeypatch.delenv("APNS_BUNDLE_ID", raising=False)
    service = PushNotificationService()
    monkeypatch.setattr(service, "_build_apns_jwt", lambda **kwargs: "fixture-provider-auth")
    return service, calls


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.registration.lifecycle
@pytest.mark.parametrize("invalid", [None, "", "x" * 36, "ABCDEFAB-CDEF-4DEF-8DEF-ABCDEFABCDEF", CONTEXT + "x", "0" * 10000,
                                     "00000000-0000-0000-0000-000000000000", "55555555-5555-1555-8555-555555555555", 12])
def test_reply_registration_rejects_malformed_nonce(invalid):
    target, _ = target_and_key()
    assert not valid_reply_registration(invalid, target["notification_public_key"], APNS_ENCRYPTION_VERSION, "device")


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
@pytest.mark.parametrize("metadata,expected", [
    (None, None), ({"id": CHAT}, None), ({"id": CHAT, "hashed_team_id": ""}, None),
    ({"id": CHAT, "hashed_team_id": None, "hashed_user_id": hashlib.sha256(OTHER_USER.encode()).hexdigest()}, None),
    ({"id": CHAT, "hashed_team_id": None, "hashed_user_id": hashlib.sha256(USER.encode()).hexdigest()}, {"kind": "personal"}),
    ({"id": CHAT, "hashed_team_id": TEAM_HASH}, {"kind": "team", "hashed_team_id": TEAM_HASH}),
    ({"id": MESSAGE, "hashed_team_id": TEAM_HASH}, None),
    ({"id": CHAT, "hashed_team_id": None, "hashed_user_id": hashlib.sha256(USER.encode()).hexdigest(),
      "chat_visibility": "direct"}, None),
])
# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_workspace_requires_exact_durable_chat_and_explicit_scope(metadata, expected):
    assert reply_workspace(metadata, USER, CHAT) == expected


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
@pytest.mark.parametrize("field,value", [("reply_context_owner_id", OTHER_USER), ("reply_context_owner_id", None),
    ("reply_context_id", None), ("encryption_version", "future"), ("device_id", None),
    ("notification_public_key", "A" * 43)])
def test_invalid_registration_never_produces_reply_context(field, value):
    target, _ = target_and_key()
    target[field] = value
    assert build_reply_context(target, USER, CHAT, MESSAGE, {"kind": "personal"}) is None


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
@pytest.mark.parametrize("workspace", [None, {}, {"kind": "personal", "hashed_team_id": TEAM_HASH},
    {"kind": "team"}, {"kind": "team", "hashed_team_id": "invalid"}, {"kind": "other"}])
def test_invalid_or_missing_workspace_never_produces_reply_context(workspace):
    target, _ = target_and_key()
    assert build_reply_context(target, USER, CHAT, MESSAGE, workspace) is None


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.registration.lifecycle
def test_registration_persists_nonce_for_authenticated_owner_and_replaces_generation():
    target, _ = target_and_key()
    durable = {"push_notification_subscription": None}
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value=dict(durable)), update_user=AsyncMock())

    async def save(user_id, values):
        assert user_id == USER
        durable.update(values)
        return True

    directus = SimpleNamespace(update_user=AsyncMock(side_effect=save))

    @asynccontextmanager
    async def lock(*args): yield object()

    namespace = {"logger": logging.getLogger(__name__), "apns_topic_for_platform": apns_topic_for_platform,
                 "merge_push_subscription_target": merge_push_subscription_target,
                 "_get_existing_subscription_json": AsyncMock(side_effect=lambda *args: durable["push_notification_subscription"]),
                 "push_subscription_write_lock": lock, "require_push_subscription_lock": AsyncMock(),
                 "NativeDeviceRegisterResponse": Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs)),
                 "HTTPException": HTTPException}
    register, = load_functions("routes/push.py", ["register_native_device"], namespace)
    body = SimpleNamespace(token=target["token"], platform="ios", environment="production", device_id=target["device_id"],
        notification_public_key=target["notification_public_key"], encryption_version=APNS_ENCRYPTION_VERSION,
        reply_context_id=CONTEXT, user_id=OTHER_USER, preview_enabled=False)
    response = asyncio.run(register(body, SimpleNamespace(id=USER), directus, cache))
    assert response.success is True and response.reply_context_id == CONTEXT
    saved = json.loads(durable["push_notification_subscription"])["targets"][0]
    assert saved["reply_context_owner_id"] == USER
    assert saved["reply_context_id"] == CONTEXT
    assert saved["preview_enabled"] is False
    replacement = str(uuid.uuid4())
    body.reply_context_id = replacement
    asyncio.run(register(body, SimpleNamespace(id=USER), directus, cache))
    saved_targets = json.loads(durable["push_notification_subscription"])["targets"]
    assert len(saved_targets) == 1
    assert saved_targets[0]["reply_context_id"] == replacement
    body.reply_context_id = "malformed"
    with pytest.raises(HTTPException) as error:
        asyncio.run(register(body, SimpleNamespace(id=USER), directus, cache))
    assert error.value.status_code == 400
    assert directus.update_user.await_count == 2
    # A server that did not persist the nonce cannot issue an activation ACK.
    body.reply_context_id = str(uuid.uuid4())
    directus.update_user.side_effect = None
    directus.update_user.return_value = False
    responses_before_failure = namespace["NativeDeviceRegisterResponse"].call_count
    with pytest.raises(HTTPException) as error:
        asyncio.run(register(body, SimpleNamespace(id=USER), directus, cache))
    assert error.value.status_code == 500
    assert namespace["NativeDeviceRegisterResponse"].call_count == responses_before_failure
    # Old clients still receive a success response with no nonce binding.
    body.reply_context_id = None
    directus.update_user.return_value = True
    legacy = asyncio.run(register(body, SimpleNamespace(id=USER), directus, cache))
    assert legacy.success is True and legacy.reply_context_id is None


# contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
def test_registration_response_omits_legacy_binding_and_echoes_new_nonce():
    from typing import Optional
    from pydantic import BaseModel

    source = SERVICES / "routes/push.py"
    tree = ast.parse(source.read_text())
    models = [node for node in tree.body if isinstance(node, ast.ClassDef)
              and node.name in {"PushSubscribeResponse", "NativeDeviceRegisterResponse"}]
    namespace = {"BaseModel": BaseModel, "Optional": Optional}
    exec(compile(ast.Module(body=models, type_ignores=[]), str(source), "exec"), namespace)
    response = namespace["NativeDeviceRegisterResponse"]
    assert response(success=True, message="Device registered").model_dump(exclude_none=True) == {
        "success": True, "message": "Device registered"}
    assert response(success=True, message="Device registered", reply_context_id=CONTEXT).model_dump(exclude_none=True) == {
        "success": True, "message": "Device registered", "reply_context_id": CONTEXT}
    route = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                 and node.name == "register_native_device")
    decorator = route.decorator_list[0]
    fields = {field.arg: field.value for field in decorator.keywords}
    assert fields["response_model"].id == "NativeDeviceRegisterResponse"
    assert fields["response_model_exclude_none"].value is True


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.delivery.idempotent-visible
def test_exact_completed_message_and_authoritative_workspace_reach_task(monkeypatch):
    celery = SimpleNamespace(send_task=Mock())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", SimpleNamespace(app=celery))
    monkeypatch.setattr("backend.core.api.app.services.notification_presence.has_active_human", AsyncMock(return_value=False))
    namespace = {"logger": logging.getLogger(__name__), "asyncio": SimpleNamespace(sleep=AsyncMock()),
        "time": time, "uuid": uuid,
        "NotificationEventService": lambda _: SimpleNamespace(create_chat_assistant_message_event=AsyncMock())}
    push, _ = load_functions("routes/websockets.py", ["_send_push_notification_if_enabled", "_check_user_offline_and_send_email"], namespace)
    namespace["_send_push_notification_if_enabled"] = push
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={"push_notification_enabled": True,
        "push_notification_subscription": '{"type":"apns","token":"fixture"}'}),
        add_pending_reminder_delivery=AsyncMock())
    metadata = {"id": CHAT, "hashed_team_id": TEAM_HASH}
    read = AsyncMock(return_value=metadata)
    directus = SimpleNamespace(chat=SimpleNamespace(get_chat_metadata=read))
    app = SimpleNamespace(state=SimpleNamespace(cache_service=cache, directus_service=directus))
    manager = SimpleNamespace(has_foreground_connection_for_chat=lambda *_: False,
        is_user_completion_capable_active=lambda _: False)
    # Execute the actual listener's production call, including its selected
    # stream fields. A continuation's processing task differs from its durable
    # assistant message, and neither push nor pending persistence may swap them.
    source = SERVICES / "routes/websockets.py"
    listener_call = next(node for node in ast.walk(ast.parse(source.read_text()))
                         if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                         and node.func.id == "_check_user_offline_and_send_email")
    stream_payload = {"task_id": OTHER_USER, "message_id": MESSAGE, "full_content_so_far": "Readable"}
    namespace.update(app=app, manager=manager, user_id_uuid=USER,
                     chat_id_from_payload=CHAT, redis_payload=stream_payload)
    asyncio.run(eval(compile(ast.Expression(body=listener_call), str(source), "eval"), namespace))
    queued = celery.send_task.call_args.kwargs["kwargs"]
    assert queued["user_id"] == USER and queued["message_id"] == MESSAGE and queued["chat_id"] == CHAT
    assert queued["workspace"] == {"kind": "team", "hashed_team_id": TEAM_HASH}
    read.assert_awaited_once_with(CHAT, admin_required=True)
    pending = cache.add_pending_reminder_delivery.await_args.kwargs["delivery_payload"]
    assert pending["message_id"] == MESSAGE
    assert pending["message_id"] != stream_payload["task_id"]
    read.return_value = None
    asyncio.run(push(app, USER, CHAT, "Readable", message_id=MESSAGE))
    assert celery.send_task.call_args.kwargs["kwargs"]["workspace"] is None


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_worker_forwards_server_recipient_exact_message_and_workspace():
    service = SimpleNamespace(send_push_notification=Mock(return_value=True))
    namespace = {"logger": logging.getLogger(__name__), "asyncio": asyncio,
        "_can_dispatch_subscription": lambda *_: True, "_direct_chat_push_access": AsyncMock(return_value=True),
        "_chat_has_active_human": AsyncMock(return_value=False), "push_notification_service": service}
    send, = load_functions("tasks/push_notification_task.py", ["send_push_notification"], namespace)
    workspace = {"kind": "team", "hashed_team_id": TEAM_HASH}
    assert send(None, "{}", "OpenMates", "Readable", chat_id=CHAT, user_id=USER, message_id=MESSAGE, workspace=workspace)
    sent = service.send_push_notification.call_args.kwargs
    assert (sent["recipient_account_id"], sent["chat_id"], sent["message_id"], sent["workspace"]) == (USER, CHAT, MESSAGE, workspace)


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.delivery.idempotent-visible
@pytest.mark.parametrize("preview_enabled,body", [(True, "Readable " + "🔐漢字" * 3000), (False, "Private preview"), (True, "")])
def test_encrypted_reply_context_survives_truncation_or_no_preview(apns, preview_enabled, body):
    service, calls = apns
    target, private = target_and_key()
    target["preview_enabled"] = preview_enabled
    workspace = {"kind": "team", "hashed_team_id": TEAM_HASH}
    expected = build_reply_context(target, USER, CHAT, MESSAGE, workspace)
    assert service.send_push_notification(json.dumps(target), "Private title", body, chat_id=CHAT,
        recipient_account_id=USER, message_id=MESSAGE, workspace=workspace)
    payload = calls[0][1]
    import httpx
    assert len(httpx.Request("POST", "https://example.invalid", json=payload).content) <= 4096
    assert "reply_context" not in payload and "recipient_account_id" not in payload
    assert USER not in json.dumps(payload) and MESSAGE not in json.dumps(payload)
    content = decrypted(payload, private)
    assert content["reply_context"] == expected
    if not preview_enabled or not body:
        assert set(content) == {"reply_context"}
    else:
        assert content["preview"].startswith("Readable ") and content["preview"].endswith("…")
    assert payload["aps"]["mutable-content"] == 1


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.registration.lifecycle
def test_multi_target_uses_individual_generation_and_stable_logical_notification(apns):
    service, calls = apns
    first, private1 = target_and_key()
    second, private2 = target_and_key(context=str(uuid.uuid4()))
    second["token"] = "second-device"
    assert service.send_push_notification(json.dumps({"type": "multi", "targets": [first, second]}), "OpenMates", "Readable",
        chat_id=CHAT, recipient_account_id=USER, message_id=MESSAGE, workspace={"kind": "personal"})
    contexts = [decrypted(payload, key)["reply_context"] for (_, payload, _), key in zip(calls, [private1, private2])]
    assert contexts[0]["notification_id"] == contexts[1]["notification_id"]
    assert contexts[0]["registration_context_id"] == CONTEXT
    assert contexts[1]["registration_context_id"] == second["reply_context_id"]
    assert contexts[0]["recipient_account_id"] == contexts[1]["recipient_account_id"] == USER


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
@pytest.mark.parametrize("case", ["legacy", "missing-message", "missing-workspace", "wrong-owner", "watch", "workflow"])
def test_unknown_context_keeps_legacy_or_generic_notification(apns, case):
    service, calls = apns
    target, private = target_and_key()
    message = MESSAGE
    workspace = {"kind": "personal"}
    category = APNS_CHAT_CATEGORY
    if case == "legacy":
        target.pop("reply_context_id")
    elif case == "missing-message":
        message = None
    elif case == "missing-workspace":
        workspace = None
    elif case == "wrong-owner":
        target["reply_context_owner_id"] = OTHER_USER
    elif case == "watch":
        target["platform"] = "watchos"
    elif case == "workflow":
        category = "OPENMATES_WORKFLOW_COMPLETED"
    assert service.send_push_notification(json.dumps(target), "OpenMates", "Readable", chat_id=CHAT,
        recipient_account_id=USER, message_id=message, workspace=workspace, category=category)
    payload = calls[0][1]
    if case == "watch":
        assert "encrypted_notification" not in payload
    else:
        assert decrypted(payload, private) == {"preview": "Readable"}
