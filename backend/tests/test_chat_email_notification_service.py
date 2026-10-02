"""Completed-chat email eligibility and ciphertext boundary tests."""
# contract-test-file: infrastructure

import json
import sys
import time
from copy import deepcopy
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services import chat_email_notification_service as service


def test_private_team_chat_link_has_encoded_context_without_content():
    subject, context = service.message_email_content("Team user", "chat/id", team_id="team/id")
    assert subject == "Team user messaged you in OpenMates."
    assert context["chat_url"].endswith("/#chat-id=chat%2Fid&team-id=team%2Fid")
    assert context["chat_title"] == context["response_preview"] == ""
    assert "token=" not in context["chat_url"] and "key=" not in context["chat_url"]


class Redis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


class Cache:
    def __init__(self):
        self.redis = Redis()

    @property
    async def client(self):
        return self.redis


class Directus:
    def __init__(self, user):
        self.user = user
        self.chat = SimpleNamespace(get_chat_metadata=AsyncMock(return_value={
            "hashed_user_id": __import__("hashlib").sha256(user["id"].encode()).hexdigest(),
        }))
        self.team = SimpleNamespace(get_membership=AsyncMock(return_value=None))

    async def get_user_fields_direct(self, user_id, fields, *, no_cache=False):
        return deepcopy(self.user) if user_id == self.user["id"] else None


class Encryption:
    async def encrypt_with_user_key(self, plaintext, key_id):
        self.plaintext = plaintext
        return "vault:v1:opaque-ciphertext", 1

    async def decrypt_with_user_key(self, ciphertext, key_id):
        assert ciphertext == "vault:v1:opaque-ciphertext"
        return self.plaintext


@pytest.fixture
def fixture(monkeypatch):
    user = {"id": "user-a", "status": "active", "email_notifications_enabled": True,
            "email_notification_preferences": {"aiResponses": True, "includeContent": False},
            "email_notification_preference_choices": {}, "vault_key_id": "vault-key", "language": "en"}
    cache, directus, encryption = Cache(), Directus(user), Encryption()
    broker = []
    tasks_package = ModuleType("backend.core.api.app.tasks")
    tasks_package.__path__ = []
    celery_module = ModuleType("backend.core.api.app.tasks.celery_config")
    celery_module.app = SimpleNamespace(send_task=lambda *args, **kwargs: broker.append((args, kwargs)))
    monkeypatch.setitem(sys.modules, tasks_package.__name__, tasks_package)
    monkeypatch.setitem(sys.modules, celery_module.__name__, celery_module)
    guard_module = ModuleType("backend.core.api.app.services.email_delivery_guard")
    guard_module.send_email_once = AsyncMock()
    monkeypatch.setitem(sys.modules, guard_module.__name__, guard_module)
    monkeypatch.setattr(service, "resolve_notification_email", AsyncMock(return_value="ci@example.com"))
    monkeypatch.setattr(service, "has_active_human", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "is_message_viewed", AsyncMock(return_value=False))
    return SimpleNamespace(user=user, cache=cache, directus=directus, encryption=encryption, broker=broker,
                           task=SimpleNamespace(cache_service=cache, directus_service=directus,
                                                encryption_service=encryption, email_template_service=object()))


async def queue(fixture, *, message_id="message-a", **options):
    return await service.enqueue_chat_email(
        cache_service=fixture.cache, directus_service=fixture.directus,
        encryption_service=fixture.encryption, user_id="user-a", chat_id="chat-a",
        message_id=message_id, **options,
    )


