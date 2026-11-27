"""Completion preview projection and encrypted APNs regression coverage."""
import asyncio
import ast
from pathlib import Path
import base64
import json
import logging
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.core.api.app.services.push_notification_service import (
    APNS_CHAT_CATEGORY, APNS_CHAT_MESSAGE_BODY, APNS_ENCRYPTION_INFO,
    APNS_ENCRYPTION_VERSION, PushNotificationService, notification_preview_text,
)
def completion_dispatch(**constants):
    # Execute the complete production coroutine independently of unrelated API
    # bootstrap services, matching existing completion/cache-fallback tests.
    source = Path(__file__).resolve().parents[1] / 'core/api/app/routes/websockets.py'
    node = next(n for n in ast.parse(source.read_text()).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == '_send_push_notification_if_enabled')
    node.returns = None
    for argument in node.args.args:
        argument.annotation = None
    namespace = {'logger': logging.getLogger(__name__), **constants}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source), 'exec'), namespace)
    return namespace[node.name]


@pytest.mark.parametrize("content,expected", [
    ('```json\n{"type":"app_skill_use","embed_id":"fixture","query":"' + 'x' * 250 + '"}\n```\n**Readable** prose follows.', 'Readable prose follows.'),
    ('```json\n{"type":"app_skill_use","embed_id":"fixture"}\n```', ''),
    ('~~~python\nprint("fixture")\n~~~\nHuman summary.', 'Human summary.'),
    ('Readable first.\n```json\n{"type":"app_skill_use","embed_id":', 'Readable first.'),
    ('```json\n{"type":"app_skill_use","embed_id":', ''),
    ('JSON objects can contain app_skill_use and embed_id words in ordinary prose.', 'JSON objects can contain app_skill_use and embed_id words in ordinary prose.'),
    ('# Heading\n- **Bold** and [human link](https://example.invalid).\n![image](https://example.invalid/image)', 'Heading\nBold and human link.\n[Image]'),
])
# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_notification_preview_preserves_prose_and_removes_fences(content, expected):
    assert notification_preview_text(content) == expected


@pytest.mark.parametrize("content,expected", [
    ('```json\n{"type":"app_skill_use","embed_id":"fixture","metadata":"' + 'x' * 300 + '"}\n```\nHuman explanation.', 'Human explanation.'),
    ('```json\n{"type":"app_skill_use","embed_id":"fixture"}\n```', ''),
])
# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_completion_dispatch_sanitizes_full_content_before_preview_limit(monkeypatch, content, expected):
    celery = SimpleNamespace(send_task=Mock())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", SimpleNamespace(app=celery))
    notify = completion_dispatch()
    monkeypatch.setattr("backend.core.api.app.services.notification_presence.has_active_human", AsyncMock(return_value=False))
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={
        "push_notification_enabled": True,
        "push_notification_subscription": '{"type":"apns","token":"synthetic"}',
        "push_notification_preferences": {"aiResponses": True, "includeAnswerText": True},
    }))
    app = SimpleNamespace(state=SimpleNamespace(cache_service=cache))
    assert asyncio.run(notify(app, "synthetic-user", "synthetic-chat", content))
    args = celery.send_task.call_args.kwargs
    assert args["kwargs"]["body"] == expected
    assert args["kwargs"]["chat_id"] == "synthetic-chat"
    assert args["queue"] == "push"


