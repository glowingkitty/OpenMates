"""Contract tests for purpose-specific Brevo sender identities."""

from __future__ import annotations

import pytest

from backend.core.api.app.services.email_sender_profiles import sender_profile_for_template


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("confirm-email", ("OpenMates Account Security", "account@openmates.org")),
        ("action-verification", ("OpenMates Account Security", "account@openmates.org")),
        ("new-device-login", ("OpenMates Account Security", "account@openmates.org")),
        ("reminder-notification", ("OpenMates Notifications", "notifications@openmates.org")),
        ("ai-response-notification", ("OpenMates Notifications", "notifications@openmates.org")),
        ("newsletter", ("OpenMates Newsletter", "newsletter@openmates.org")),
        ("newsletter-confirmation-request", ("OpenMates Newsletter", "newsletter@openmates.org")),
        ("issue_report_confirmation", ("OpenMates Support", "support@openmates.org")),
        ("purchase-confirmation", ("OpenMates Support", "support@openmates.org")),
        ("health-status-alert", ("OpenMates", "noreply@openmates.org")),
    ],
)
# contract-test: direct surface=rest_api assertions=notifications.delivery.email-enabled
def test_sender_profile_for_template(template: str, expected: tuple[str, str]) -> None:
    assert sender_profile_for_template(template) == expected


# contract-test: direct surface=rest_api assertions=notifications.delivery.email-enabled
def test_sender_profile_supports_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_NEWSLETTER_SENDER_NAME", "Newsletter Test")
    monkeypatch.setenv("EMAIL_NEWSLETTER_SENDER_EMAIL", "newsletter-test@example.com")

    assert sender_profile_for_template("newsletter") == (
        "Newsletter Test",
        "newsletter-test@example.com",
    )