def ready(fixture, message_id="message-a"):
    key = service.candidate_key("user-a", "chat-a", message_id)
    candidate = json.loads(fixture.cache.redis.values[key])
    candidate["not_before"] = time.time() - 1
    fixture.cache.redis.values[key] = json.dumps(candidate)


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary
@pytest.mark.asyncio
async def test_repeated_send_gate_removes_previously_enabled_preview(fixture, monkeypatch):
    fixture.user['email_notification_preferences']['includeContent'] = True
    fixture.user['email_notification_preference_choices']['includeContent'] = {'source': 'user', 'value': True}
    assert await queue(fixture, title='Private title', preview='Private response')
    ready(fixture)

    async def guarded_send(**kwargs):
        assert await kwargs['before_send']()
        assert kwargs['context']['response_preview'] == 'Private response'
        fixture.user['email_notification_preference_choices']['includeContent']['value'] = False
        assert await kwargs['before_send']()
        assert kwargs['context']['response_preview'] == kwargs['context']['chat_title'] == ''
        assert kwargs['send_options']['subject'] == 'Mate messaged you in OpenMates.'
        return True, 'sent'

    monkeypatch.setattr(sys.modules['backend.core.api.app.services.email_delivery_guard'], 'send_email_once', guarded_send)
    assert await service.dispatch_chat_email(fixture.task, user_id='user-a', chat_id='chat-a', message_id='message-a') == 'sent'


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
@pytest.mark.parametrize('late_change', ['opt_out', 'foreground', 'viewed'])
@pytest.mark.asyncio
async def test_state_change_during_preview_decryption_prevents_send(fixture, monkeypatch, late_change):
    fixture.user['email_notification_preferences']['includeContent'] = True
    fixture.user['email_notification_preference_choices']['includeContent'] = {'source': 'user', 'value': True}
    assert await queue(fixture, title='Private title', preview='Private response')
    ready(fixture)
    plaintext = fixture.encryption.plaintext

    async def decrypt(*args):
        if late_change == 'opt_out':
            fixture.user['email_notification_preferences']['aiResponses'] = False
        elif late_change == 'foreground':
            service.has_active_human.return_value = True
        else:
            service.is_message_viewed.return_value = True
        return plaintext

    fixture.encryption.decrypt_with_user_key = decrypt

    async def guarded_send(**kwargs):
        assert not await kwargs['before_send']()
        return False, 'ineligible_at_dispatch'

    monkeypatch.setattr(sys.modules['backend.core.api.app.services.email_delivery_guard'], 'send_email_once', guarded_send)
    assert await service.dispatch_chat_email(fixture.task, user_id='user-a', chat_id='chat-a', message_id='message-a') == 'ineligible_at_dispatch'


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent,notifications.content.privacy-boundary
@pytest.mark.asyncio
async def test_queue_is_id_only_private_and_idempotent(fixture):
    assert await queue(fixture, preview="PRIVATE RESPONSE", title="PRIVATE CHAT")
    assert not await queue(fixture, preview="PRIVATE RESPONSE", title="PRIVATE CHAT")
    key, raw = next(iter(fixture.cache.redis.values.items()))
    assert "PRIVATE RESPONSE" not in raw and "PRIVATE CHAT" not in raw
    assert "encrypted_preview" not in json.loads(raw)
    assert fixture.broker[0][1]["kwargs"] == {"user_id": "user-a", "chat_id": "chat-a", "message_id": "message-a"}
    assert "PRIVATE" not in repr(fixture.broker)
    assert key.startswith("chat_email_candidate:")
    assert not await queue(fixture, message_id="own", sender_user_id="user-a")
    assert not await queue(fixture, message_id="workflow", source="workflow")


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent
@pytest.mark.asyncio
@pytest.mark.parametrize("cause,expected", [
    ("master_opt_out", "disabled"), ("category_opt_out", "disabled"),
    ("unsubscribed", "no_verified_address"), ("active", "active"), ("viewed", "viewed"),
])
async def test_dispatch_rechecks_after_queue_before_reservation(fixture, monkeypatch, cause, expected):
    assert await queue(fixture)
    ready(fixture)
    if cause == "master_opt_out":
        fixture.user["email_notifications_enabled"] = False
    if cause == "category_opt_out":
        fixture.user["email_notification_preferences"]["aiResponses"] = False
    if cause == "unsubscribed":
        service.resolve_notification_email.return_value = None
    if cause == "active":
        service.has_active_human.return_value = True
    if cause == "viewed":
        service.is_message_viewed.return_value = True
    called = AsyncMock()
    monkeypatch.setattr(sys.modules["backend.core.api.app.services.email_delivery_guard"], "send_email_once", called)
    assert await service.dispatch_chat_email(fixture.task, user_id="user-a", chat_id="chat-a", message_id="message-a") == expected
    called.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.delivery.idempotent