def decode(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


@pytest.mark.parametrize("content,expected", [
    ('```json\n{"type":"app_skill_use","embed_id":"fixture"}\n```\nPrivate readable prose.', 'Private readable prose.'),
    ('```json\n{"type":"app_skill_use","embed_id":', None),
    ('Readable ' + 'a' * 12000, '<truncated>'),
    ('Readable ' + '🔐漢字' * 3000, '<truncated>'),
    ('Readable ' + '\"\\' * 6000, '<truncated>'),
])
# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_apns_transport_keeps_public_generic_and_encrypts_only_clean_preview(monkeypatch, content, expected):
    private = x25519.X25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    target = {"type": "apns", "platform": "ios", "token": "synthetic-device",
              "environment": "production", "encryption_version": APNS_ENCRYPTION_VERSION,
              "notification_public_key": base64.urlsafe_b64encode(public).decode().rstrip('=')}
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json, headers):
            calls.append(json)
            return SimpleNamespace(status_code=200, text='')
    monkeypatch.setattr('httpx.Client', Client)
    monkeypatch.setenv('APNS_TEAM_ID', 'fixture-team')
    monkeypatch.setenv('APNS_KEY_ID', 'fixture-key')
    monkeypatch.setenv('APNS_PRIVATE_KEY', 'fixture-key-material')
    monkeypatch.delenv('APNS_BUNDLE_ID', raising=False)
    service = PushNotificationService()
    monkeypatch.setattr(service, '_build_apns_jwt', lambda **kwargs: 'synthetic-provider-auth')
    assert service._send_apns_notification(target, 'Private title', content, 'synthetic-chat', APNS_CHAT_CATEGORY, None)
    payload = calls[0]
    import httpx
    wire = httpx.Request('POST', 'https://example.invalid', json=payload).content
    assert len(wire) <= 4096
    assert payload['aps']['alert'] == {'title': 'OpenMates', 'body': APNS_CHAT_MESSAGE_BODY}
    assert 'Private' not in json.dumps(payload)
    assert 'app_skill_use' not in json.dumps(payload)
    if expected is None:
        assert 'encrypted_notification' not in payload
        assert 'mutable-content' not in payload['aps']
    else:
        envelope = payload['encrypted_notification']
        ephemeral = x25519.X25519PublicKey.from_public_bytes(decode(envelope['ephemeral_public_key']))
        secret = private.exchange(ephemeral)
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=APNS_ENCRYPTION_INFO).derive(secret)
        plaintext = AESGCM(key).decrypt(decode(envelope['nonce']), decode(envelope['ciphertext']), None)
        if expected == '<truncated>':
            preview = json.loads(plaintext)['preview']
            assert preview.startswith('Readable ')
            assert preview.endswith('…')
            assert len(preview) > 200
            assert content.startswith(preview[:-1])
        else:
            assert json.loads(plaintext) == {'preview': expected}
        assert payload['aps']['mutable-content'] == 1


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.preview.readable
def test_preview_skill_summary_query_and_readable_inline_images():
    blocks = []
    for index, app in enumerate(('web', 'images', 'web', 'code')):
        blocks.append('```json\n' + json.dumps({
            'type': 'app_skill_use', 'embed_id': f'private-id-{index}',
            'app_id': app, 'skill_id': 'search' if app != 'code' else 'get_docs',
            'query': 'GPT6.1 Astra' if index == 0 else 'ignored later query',
            'metadata': {'private_id': 'must-never-render'},
        }) + '\n```')
    prose = 'Here are the results [3 Images](embed:private-image-slug).'
    # The answer text wins; the skill summary only stands in when there is no prose.
    expected = "Here are the results [3 Images]."
    assert notification_preview_text('\n'.join(blocks) + '\n' + prose) == expected
    assert notification_preview_text(expected) == expected
    assert notification_preview_text('\n'.join(blocks)) == "Web | Search: 'GPT6.1 Astra' & 3 other app skills"


@pytest.mark.parametrize('content,expected', [
    ('```json\n{"type":"app_skill_use","embed_id":"private","app_id":"web","skill_id":"search"}\n```\nSummary.', 'Summary.'),
    ('{"type":"app_skill_use","embed_id":"private","app_id":"web","skill_id":"search","query":{"private":"never"}}\nSummary.', 'Summary.'),
    ('| Plant | Spacing |\n|---|:--:|\n| Tomato | 50 cm |\n\n---\nWater daily.', 'Plant · Spacing.\nTomato · 50 cm.\nWater daily.'),
    ('Summary. {"type":"image","embed_id":"private","metadata":{"url":"private"}}', 'Summary. [Image]'),
    ('Summary. {"type":"app_skill_use","embed_id":', 'Summary.'),
    ('Summary. {"type":{},"embed_id":"private"}', 'Summary.'),
    ('```json\n{"type":"app_skill_use","app_id":"web","skill_id":"search","embed_id":{"private":"id"}}\n```', 'Web | Search'),
    ('See [](embed:private-id) and [private-id](embed:private-id).', 'See [Attachment] and [Attachment].'),
    ('![a](https://example.invalid/a) ![b](https://example.invalid/b) ![c](https://example.invalid/c)', '[3 Images]'),
])
# contract-test: supporting surface=gui.apple assertions=apple-notifications.preview.readable
def test_preview_allowlisted_metadata_and_markers(content, expected):
    assert notification_preview_text(content) == expected


