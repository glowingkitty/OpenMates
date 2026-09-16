"""Purpose-specific sender identities for OpenMates email traffic."""

from __future__ import annotations

import os


SENDER_PROFILES = {
    "account": ("OpenMates Account Security", "account@openmates.org"),
    "notifications": ("OpenMates Notifications", "notifications@openmates.org"),
    "newsletter": ("OpenMates Newsletter", "newsletter@openmates.org"),
    "support": ("OpenMates Support", "support@openmates.org"),
    "default": ("OpenMates", "noreply@openmates.org"),
}

ACCOUNT_EMAIL_TEMPLATES = {
    "account-created",
    "account-deletion-warning-correction",
    "account-recovery",
    "action-verification",
    "backup-code-was-used",
    "backup-reminder",
    "confirm-email",
    "existing-account",
    "inactive-account-deleted",
    "inactive-account-deletion-reminder",
    "new-api-key-device",
    "new-device-login",
    "password-security-reminder",
    "post-purchase-security-setup",
    "recovery-key-was-used",
    "signup_milestone",
}

NOTIFICATION_EMAIL_TEMPLATES = {
    "ai-response-notification",
    "community_share_notification",
    "referral-reward",
    "reminder-notification",
    "team-member-mention-notification",
}

NEWSLETTER_EMAIL_TEMPLATES = {
    "newsletter",
    "newsletter-confirmation-request",
    "newsletter-confirmed",
}

SUPPORT_EMAIL_TEMPLATES = {
    "bank-transfer-amount-notice",
    "bank-transfer-duplicate-reference",
    "bank-transfer-reminder",
    "issue_report",
    "issue_report_confirmation",
    "purchase-confirmation",
    "refund-confirmation",
    "storage-billing-failed-1",
    "storage-billing-failed-2",
    "storage-billing-failed-3",
    "storage-files-deleted",
    "support-contribution-confirmation",
    "usecase_submitted",
}


def sender_profile_for_template(template: str) -> tuple[str, str]:
    """Return the configured From identity for an email template."""
    if template in ACCOUNT_EMAIL_TEMPLATES:
        profile = "account"
    elif template in NOTIFICATION_EMAIL_TEMPLATES:
        profile = "notifications"
    elif template in NEWSLETTER_EMAIL_TEMPLATES:
        profile = "newsletter"
    elif template in SUPPORT_EMAIL_TEMPLATES:
        profile = "support"
    else:
        profile = "default"

    default_name, default_email = SENDER_PROFILES[profile]
    env_prefix = f"EMAIL_{profile.upper()}_SENDER"
    return (
        os.getenv(f"{env_prefix}_NAME", default_name),
        os.getenv(f"{env_prefix}_EMAIL", default_email),
    )
