"""CI-only real reminder/Vault/cache recovery -> broker worker -> Mailpit proof.

SetReminderSkill.execute is invoked directly with production services; no browser
session/API authentication is claimed. Scheduler and SMTP worker are real. The
fixture-only task adapter injects real services and defers their cleanup to this
probe's outer finally, retaining BaseServiceTask's real Redis WebSocket publication.
It has no bound Celery request and does not initialize unrelated billing/S3 clients.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import io
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image

from backend.scripts.probe_chat_response_email import _admin, _data, _json_object, _one, _require_isolation
from backend.apps.reminder.skills.set_reminder_skill import SetReminderSkill
from backend.apps.reminder.tasks import _process_due_reminders_async
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.newsletter_utils import hash_email

ARTIFACT = Path('/tmp/reminder-email-probe.json')


class EmailMarkup(HTMLParser):
    def __init__(self, body: str):
        super().__init__()
        self.links: list[str] = []
        self.images: list[dict] = []
        self._anchor = ''
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            self._anchor = attrs.get('href', '')
            self.links.append(self._anchor)
        if tag == 'img':
            self.images.append({**attrs, 'href': self._anchor})

    def handle_endtag(self, tag):
        if tag == 'a':
            self._anchor = ''


class ProbeTask(BaseServiceTask):
    async def initialize_services(self):
        # Injected real services already initialized below. No SMTP/queue mocks.
        return None

    async def cleanup_services(self):
        # This adapter is called directly, outside a bound Celery request. The
        # probe owns these real services across scheduler/replay calls and closes
        # them exactly once in run()'s finally; worker cleanup requires request.id.
        return None


async def _messages(mailpit, email, since, chat_id):
    response = mailpit.get('/api/v1/messages', params={'limit': 100})
    response.raise_for_status()
    found = []
    for item in response.json().get('messages', []):
        if not any(address.get('Address', '').lower() == email for address in item.get('To', [])):
            continue
        stamp = datetime.fromisoformat(item['Created'].replace('Z', '+00:00')).timestamp()
        if stamp + 1 < since or 'reminder' not in item.get('Subject', '').lower():
            continue
        response = mailpit.get(f"/api/v1/message/{item['ID']}")
        response.raise_for_status()
        message = response.json()
        # A prior failed Playwright attempt may have an in-flight SMTP job. Only
        # this disposable chat's real emails count, while duplicates within this
        # scheduler attempt remain visible to the strict count assertion.
        if f'chat-id={chat_id}' not in html.unescape(message.get('HTML') or ''):
            continue
        found.append((stamp, item['ID'], message))
    return [row[2] for row in sorted(found, key=lambda row: row[:2])]


async def _wait_mail(mailpit, email, since, count, chat_id):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        messages = await _messages(mailpit, email, since, chat_id)
        if len(messages) >= count:
            assert len(messages) == count, 'Duplicate reminder email'
            return messages
        await asyncio.sleep(1)
    raise AssertionError('Reminder email did not arrive at isolated Mailpit')


async def run():
    email = _require_isolation()
    ARTIFACT.unlink(missing_ok=True)
    admin = _admin()
    user = _one(admin, '/users', {'filter[hashed_email][_eq]': hash_email(email)})
    user_id = user['id']
    owner = hashlib.sha256(user_id.encode()).hexdigest()
    chat_id, parent_id, child_id = [str(uuid.uuid4()) for _ in range(3)]
    now = int(time.time())
    cache, encryption = CacheService(), EncryptionService()
    directus = DirectusService(encryption_service=encryption)
    task = ProbeTask()
    task._cache_service, task._encryption_service, task._directus_service = cache, encryption, directus
    original = {key: user.get(key) for key in ('email_notifications_enabled', 'email_notification_preferences', 'email_notification_preference_choices')}
    preferences = _json_object(user.get('email_notification_preferences'))
    choices = _json_object(user.get('email_notification_preference_choices'))
    reminders, fixtures, captures, private_values = [], [], [], []
    records = []

    class LogCapture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = LogCapture()
    logging.getLogger().addHandler(handler)
    try:
        assert await encryption.initialize()
        contact = _one(admin, '/items/account_contact_emails', {'filter[user_id][_eq]': user_id, 'filter[hashed_email][_eq]': user['hashed_email']})
        assert contact.get('verified_at') and contact.get('purpose') == 'account_lifecycle'
        preferences['backupReminder'] = True
        choices['includeContent'] = {'source': 'user', 'value': True}
        _data(admin.patch(f'/users/{user_id}', json={'email_notifications_enabled': True,
            'email_notification_preferences': preferences, 'email_notification_preference_choices': choices}))
        _data(admin.post('/items/chats', json={'id': chat_id, 'hashed_user_id': owner, 'storage_state': 'hot',
            'messages_v': 0, 'title_v': 0, 'metadata_v': 0, 'created_at': now, 'updated_at': now,
            'last_edited_overall_timestamp': now, 'last_message_timestamp': now, 'unread_count': 0}))
        fixtures.append(('chats', chat_id))
        for embed_id, parent in ((parent_id, None), (child_id, parent_id)):
            _data(admin.post('/items/embeds', json={'id': embed_id, 'embed_id': embed_id,
                'hashed_embed_id': hashlib.sha256(embed_id.encode()).hexdigest(), 'hashed_user_id': owner,
                'hashed_chat_id': hashlib.sha256(chat_id.encode()).hexdigest(), 'parent_embed_id': parent,
                'root_embed_id': parent, 'status': 'finished', 'storage_state': 'hot',
                'encryption_mode': 'client', 'encrypted_content': 'opaque-client-content'}))
            fixtures.append(('embeds', embed_id))
        skill = SetReminderSkill(app=None, app_id='reminder', skill_id='set-reminder',
            skill_name='Set reminder', skill_description='CI real reminder probe')
        image = io.BytesIO()
        Image.new('RGB', (32, 24), '#f2b57c').save(image, format='PNG')
        photo = base64.b64encode(image.getvalue()).decode()
        contexts = [
            {'version': 1, 'kind': 'chat', 'title': 'Weekend in Berlin',
             'summary': 'Review the museum itinerary and train reservations.', 'category': 'travel', 'icon': 'Train'},
            {'version': 1, 'kind': 'event', 'title': 'Berlin Philharmonic evening',
             'description': 'Doors open at 18:30. Bring the booking confirmation.', 'summary': 'Saved concert details',
             'starts_at': '2027-03-20T19:00:00Z', 'ends_at': '2027-03-20T21:00:00Z',
             'timezone': 'Europe/Berlin', 'location': 'Philharmonie Berlin', 'app_id': 'events',
             'facts': [{'label': 'Provider', 'value': 'Concert provider'}], 'image_base64': photo},
        ]
        with httpx.Client(base_url='http://mailpit:8025', timeout=15) as mailpit, httpx.Client(base_url='http://api:8000', timeout=30) as api:
            since = time.time()
            for index, context in enumerate([*contexts, contexts[1]]):
                if index == 2:
                    choices['includeContent'] = {'source': 'user', 'value': False}
                    _data(admin.patch(f'/users/{user_id}', json={'email_notification_preference_choices': choices}))
                private_values.extend([context['title'], context.get('description', ''), context.get('summary', '')])
                result = await skill.execute(prompt='Reminder notes: check the saved details.',
                    trigger_type='specific', trigger_datetime=datetime.fromtimestamp(now + 3600, timezone.utc).isoformat(),
                    timezone='UTC', target_type='existing_chat' if index == 0 else 'embed', response_type='simple',
                    target_embed_id=None if index == 0 else child_id, target_embed_app_id=None if index == 0 else 'events',
                    target_embed_title=context['title'], notification_context=context,
                    cache_service=cache, encryption_service=encryption, directus_service=directus,
                    user_id=user_id, chat_id=chat_id)
                assert result.success, 'Real set-reminder skill failed'
                reminder_id = result.reminder_id
                reminders.append(reminder_id)
                persisted = _one(admin, '/items/reminders', {'filter[id][_eq]': reminder_id})
                assert context['title'] not in json.dumps(persisted)
                stored = json.loads(await encryption.decrypt_with_user_key(
                    ciphertext=persisted['encrypted_notification_context'], key_id=persisted['vault_key_id']))
                assert stored['title'] == context['title']
                assert stored.get('description') == context.get('description')
                token = stored['_preview_token']
                private_values.append(token)
                # Expire only this fixture's schedule and evict its hot cache entry.
                # The scheduler must recover the encrypted snapshot from Directus.
                _data(admin.patch(f'/items/reminders/{reminder_id}', json={'trigger_at': int(time.time()) - 2}))
                await cache.remove_reminder_from_cache(reminder_id)
                assert await cache.get_cache_schedule_count() == 0
                outcome = await _process_due_reminders_async(task)
                assert outcome.get('processed') == 1 and outcome.get('errors') == 0, 'Real due scheduler failed'
                messages = await _wait_mail(mailpit, email, since, index + 1, chat_id)
                message = messages[-1]
                body = message.get('HTML') or ''
                markup = EmailMarkup(body)
                destination = f'/#chat-id={chat_id}' + (f'&embed-id={child_id}' if index else '')
                assert any(link.endswith(destination) for link in markup.links), 'Email target lost source or child embed'
                if index < 2:
                    assert context['title'] in message['Subject']
                    assert context.get('description', context.get('summary')) in html.unescape(body)
                    assert 'Reminder notes: check the saved details.' in html.unescape(body)
                    preview = next(item for item in markup.images if '/v1/email/reminder-preview/' in item.get('src', ''))
                    assert context['title'] in preview.get('alt', '')
                    assert preview['href'].endswith(destination)
                    assert markup.links.count(preview['href']) >= 2, 'Preview and button destinations differ'
                    image_response = api.get(urlsplit(preview['src']).path)
                    assert image_response.status_code == 200 and image_response.headers.get('content-type') == 'image/png', (
                    f"Actual reminder preview request failed: status={image_response.status_code}, "
                    f"content_type={image_response.headers.get('content-type', 'missing')}"
                )
                    assert image_response.content.startswith(b'\x89PNG\r\n\x1a\n')
                    captures.append({'kind': context['kind'], 'html': body, 'subject': message['Subject'],
                        'title': context['title'], 'destination': destination, 'imageUrl': preview['src'],
                        'image': base64.b64encode(image_response.content).decode()})
                    path = urlsplit(preview['src']).path
                    assert api.get(path.replace(token, 'a' * 43)).status_code == 404
                    _data(admin.patch(f'/items/reminders/{reminder_id}', json={'notification_preview_expires_at': 1}))
                    assert api.get(path).status_code == 404
                    _data(admin.patch(f'/items/reminders/{reminder_id}', json={'notification_preview_expires_at': now + 3600, 'status': 'cancelled'}))
                    assert api.get(path).status_code == 404
                else:
                    assert context['title'] not in body and context['description'] not in body
                    assert context['title'] not in message['Subject'] and 'reminder-preview' not in body
                    assert 'Reminder notes: check the saved details.' not in body
                replay = await _process_due_reminders_async(task)
                assert replay.get('processed') == 0
                await asyncio.sleep(2)
                assert len(await _messages(mailpit, email, since, chat_id)) == index + 1, 'Scheduler replay duplicated mail'
        combined_logs = '\n'.join(records)
        assert not any(value and value in combined_logs for value in private_values), 'Private reminder context appeared in probe logs'
        ARTIFACT.write_text(json.dumps({'captures': captures, 'checks': ['real-skill', 'vault-persistence',
            'cold-cache-recovery', 'real-scheduler', 'broker-worker-smtp', 'image-api', 'capability-revocation',
            'content-opt-out', 'replay-idempotence', 'private-log-check']}))
        ARTIFACT.chmod(0o600)
    finally:
        logging.getLogger().removeHandler(handler)
        for reminder_id in reminders:
            await cache.remove_reminder_from_cache(reminder_id)
            response = admin.delete(f'/items/reminders/{reminder_id}')
            assert response.status_code in (200, 204, 404), 'Could not remove CI reminder'
        for collection, fixture_id in reversed(fixtures):
            response = admin.delete(f'/items/{collection}/{fixture_id}')
            assert response.status_code in (200, 204, 404), 'Could not remove CI target'
        _data(admin.patch(f'/users/{user_id}', json=original))
        await directus.close()
        await encryption.close()
        await cache.close()
        admin.close()
    print('real reminder Mailpit roundtrip passed')


if __name__ == '__main__':
    asyncio.run(run())