@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["master_opt_out", "category_opt_out", "unsubscribed", "active", "viewed", "chat_removed"])
async def test_before_send_rechecks_late_state(fixture, monkeypatch, cause):
    assert await queue(fixture)
    ready(fixture)
    async def guarded_send(**kwargs):
        if cause == "master_opt_out":
            fixture.user["email_notifications_enabled"] = False
        if cause == "category_opt_out":
            fixture.user["email_notification_preferences"]["aiResponses"] = False
        if cause == "unsubscribed":
            service.resolve_notification_email.return_value = None
        if cause == "active":
            service.has_active_human.return_value = True
        if cause == "viewed":
            service.is_message_viewed.return_value = True
        if cause == "chat_removed":
            fixture.directus.chat.get_chat_metadata.return_value = None
        assert await kwargs["before_send"]() is False
        return False, "ineligible_at_dispatch"
    monkeypatch.setattr(sys.modules["backend.core.api.app.services.email_delivery_guard"], "send_email_once", guarded_send)
    assert await service.dispatch_chat_email(fixture.task, user_id="user-a", chat_id="chat-a", message_id="message-a") == "ineligible_at_dispatch"


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary,notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_explicit_preview_is_bounded_escaped_and_revocable(fixture, monkeypatch):
    fixture.user["email_notification_preferences"]["includeContent"] = True
    fixture.user["email_notification_preference_choices"]["includeContent"] = {"source": "user", "value": True}
    preview = "<script>private</script>\n" + "\n".join(f"line {i}" for i in range(1, 20))
    assert await queue(fixture, title="A" * 80, preview=preview)
    ready(fixture)
    raw = next(iter(fixture.cache.redis.values.values()))
    assert "<script>" not in raw and "private" not in raw
    async def guarded_send(**kwargs):
        assert await kwargs["before_send"]() is True
        assert len(kwargs["context"]["chat_title"]) == 60
        assert "&lt;script&gt;private&lt;/script&gt;" in kwargs["context"]["response_preview"]
        assert "line 10" not in kwargs["context"]["response_preview"]
        assert "<script>" not in kwargs["context"]["response_preview"]
        assert len(kwargs["context"]["response_preview"]) <= 2100
        assert "#chat-id=chat-a" in kwargs["context"]["chat_url"]
        assert "#settings/notifications/chat" in kwargs["context"]["settings_url"]
        assert "token=" not in repr(kwargs["context"])
        return True, "sent"
    monkeypatch.setattr(sys.modules["backend.core.api.app.services.email_delivery_guard"], "send_email_once", guarded_send)
    assert await service.dispatch_chat_email(fixture.task, user_id="user-a", chat_id="chat-a", message_id="message-a") == "sent"

    fixture.user["email_notification_preference_choices"]["includeContent"] = {"source": "user", "value": False}
    # A queued ciphertext envelope cannot bypass a later content opt-out.
    assert service.preview_enabled(fixture.user) is False


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary,notifications.delivery.email-enabled
def test_pre_transition_plaintext_tasks_are_discarded():
    from backend.core.api.app.tasks.email_tasks.ai_response_notification_email_task import send_ai_response_notification

    assert send_ai_response_notification.run(
        recipient_email="unused@example.com", response_preview="old private content",
        user_id="user-a", chat_id="chat-a",
    ) == "legacy_discarded"
    assert send_ai_response_notification.run("unused@example.com", "old private content", "chat-a") == "legacy_discarded"


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_inactive_account_cannot_queue_or_receive(fixture):
    fixture.user['status'] = 'suspended'
    assert not await queue(fixture)
    fixture.user['status'] = 'active'
    assert await queue(fixture)
    ready(fixture)
    fixture.user['status'] = 'archived'
    assert await service.dispatch_chat_email(fixture.task, user_id='user-a', chat_id='chat-a', message_id='message-a') == 'disabled'


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary,notifications.delivery.email-enabled
@pytest.mark.asyncio
async def test_optional_corrupt_envelopes_fall_back_to_private_mail(fixture, monkeypatch):
    assert await queue(fixture)
    ready(fixture)
    key = service.candidate_key('user-a', 'chat-a', 'message-a')
    candidate = json.loads(fixture.cache.redis.values[key])
    candidate.update(encrypted_sender_name='corrupt', encrypted_preview='corrupt')
    fixture.cache.redis.values[key] = json.dumps(candidate)
    fixture.user['email_notification_preferences']['includeContent'] = True
    fixture.user['email_notification_preference_choices']['includeContent'] = {'value': True, 'source': 'user'}
    fixture.encryption.decrypt_with_user_key = AsyncMock(side_effect=ValueError('unavailable'))
    async def guarded_send(**kwargs):
        assert await kwargs['before_send']()
        assert kwargs['send_options']['subject'] == 'Mate messaged you in OpenMates.'
        assert kwargs['context']['response_preview'] == kwargs['context']['chat_title'] == ''
        return True, 'sent'
    monkeypatch.setattr(sys.modules['backend.core.api.app.services.email_delivery_guard'], 'send_email_once', guarded_send)
    assert await service.dispatch_chat_email(fixture.task, user_id='user-a', chat_id='chat-a', message_id='message-a') == 'sent'


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
@pytest.mark.parametrize('override,eligible', [
    ({}, True),
    ({'is_final_chunk': False}, False),
    ({'full_content_so_far': ''}, False),
    ({'external_request': True}, False),
    ({'workflow_id': 'workflow'}, False),
    ({'workflow_run_id': 'manual-or-scheduled-run'}, False),
    ({'step_test': True}, False),
    ({'awaiting_focus_mode_continuation': True}, False),
    ({'awaiting_async_skill_continuation': True}, False),
    ({'awaiting_sub_chats_completion': True}, False),
    ({'interrupted_by_revocation': True}, False),
    ({'is_anonymous': True}, False),
])
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_production_completion_gate_excludes_intermediate_and_workflow_events(override, eligible):
    import ast
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / 'core/api/app/routes/websockets.py'
    tree = ast.parse(source.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'email_eligible_completion')
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
    assert namespace['email_eligible_completion']({'is_final_chunk': True, 'full_content_so_far': 'visible answer', **override}) is eligible
