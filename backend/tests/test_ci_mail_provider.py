"""The CI mailbox must never send to real recipients or run outside isolation."""

import asyncio

import pytest

from backend.core.api.app.services.email.ci_mail_provider import CiMailProvider


# contract-test: supporting surface=rest_api assertions=auth.signup.current-flow
def test_ci_mail_provider_rejects_non_ci_environment(monkeypatch):
    monkeypatch.delenv("OPENMATES_CI_MAIL_CAPTURE", raising=False)
    with pytest.raises(RuntimeError, match="isolated development runner"):
        CiMailProvider()


# contract-test: supporting surface=rest_api assertions=auth.signup.current-flow
def test_ci_mail_provider_limits_recipients_and_delivers_rendered_mime(monkeypatch):
    for name, value in {
        "CI": "true",
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_CI_MAIL_CAPTURE": "1",
        "SERVER_ENVIRONMENT": "development",
    }.items():
        monkeypatch.setenv(name, value)

    delivered = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("mailpit", 1025, 10)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def send_message(self, message, *, from_addr, to_addrs):
            delivered.append((message, from_addr, to_addrs))

    monkeypatch.setattr("backend.core.api.app.services.email.ci_mail_provider.smtplib.SMTP", FakeSMTP)
    provider = CiMailProvider()
    payload = dict(
        sender_name="OpenMates",
        sender_email="noreply@openmates.org",
        recipient_name="Test",
        subject="Your code 123456",
        html_content="<p>123456</p>",
        plain_text_content="123456",
        email_headers={"Auto-Submitted": "auto-generated"},
        attachments=None,
    )
    with pytest.raises(ValueError, match="example.com"):
        asyncio.run(provider.send_email(recipient_email="real@gmail.com", **payload))
    assert not delivered

    assert asyncio.run(provider.send_email(recipient_email="ci-inbox+run@example.com", **payload))
    message, sender, recipients = delivered[0]
    assert sender == "noreply@openmates.org"
    assert recipients == ["ci-inbox+run@example.com"]
    assert message["Subject"] == "Your code 123456"
    assert "123456" in message.get_body(preferencelist=("plain",)).get_content()
    assert "<p>123456</p>" in message.get_body(preferencelist=("html",)).get_content()