# contract-test: supporting surface=gui.apple assertions=apple-notifications.preview.readable
def test_preview_uses_existing_translated_skill_labels_without_internal_ids():
    content = '```json\n{"type":"app_skill_use","embed_id":"private","app_id":"web","skill_id":"search"}\n```'
    assert notification_preview_text(content, lang='de') == 'Internet | Suchen'
    unknown = content.replace('"web"', '"private-app"').replace('"search"', '"private-skill"')
    assert notification_preview_text(unknown) == 'App | Action'


def _apns_with_device_key(monkeypatch, subscription_extra=None):
    """Capture the APNs request for a synthetic device and return a decryptor."""
    private = x25519.X25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    target = {"type": "apns", "platform": "ios", "token": "synthetic-device", "environment": "production",
              "encryption_version": APNS_ENCRYPTION_VERSION,
              "notification_public_key": base64.urlsafe_b64encode(public).decode().rstrip('='),
              **(subscription_extra or {})}
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json, headers):
            calls.append(json)
            return SimpleNamespace(status_code=200, text='')
    monkeypatch.setattr('httpx.Client', Client)
    monkeypatch.setenv('APNS_TEAM_ID', 'fixture-team')
    monkeypatch.setenv('APNS_KEY_ID', 'fixture-key')
    monkeypatch.setenv('APNS_PRIVATE_KEY', 'fixture-key-material')
    service = PushNotificationService()
    monkeypatch.setattr(service, '_build_apns_jwt', lambda **kwargs: 'synthetic-provider-auth')

    def opened():
        envelope = calls[0]['encrypted_notification']
        ephemeral = x25519.X25519PublicKey.from_public_bytes(decode(envelope['ephemeral_public_key']))
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=APNS_ENCRYPTION_INFO).derive(private.exchange(ephemeral))
        return json.loads(AESGCM(key).decrypt(decode(envelope['nonce']), decode(envelope['ciphertext']), None))
    return service, target, calls, opened


@pytest.mark.parametrize('extra,expected_body', [
    ({}, 'Garden answer is ready.'),
    ({'preview_enabled': False}, APNS_CHAT_MESSAGE_BODY),
])
# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.preview.readable
def test_apns_chat_title_is_sealed_to_the_device_and_absent_from_the_wire(monkeypatch, extra, expected_body):
    service, target, calls, opened = _apns_with_device_key(monkeypatch, extra)
    headline = 'Garden planning notes'
    assert service._send_apns_notification(target, 'OpenMates', 'Garden answer is ready.', 'synthetic-chat',
                                           APNS_CHAT_CATEGORY, None, encrypted_title=headline)
    wire = json.dumps(calls[0])
    # Apple only sees the generic alert and ciphertext, never the title.
    assert calls[0]['aps']['alert'] == {'title': 'OpenMates', 'body': APNS_CHAT_MESSAGE_BODY}
    assert 'Garden' not in wire
    assert calls[0]['aps']['mutable-content'] == 1
    assert opened() == {'title': headline, 'body': expected_body}


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_apns_chat_without_title_stays_generic_for_the_extension(monkeypatch):
    service, target, calls, opened = _apns_with_device_key(monkeypatch)
    assert service._send_apns_notification(target, 'OpenMates', 'Garden answer is ready.', 'synthetic-chat',
                                           APNS_CHAT_CATEGORY, None)
    assert opened() == {'preview': 'Garden answer is ready.'}


