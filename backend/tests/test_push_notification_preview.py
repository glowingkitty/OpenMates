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
def completion_dispatch():
    # Execute the complete production coroutine independently of unrelated API
    # bootstrap services, matching existing completion/cache-fallback tests.
    source = Path(__file__).resolve().parents[1] / 'core/api/app/routes/websockets.py'
    node = next(n for n in ast.parse(source.read_text()).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == '_send_push_notification_if_enabled')
    node.returns = None
    for argument in node.args.args:
        argument.annotation = None
    namespace = {'logger': logging.getLogger(__name__)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source), 'exec'), namespace)
    return namespace[node.name]


@pytest.mark.parametrize("content,expected", [
    ('```json\n{"type":"app_skill_use","embed_id":"fixture","query":"' + 'x' * 250 + '"}\n```\n**Readable** prose follows.', 'Readable prose follows.'),
    ('```json\n{"type":"app_skill_use","embed_id":"fixture"}\n```', ''),
    ('~~~python\nprint("fixture")\n~~~\nHuman summary.', 'Human summary.'),
    ('Readable first.\n```json\n{"type":"app_skill_use","embed_id":', 'Readable first.'),
    ('```json\n{"type":"app_skill_use","embed_id":', ''),
    ('JSON objects can contain app_skill_use and embed_id words in ordinary prose.', 'JSON objects can contain app_skill_use and embed_id words in ordinary prose.'),
    ('# Heading\n- **Bold** and [human link](https://example.invalid).\n![image](https://example.invalid/image)', 'Heading Bold and human link. [Image]'),
])
# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_notification_preview_preserves_prose_and_removes_fences(content, expected):
    assert notification_preview_text(content) == expected


@pytest.mark.parametrize("content,expected", [
    ('```json\n{"type":"app_skill_use","embed_id":"fixture","metadata":"' + 'x' * 300 + '"}\n```\nHuman explanation.', 'Human explanation.'),
    ('```json\n{"type":"app_skill_use","embed_id":"fixture"}\n```', 'Your AI assistant has responded.'),
])
# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe
def test_completion_dispatch_sanitizes_full_content_before_preview_limit(monkeypatch, content, expected):
    celery = SimpleNamespace(send_task=Mock())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", SimpleNamespace(app=celery))
    notify = completion_dispatch()
    cache = SimpleNamespace(get_user_by_id=AsyncMock(return_value={
        "push_notification_enabled": True,
        "push_notification_subscription": '{"type":"apns","token":"synthetic"}',
        "push_notification_preferences": {"aiResponses": True},
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
    expected = "Web | Search: 'GPT6.1 Astra' & 3 other app skills\n\nHere are the results [3 Images]."
    assert notification_preview_text('\n'.join(blocks) + '\n' + prose) == expected
    assert notification_preview_text(expected) == expected


@pytest.mark.parametrize('content,expected', [
    ('```json\n{"type":"app_skill_use","embed_id":"private","app_id":"web","skill_id":"search"}\n```\nSummary.', 'Web | Search\n\nSummary.'),
    ('{"type":"app_skill_use","embed_id":"private","app_id":"web","skill_id":"search","query":{"private":"never"}}\nSummary.', 'Web | Search\n\nSummary.'),
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
