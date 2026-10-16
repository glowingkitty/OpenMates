"""The isolated SMTP capture must preserve newsletter protocol header syntax."""

from email import policy
from email.parser import BytesParser

import pytest

from backend.core.api.app.services.email.ci_mail_provider import CiMailProvider
from backend.core.api.app.utils.newsletter_unsubscribe import (
    build_newsletter_one_click_url,
    newsletter_one_click_headers,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["a" * 43, "b" * 128])
# contract-test: supporting surface=rest_api assertions=newsletter.privacy.identity-and-token-boundary,newsletter.lifecycle.unsubscribe-resubscribe
async def test_captured_smtp_keeps_ascii_one_click_url_without_encoded_words(monkeypatch, token):
    from backend.core.api.app.services.email import ci_mail_provider

    for name, value in {
        "CI": "true", "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_CI_MAIL_CAPTURE": "1", "SERVER_ENVIRONMENT": "development",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("NEWSLETTER_PUBLIC_API_ORIGIN", raising=False)
    captured = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("mailpit", 1025, 10)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def send_message(self, message, **_kwargs):
            captured.append(message.as_bytes())

    monkeypatch.setattr(ci_mail_provider.smtplib, "SMTP", FakeSMTP)
    url = build_newsletter_one_click_url(token)
    headers = newsletter_one_click_headers(url)
    headers["X-OpenMates-Email-Type"] = "newsletter-confirmed"
    assert await CiMailProvider().send_email(
        sender_name="Synthetic sender", sender_email="newsletter@example.com",
        recipient_email="ci-inbox+synthetic@example.com", recipient_name="",
        subject="Synthetic welcome", html_content="<p>Welcome</p>",
        plain_text_content="Welcome", email_headers=headers, attachments=None,
    )
    assert len(captured) == 1
    raw_headers = captured[0].split(b"\r\n\r\n", 1)[0]
    assert all(len(line) <= 998 for line in raw_headers.split(b"\r\n"))
    assert f"List-Unsubscribe: <{url}>\r\n".encode() in raw_headers + b"\r\n"
    # Mailpit's headers endpoint returns raw field values, rather than decoding
    # unstructured MIME display words. Verify that raw parse preserves the URI.
    parsed = BytesParser(policy=policy.compat32).parsebytes(captured[0])
    assert parsed["List-Unsubscribe"] == f"<{url}>"
    assert "=?" not in parsed["List-Unsubscribe"]
    assert token in parsed["List-Unsubscribe"]
    assert parsed["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert parsed["X-OpenMates-Email-Type"] == "newsletter-confirmed"
