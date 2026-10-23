"""Limited reminder facts survive cache expiry without widening encrypted reads."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.core.api.app.services.reminder_notification_context import (
    create_preview_token, normalize_notification_context, reminder_email_content_allowed,
    resolve_reminder_source_chat,
)
from backend.core.api.app.utils.log_filters import SensitiveDataFilter, redact_newsletter_token_urls

USER = "11111111-1111-4111-8111-111111111111"
CHAT = "22222222-2222-4222-8222-222222222222"
EMBED = "33333333-3333-4333-8333-333333333333"
REMINDER = "44444444-4444-4444-8444-444444444444"
OWNER = hashlib.sha256(USER.encode()).hexdigest()
CHAT_HASH = hashlib.sha256(CHAT.encode()).hexdigest()


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.durable-limited-context
@pytest.mark.parametrize("change", [
    {"messages": ["private transcript"]}, {"description": "x" * 2001},
    {"facts": [{"label": "x", "value": "y"}] * 9}, {"timezone": "invalid/timezone"},
    {"starts_at": "tomorrow"}, {"image_base64": "not an image"},
])
def test_snapshot_rejects_extra_content_and_unbounded_fields(change):
    with pytest.raises(ValueError):
        normalize_notification_context({"version": 1, "kind": "event", "title": "Meetup", **change})


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.identifiable-default
def test_snapshot_keeps_description_and_respects_deliberate_opt_out():
    value = normalize_notification_context({
        "version": 1, "kind": "event", "title": "Meetup", "description": "<p>Bring questions &amp; ideas.</p>",
        "starts_at": "2026-10-27T18:00:00+01:00", "timezone": "Europe/Berlin",
    })
    assert value["description"] == "Bring questions & ideas."
    assert reminder_email_content_allowed({"email_notification_preferences": {"includeContent": False}})
    assert not reminder_email_content_allowed({"email_notification_preference_choices": {
        "includeContent": {"source": "user", "value": False},
    }})


def _source(*, wrong_owner=False, team=False, parent=False):
    row = {"hashed_user_id": "other" if wrong_owner else OWNER, "hashed_chat_id": CHAT_HASH,
           "hashed_team_id": "team" if team else None}
    if parent:
        row["parent_embed_id"] = "parent"
    directus = SimpleNamespace(
        embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value=row)),
        chat=SimpleNamespace(
            get_chat_activity_candidates=AsyncMock(return_value=[{"id": CHAT}]),
            get_chat_metadata=AsyncMock(return_value={"hashed_user_id": OWNER}),
        ),
    )
    return directus


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.exact-web-target
@pytest.mark.asyncio
async def test_legacy_embed_recovers_only_its_fresh_personal_source():
    directus = _source()
    assert await resolve_reminder_source_chat(directus, USER, embed_id=EMBED) == CHAT
    directus.chat.get_chat_activity_candidates.assert_awaited_once_with(USER)
    directus.chat.get_chat_metadata.assert_awaited_once_with(CHAT, admin_required=True)


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.exact-web-target
@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"wrong_owner": True}, {"team": True}, {"parent": True}])
async def test_source_cannot_cross_owner_team_or_child_provenance(options):
    with pytest.raises(ValueError):
        await resolve_reminder_source_chat(_source(**options), USER, chat_id=CHAT, embed_id=EMBED)


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.preview-access
@pytest.mark.asyncio
async def test_recipient_capability_is_private_revocable_and_validated_before_decryption(monkeypatch):
    from backend.core.api.app.routes.reminder_email_preview import get_reminder_email_preview
    from backend.core.api.app.services import reminder_preview_renderer

    token, digest = create_preview_token()
    context = {"version": 1, "kind": "event", "title": "Private meetup", "_preview_token": token}
    row = {"id": REMINDER, "status": "fired", "notification_preview_expires_at": 2000,
           "notification_preview_token_hash": digest, "encrypted_notification_context": "ciphertext",
           "vault_key_id": "vault-key"}
    decryption = AsyncMock(return_value=json.dumps(context))
    directus = SimpleNamespace(reminder=SimpleNamespace(get_reminder=AsyncMock(return_value=row)))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        directus_service=directus, encryption_service=SimpleNamespace(decrypt_with_user_key=decryption),
    )))
    monkeypatch.setattr("backend.core.api.app.routes.reminder_email_preview.time.time", lambda: 1000)
    monkeypatch.setattr(reminder_preview_renderer, "render_reminder_preview", lambda *args, **kwargs: b"PNG")
    response = await get_reminder_email_preview(REMINDER, token, request)
    assert response.body == b"PNG"
    assert response.headers["cache-control"] == "private, max-age=300"
    decryption.reset_mock()
    for change, supplied in [({}, "a" * 43), ({"status": "cancelled"}, token),
                             ({"status": "fired", "notification_preview_expires_at": 900}, token)]:
        row.update(change)
        with pytest.raises(HTTPException) as error:
            await get_reminder_email_preview(REMINDER, supplied, request)
        assert error.value.status_code == 404
    decryption.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.preview-access
def test_preview_bearer_never_enters_url_or_general_log_output():
    import logging

    token, _ = create_preview_token()
    url = f"https://api.example.test/v1/email/reminder-preview/{REMINDER}/{token}.png"
    assert token not in redact_newsletter_token_urls(url)
    record = logging.LogRecord("test", logging.INFO, "", 0, "GET %s", (url,), None)
    SensitiveDataFilter().filter(record)
    assert token not in record.getMessage()