@pytest.mark.parametrize('prefs,expect_title', [
    ({'aiResponses': True}, True),
    ({'aiResponses': True, 'includeChatTitle': True}, True),
    ({'aiResponses': True, 'includeChatTitle': False}, False),
])
# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_completion_dispatch_adds_chat_title_by_default_and_honours_opt_out(monkeypatch, prefs, expect_title):
    celery = SimpleNamespace(send_task=Mock())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", SimpleNamespace(app=celery))
    notify = completion_dispatch()
    monkeypatch.setattr("backend.core.api.app.services.notification_presence.has_active_human", AsyncMock(return_value=False))
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={
        "push_notification_enabled": True,
        "push_notification_subscription": '{"type":"apns","token":"synthetic"}',
        "push_notification_preferences": prefs,
    }))
    app = SimpleNamespace(state=SimpleNamespace(cache_service=cache))
    assert asyncio.run(notify(app, "synthetic-user", "synthetic-chat", "Garden answer.",
                              chat_title="Garden planning notes"))
    sent = celery.send_task.call_args.kwargs["kwargs"]
    assert sent["body"] == "Garden answer."
    assert sent["chat_context"] is None
    if expect_title:
        assert sent["title"] == sent["chat_title"] == "Garden planning notes"
    else:
        assert (sent["title"], sent["chat_title"]) == ("OpenMates", None)


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_apns_sealed_context_line_is_verbatim_and_absent_from_the_wire(monkeypatch):
    service, target, calls, opened = _apns_with_device_key(monkeypatch)
    # A chat title with braces/markdown must never be run through the answer-text projection.
    assert service._send_apns_notification(target, 'OpenMates', '', 'synthetic-chat', APNS_CHAT_CATEGORY, None,
                                           encrypted_title='Garden {notes} **plan**')
    assert 'Garden' not in json.dumps(calls[0])
    # The chat title is sealed verbatim; without an excerpt the body is the generic text.
    assert opened() == {'title': 'Garden {notes} **plan**', 'body': APNS_CHAT_MESSAGE_BODY}


def _dispatch_with_summary(monkeypatch, prefs, *, headline, metadata):
    celery = SimpleNamespace(send_task=Mock())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", SimpleNamespace(app=celery))
    monkeypatch.setattr("backend.core.api.app.services.notification_presence.has_active_human", AsyncMock(return_value=False))
    read = AsyncMock(return_value=headline)
    monkeypatch.setattr("backend.core.api.app.services.notification_headline_handoff.read_headline", read)
    notify = completion_dispatch(HEADLINE_WAIT_SECONDS=0.0)
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={
        "push_notification_enabled": True, "vault_key_id": "synthetic-vault-key",
        "push_notification_subscription": '{"type":"apns","token":"synthetic"}',
        "push_notification_preferences": {"aiResponses": True, **prefs},
    }))
    directus = SimpleNamespace(chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value=metadata)))
    app = SimpleNamespace(state=SimpleNamespace(cache_service=cache, directus_service=directus,
                                                encryption_service=SimpleNamespace()))
    assert asyncio.run(notify(app, "synthetic-user", "synthetic-chat", "The beds are planned.",
                              chat_title="Garden planning notes"))
    return celery.send_task.call_args.kwargs["kwargs"], read


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.preview.readable
def test_completion_dispatch_sends_chat_title_and_excerpt_by_default(monkeypatch):
    sent, read = _dispatch_with_summary(monkeypatch, {}, headline="✅ Added 4 models", metadata={"is_hidden": False})
    assert sent["chat_title"] == sent["title"] == "Garden planning notes"
    assert sent["body"] == "The beds are planned."
    assert sent["chat_context"] is None
    assert sent["language"] == "en"
    read.assert_not_awaited()  # the post-processing summary no longer delays or titles the push


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_completion_dispatch_preview_can_be_turned_off(monkeypatch):
    sent, _ = _dispatch_with_summary(monkeypatch, {"includeAnswerText": False}, headline=None, metadata={})
    assert (sent["title"], sent["body"]) == ("Garden planning notes", "")


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.preview.readable
@pytest.mark.parametrize("language,generic", [("en", "New message received"), ("de", "Neue Nachricht erhalten")])
def test_long_markdown_reply_fills_the_payload_under_the_chat_title(monkeypatch, language, generic):
    from backend.core.api.app.services.push_notification_content import compose_push_content
    reply = ("## Raised beds\n**Good news:** a 1.2 m wide bed works well. ```python\nprint('code')\n```\n"
             "- Fill the bottom with branches and compost before the topsoil goes in.\n") * 60
    content = compose_push_content(preferences={}, chat_title="Garden planning notes",
                                   preview_text=notification_preview_text(reply), hidden=False)
    service, target, calls, opened = _apns_with_device_key(monkeypatch)
    assert service._send_apns_notification(target, content.title, content.body, 'synthetic-chat', APNS_CHAT_CATEGORY, None,
                                           encrypted_title=content.sealed_title, encrypted_context=content.context,
                                           language=language)
    import httpx
    assert len(httpx.Request('POST', 'https://example.invalid', json=calls[0]).content) <= 4096
    assert calls[0]['aps']['alert'] == {'title': 'OpenMates', 'body': generic}
    shown = opened()
    excerpt = shown['body']
    assert shown['title'] == 'Garden planning notes'
    # The first lines of the answer, line breaks kept; only the last line is cut.
    lines = excerpt.split('\n')
    source_lines = {'Raised beds', 'Good news: a 1.2 m wide bed works well.',
                    'Fill the bottom with branches and compost before the topsoil goes in.'}
    assert lines[:3] == ['Raised beds', 'Good news: a 1.2 m wide bed works well.',
                         'Fill the bottom with branches and compost before the topsoil goes in.']
    assert all(line in source_lines for line in lines[:-1])
    assert excerpt.endswith('…') and not excerpt[:-1].endswith((' ', '\n')) and len(excerpt) > 600
    assert all(marker not in excerpt for marker in ('**', '##', '```', "print("))
    assert reply.replace('**', '').replace('## ', '').replace('- ', '').split()[0] in excerpt


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_multi_target_fan_out_keeps_chat_title_and_language(monkeypatch):
    service, target, calls, opened = _apns_with_device_key(monkeypatch)
    multi = json.dumps({"type": "multi", "targets": [target]})
    assert service.send_push_notification(multi, 'Garden', 'Answer.', chat_id='synthetic-chat', category=APNS_CHAT_CATEGORY,
                                          encrypted_title='Garden', language='de')
    assert calls[0]['aps']['alert'] == {'title': 'OpenMates', 'body': 'Neue Nachricht erhalten'}
    assert opened() == {'title': 'Garden', 'body': 'Answer.'}


