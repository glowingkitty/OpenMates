"""Reminder HTML keeps accessible text and exact image/button destinations."""
from pathlib import Path

from lxml import html
import pytest

from backend.core.api.app.services.email.renderer import render_mjml_template
from backend.core.api.app.services.email_template import html_to_plain_text
from backend.core.api.app.services.translations import TranslationService
from backend.core.api.app.tasks.email_tasks import reminder_notification_email_task as task

TEMPLATES = Path(__file__).parents[1] / "core/api/templates/email"


def _render(context):
    return render_mjml_template(str(TEMPLATES), "reminder-notification", {
        "t": TranslationService().get_translations("en"),
        "imprint_url": "https://openmates.org/legal/imprint", "privacy_url": "https://openmates.org/legal/privacy",
        "terms_url": "https://openmates.org/legal/terms", "contact_email": "contact@openmates.org", **context,
    })


def _context(monkeypatch, **kwargs):
    from backend.shared.python_utils import frontend_url
    monkeypatch.setattr(frontend_url, "get_frontend_base_url", lambda: "https://app.dev.openmates.org")
    return task.build_reminder_email_context(reminder_prompt="Bring your questions & ideas.", trigger_time="23 October, 13:30 CEST", chat_id="chat-123", is_new_chat=False, **kwargs)


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.identifiable-default,notifications.reminder-email.readable-without-images,notifications.content.privacy-boundary
@pytest.mark.parametrize("kind,label", [("chat", "Open Chat"), ("event", "Open event"), ("appointment", "Open appointment"), ("travel_connection", "Open item"), ("travel_stay", "Open item"), ("home_listing", "Open item"), ("embed", "Open item")])
def test_reminder_html_includes_escaped_metadata_and_exact_linked_preview(monkeypatch, kind, label):
    context = _context(monkeypatch, notification_context={
        "version": 1, "kind": kind, "title": 'Community Hour <test> "title"',
        "description": '<script>alert("private")</script>\nA useful description.',
        "starts_at": "2026-10-27T17:00:00Z", "ends_at": "2026-10-27T18:00:00Z",
        "timezone": "Europe/Berlin", "location": "Online & in Berlin",
        "facts": [{"label": "Organizer", "value": "OpenMates <team>"}],
    }, target_embed_id="embed-456" if kind != "chat" else None,
        preview_url="https://api.dev.openmates.org/v1/reminders/email-preview/opaque-token")
    if kind not in {"chat", "event", "appointment"}:
        assert context["heading_key"] == "header"
    rendered = _render(context)
    document = html.fromstring(rendered)
    assert document.xpath('//img[@src="https://app.dev.openmates.org/images/email/reminder-notification.png"]')
    target_title = 'Community Hour <test> "title"'
    images = document.xpath('//img[@alt=$title]', title=target_title)
    assert len(images) == 1
    assert images[0].get("src") == "https://api.dev.openmates.org/v1/reminders/email-preview/opaque-token"
    expected_url = "https://app.dev.openmates.org/#chat-id=chat-123" + ("&embed-id=embed-456" if kind != "chat" else "")
    assert images[0].getparent().get("href") == expected_url
    button = document.xpath('//a[normalize-space()=$label]', label=label)
    assert len(button) == 1 and button[0].get("href") == expected_url
    assert not document.xpath("//script")
    plain = html_to_plain_text(rendered)
    for text in (target_title, 'A useful description.', 'Online & in Berlin', 'Organizer:', 'OpenMates <team>', 'Bring your questions & ideas.', '18:00', '19:00'):
        assert text in plain
    assert "data:image" not in images[0].get("src")
    assert "icons/mail.png" not in rendered
    assert context["reminder_excerpt"] == target_title


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary
def test_explicit_redaction_has_generic_subject_and_body(monkeypatch):
    context = task.build_reminder_email_context(reminder_prompt="", trigger_time="23 October", chat_id="chat-123", chat_title=None, notification_context=None, is_new_chat=False)
    rendered = _render(context)
    assert context["reminder_excerpt"] == "Your Reminder"
    assert not context["preview_url"]
    assert "A reminder you set has been triggered" in html_to_plain_text(rendered)


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.identifiable-default,notifications.reminder-email.readable-without-images
@pytest.mark.parametrize("is_new_chat", [False, True])
def test_legacy_jobs_keep_saved_prompt_with_or_without_title(monkeypatch, is_new_chat):
    context = task.build_reminder_email_context(reminder_prompt="Saved task <text>\nSecond line", trigger_time="Friday", chat_id="chat-old", is_new_chat=is_new_chat)
    rendered = _render(context)
    assert "Saved task <text>" in html_to_plain_text(rendered)
    assert "Second line" in html_to_plain_text(rendered)
    assert context["reminder_excerpt"] == "Saved task <text> Second line"
    assert not context["preview_url"]


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary
@pytest.mark.parametrize("preview", ["javascript:alert(1)", "data:image/png;base64,YQ==", "cid:private", "http://external.test/image", "https://user:secret@example.com/image", "https://[invalid/"])
def test_email_refuses_active_or_invalid_preview_url(monkeypatch, preview):
    context = _context(monkeypatch, notification_context={"kind": "chat", "title": "Target"}, preview_url=preview)
    assert context["preview_url"] is None


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.preview-access
def test_loopback_preview_requires_the_isolated_mail_stack(monkeypatch):
    preview = "http://localhost:8000/v1/email/reminder-preview/test/image.png"
    context = {"kind": "chat", "title": "Target"}
    monkeypatch.delenv("OPENMATES_CI_ISOLATED", raising=False)
    assert _context(monkeypatch, notification_context=context, preview_url=preview)["preview_url"] is None
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("OPENMATES_CI_ISOLATED", "1")
    monkeypatch.setenv("OPENMATES_CI_MAIL_CAPTURE", "1")
    assert _context(monkeypatch, notification_context=context, preview_url=preview)["preview_url"] == preview


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.identifiable-default,notifications.reminder-email.readable-without-images
def test_target_identifier_cannot_inject_other_hash_parameters(monkeypatch):
    context = _context(monkeypatch, target_embed_id="embed&settings=private", notification_context={"kind": "event", "title": "Target"})
    assert context["chat_url"].endswith("&amp;embed-id=embed%26settings%3Dprivate")


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,notifications.content.privacy-boundary
@pytest.mark.asyncio
async def test_send_task_keeps_legacy_arguments_and_closes_secrets_on_private_failure(monkeypatch, caplog):
    class Secrets:
        closed = False
        async def initialize(self):
            pass
        async def aclose(self):
            self.closed = True
    secrets = Secrets()
    monkeypatch.setattr(task, "SecretsManager", lambda: secrets)
    class Service:
        def __init__(self, **kwargs):
            pass
        async def send_email(self, **kwargs):
            raise ValueError("PRIVATE-REMINDER-CONTENT")
    monkeypatch.setattr(task, "EmailTemplateService", Service)
    assert not await task._async_send_reminder_notification("user@example.test", "PRIVATE-REMINDER-CONTENT", "Friday", "chat-123")
    assert secrets.closed
    assert "PRIVATE-REMINDER-CONTENT" not in caplog.text


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.preview-access
@pytest.mark.asyncio
@pytest.mark.parametrize("accepted,has_preview,has_id,renewed", [
    (True, True, True, True), (False, True, True, False),
    (True, False, True, False), (True, True, False, False),
])
async def test_preview_expiry_renews_only_after_accepted_image_email(monkeypatch, accepted, has_preview, has_id, renewed):
    from unittest.mock import AsyncMock

    secrets = type("Secrets", (), {"initialize": AsyncMock(), "aclose": AsyncMock()})()
    monkeypatch.setattr(task, "SecretsManager", lambda: secrets)
    service = type("Email", (), {"send_email": AsyncMock(return_value=accepted)})()
    monkeypatch.setattr(task, "EmailTemplateService", lambda **kwargs: service)
    monkeypatch.setattr(task, "build_reminder_email_context", lambda **kwargs: {"preview_url": "https://api.test/image.png" if has_preview else None})
    refresh = AsyncMock()
    monkeypatch.setattr(task, "_refresh_preview_expiry_after_delivery", refresh)
    result = await task._async_send_reminder_notification(
        "user@example.test", "Note", "Friday", "chat-123",
        preview_url="https://api.test/image.png", reminder_id="reminder-123" if has_id else None,
    )
    assert result is accepted
    assert refresh.await_count == int(renewed)
    secrets.aclose.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=notifications.reminder-email.preview-access
@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [True, False, ValueError("PRIVATE-CONTENT")])
async def test_preview_expiry_renewal_closes_directus_and_hides_failure(monkeypatch, caplog, outcome):
    from unittest.mock import AsyncMock
    from backend.core.api.app.services import directus as directus_module
    from backend.core.api.app.services.reminder_notification_context import PREVIEW_RETENTION_SECONDS

    update = AsyncMock(return_value=outcome) if isinstance(outcome, bool) else AsyncMock(side_effect=outcome)
    directus = type("Directus", (), {"close": AsyncMock(), "reminder": type("Reminder", (), {"update_reminder": update})()})()
    monkeypatch.setattr(directus_module, "DirectusService", lambda: directus)
    monkeypatch.setattr("time.time", lambda: 1000)
    await task._refresh_preview_expiry_after_delivery("reminder-123")
    update.assert_awaited_once_with("reminder-123", {"notification_preview_expires_at": 1000 + PREVIEW_RETENTION_SECONDS})
    directus.close.assert_awaited_once()
    assert "PRIVATE-CONTENT" not in caplog.text
