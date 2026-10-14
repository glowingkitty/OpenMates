"""Verify actual email service header assembly without opening a transport."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("cssutils")
from backend.core.api.app.services.email_template import EmailSendIneligible, EmailTemplateService
from backend.core.api.app.utils.newsletter_unsubscribe import build_newsletter_one_click_url


# contract-test: direct surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary
@pytest.mark.asyncio
@pytest.mark.parametrize("template", ["newsletter", "newsletter-confirmed", "newsletter-confirmation-request", "new-device-login"])
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_only_real_newsletter_post_url_gets_one_click_headers(template, monkeypatch):
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.delenv("NEWSLETTER_PUBLIC_API_ORIGIN", raising=False)
    service = EmailTemplateService.__new__(EmailTemplateService)
    captured = AsyncMock(return_value=True)
    service.selected_delivery_transport = lambda: "ci_smtp"
    service._ci_mail_provider = SimpleNamespace(send_email=captured)
    service.default_sender_email = "synthetic@example.invalid"
    service.default_sender_name = "Synthetic sender"
    service.translation_service = SimpleNamespace(get_translations=lambda *_args, **_kwargs: {})
    service.render_template = lambda _template, context, *_args, **_kwargs: ("<p>synthetic newsletter</p>", context)
    endpoint = build_newsletter_one_click_url("synthetic_recipient_secret_" + "a" * 20)
    body_url = "https://app.dev.openmates.org/#settings/newsletter/unsubscribe/synthetic"
    context = {"unsubscribe_url": body_url, "unsubscribe_one_click_url": endpoint,
               "block_list_url": "https://app.dev.openmates.org/#settings/email/block/synthetic"}
    assert await service.send_email(template, "ci-inbox+synthetic@example.com", context=context, subject="Synthetic subject")
    headers = captured.call_args.kwargs["email_headers"]
    assert headers["X-OpenMates-Email-Type"] == template
    if template in ("newsletter", "newsletter-confirmed"):
        assert headers["List-Unsubscribe"] == f"<{endpoint}>"
        assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    else:
        assert "List-Unsubscribe-Post" not in headers


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_browser_hash_link_never_advertises_one_click():
    service = EmailTemplateService.__new__(EmailTemplateService)
    captured = AsyncMock(return_value=True)
    service.selected_delivery_transport = lambda: "ci_smtp"
    service._ci_mail_provider = SimpleNamespace(send_email=captured)
    service.default_sender_email = "synthetic@example.invalid"
    service.default_sender_name = "Synthetic sender"
    service.translation_service = SimpleNamespace(get_translations=lambda *_args, **_kwargs: {})
    service.render_template = lambda _template, context, *_args, **_kwargs: ("<p>synthetic newsletter</p>", context)
    assert await service.send_email("newsletter-confirmation-request", "ci-inbox+synthetic@example.com", subject="Synthetic subject",
                                    context={"unsubscribe_url": "https://app.dev.openmates.org/#settings/email/block/synthetic"})
    assert "List-Unsubscribe-Post" not in captured.call_args.kwargs["email_headers"]


@pytest.mark.asyncio
@pytest.mark.parametrize("template", ["newsletter", "newsletter-confirmed", "newsletter_milestone"])
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_unsubscribed_preview_does_not_advertise_global_block_or_dummy_unsubscribe(template):
    service = EmailTemplateService.__new__(EmailTemplateService)
    captured = AsyncMock(return_value=True)
    service.selected_delivery_transport = lambda: "ci_smtp"
    service._ci_mail_provider = SimpleNamespace(send_email=captured)
    service.default_sender_email = "synthetic@example.invalid"
    service.default_sender_name = "Synthetic sender"
    service.translation_service = SimpleNamespace(get_translations=lambda *_args, **_kwargs: {})
    service.render_template = lambda _template, context, *_args, **_kwargs: ("<p>preview</p>", context)
    assert await service.send_email(
        template, "ci-inbox+synthetic@example.com", subject="Synthetic preview",
        context={"_email_audience": "test",
                 "unsubscribe_url": "https://app.dev.openmates.org/#settings/newsletter/unsubscribe/TEST-TOKEN",
                 "block_list_url": "https://app.dev.openmates.org/#settings/email/block/synthetic"},
    )
    headers = captured.call_args.kwargs["email_headers"]
    assert headers["X-OpenMates-Email-Audience"] == "test"
    assert "List-Unsubscribe" not in headers
    assert "List-Unsubscribe-Post" not in headers


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_preview_with_real_subscription_preserves_category_token_headers(monkeypatch):
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.delenv("NEWSLETTER_PUBLIC_API_ORIGIN", raising=False)
    service = EmailTemplateService.__new__(EmailTemplateService)
    captured = AsyncMock(return_value=True)
    service.selected_delivery_transport = lambda: "ci_smtp"
    service._ci_mail_provider = SimpleNamespace(send_email=captured)
    service.default_sender_email = "synthetic@example.invalid"
    service.default_sender_name = "Synthetic sender"
    service.translation_service = SimpleNamespace(get_translations=lambda *_args, **_kwargs: {})
    service.render_template = lambda _template, context, *_args, **_kwargs: ("<p>preview</p>", context)
    endpoint = build_newsletter_one_click_url("synthetic-token-0000000001")
    assert await service.send_email(
        "newsletter", "ci-inbox+synthetic@example.com", subject="Synthetic preview",
        context={"_email_audience": "test", "unsubscribe_one_click_url": endpoint,
                 "block_list_url": "https://app.dev.openmates.org/#settings/email/block/synthetic"},
    )
    headers = captured.call_args.kwargs["email_headers"]
    assert headers["List-Unsubscribe"] == f"<{endpoint}>"
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_oversize_final_newsletter_render_never_reaches_transport(monkeypatch):
    from backend.core.api.app.services import email_template

    service = EmailTemplateService.__new__(EmailTemplateService)
    captured = AsyncMock(return_value=True)
    service.selected_delivery_transport = lambda: "ci_smtp"
    service._ci_mail_provider = SimpleNamespace(send_email=captured)
    service.default_sender_email = "synthetic@example.invalid"
    service.default_sender_name = "Synthetic sender"
    service.shared_urls = {}
    service.templates_dir = "/synthetic-templates"
    service.translation_service = SimpleNamespace(get_translations=lambda *_args, **_kwargs: {})
    monkeypatch.setattr(email_template, "add_shared_urls_to_context", lambda context, _shared: context)
    monkeypatch.setattr(email_template, "process_template_variables", lambda context: context)
    # Exercise the actual render_template/send_email boundary with final MJML
    # output; character count alone would incorrectly admit this UTF-8 message.
    monkeypatch.setattr(email_template, "render_mjml_template", lambda **_kwargs: "é" * (80 * 1024 // 2 + 1))
    assert not await service.send_email("newsletter", "ci-inbox+synthetic@example.com", subject="Synthetic subject")
    captured.assert_not_called()


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_brevo_suppression_is_checked_before_render_or_transport(monkeypatch):
    from backend.core.api.app.services import email_delivery_feedback

    service = EmailTemplateService.__new__(EmailTemplateService)
    service.selected_delivery_transport = lambda: "brevo"
    service.secrets_manager = SimpleNamespace(get_secret=AsyncMock(return_value="synthetic-api-key"))
    service.render_template = AsyncMock()
    service._brevo_provider = SimpleNamespace(send_email=AsyncMock())
    allowed = AsyncMock(return_value=False)
    monkeypatch.setattr(email_delivery_feedback, "email_recipient_allowed", allowed)
    with pytest.raises(EmailSendIneligible):
        await service.send_email("new-device-login", "synthetic@example.invalid", subject="Synthetic subject")
    allowed.assert_awaited_once_with("synthetic@example.invalid", secrets_manager=service.secrets_manager)
    service.render_template.assert_not_called()
    service._brevo_provider.send_email.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("audience,expected", [("test", "test"), ("user", None), ("untrusted", None), (None, None)])
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_only_explicit_test_context_marks_test_audience(audience, expected):
    service = EmailTemplateService.__new__(EmailTemplateService)
    captured = AsyncMock(return_value=True)
    service.selected_delivery_transport = lambda: "ci_smtp"
    service._ci_mail_provider = SimpleNamespace(send_email=captured)
    service.default_sender_email = "synthetic@example.invalid"
    service.default_sender_name = "Synthetic sender"
    service.translation_service = SimpleNamespace(get_translations=lambda *_args, **_kwargs: {})
    service.render_template = lambda _template, context, *_args, **_kwargs: ("<p>synthetic newsletter</p>", context)
    assert await service.send_email("newsletter", "ci-inbox+synthetic@example.com", subject="Synthetic subject",
                                    context={"_email_audience": audience})
    assert captured.call_args.kwargs["email_headers"].get("X-OpenMates-Email-Audience") == expected