# contract-test: supporting surface=gui.web assertions=notifications.content.privacy-boundary
def test_web_push_uses_the_same_layout(monkeypatch):
    sent = {}
    monkeypatch.setitem(sys.modules, 'pywebpush', SimpleNamespace(webpush=lambda **kwargs: sent.update(kwargs)))
    service = PushNotificationService()
    service._initialized, service._vapid_private_key, service._vapid_public_key = True, 'synthetic', 'synthetic'
    target = json.dumps({"endpoint": "https://push.example.invalid/x", "keys": {"p256dh": "k", "auth": "a"}})
    assert service.send_push_notification(target, 'Garden planning notes', 'word ' * 300, chat_id='c',
                                          category=APNS_CHAT_CATEGORY)
    data = json.loads(sent['data'])
    assert data['title'] == 'Garden planning notes'
    assert data['body'].endswith('word…') and len(data['body']) <= 600


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
@pytest.mark.parametrize("metadata", [{"is_hidden": True}, {"is_hidden_candidate": True}, None])
def test_completion_dispatch_hidden_or_unknown_chats_stay_generic(monkeypatch, metadata):
    celery = SimpleNamespace(send_task=Mock())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", SimpleNamespace(app=celery))
    monkeypatch.setattr("backend.core.api.app.services.notification_presence.has_active_human", AsyncMock(return_value=False))
    read = AsyncMock(return_value="✅ Secret detail")
    monkeypatch.setattr("backend.core.api.app.services.notification_headline_handoff.read_headline", read)
    notify = completion_dispatch(HEADLINE_WAIT_SECONDS=0.0)
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={
        "push_notification_enabled": True, "vault_key_id": "k",
        "push_notification_subscription": '{"type":"apns","token":"synthetic"}',
        "push_notification_preferences": {"aiResponses": True, "includeAnswerText": True},
    }))
    directus = SimpleNamespace(chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value=metadata)))
    app = SimpleNamespace(state=SimpleNamespace(cache_service=cache, directus_service=directus, encryption_service=SimpleNamespace()))
    assert asyncio.run(notify(app, "synthetic-user", "synthetic-chat", "Secret answer.", chat_title="Secret"))
    sent = celery.send_task.call_args.kwargs["kwargs"]
    assert (sent["title"], sent["body"], sent["chat_title"], sent["chat_context"]) == ("OpenMates", "", None, None)
    read.assert_not_awaited()
