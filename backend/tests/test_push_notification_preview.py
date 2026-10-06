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
    ('# Heading\n- **Bold** and [human link](https://example.invalid).\n![image](https://example.invalid/image)', 'Heading Bold and human link.'),
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
        assert json.loads(plaintext) == {'preview': expected}
        assert payload['aps']['mutable-content'] == 1
