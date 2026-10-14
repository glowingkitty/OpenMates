"""Recipient guard and bounded metadata for every live Brevo transport.

Captured isolated CI mail must only reach Mailpit. Known test recipients require
an explicit exact-address allowlist; Gmail plus aliases are never broadened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
from typing import Mapping

_EMAIL_TYPES = frozenset(
    {
        "account-created",
        "account-deletion-warning-correction",
        "account-recovery",
        "account-recovery-pending",
        "action-verification",
        "ai-response-notification",
        "backup-code-was-used",
        "backup-reminder",
        "bank-transfer-amount-notice",
        "bank-transfer-duplicate-reference",
        "bank-transfer-reminder",
        "billing-processing-error",
        "chat-failure-alert",
        "chat-message-notification",
        "community_share_notification",
        "confirm-email",
        "cron_session_notification",
        "daily_ci_digest",
        "daily_issue_digest",
        "error_digest_weekly",
        "existing-account",
        "free-testing-budget-exhausted",
        "health-status-alert",
        "inactive-account-deleted",
        "inactive-account-deletion-reminder",
        "issue_report",
        "issue_report_confirmation",
        "new-api-key-device",
        "new-device-login",
        "newsletter",
        "newsletter-confirmation-request",
        "newsletter-confirmed",
        "newsletter_milestone",
        "openrouter_model_watch",
        "operational_monitoring_digest",
        "password-security-reminder",
        "post-purchase-security-setup",
        "prometheus_alert",
        "purchase-confirmation",
        "recovery-key-was-used",
        "referral-reward",
        "refund-confirmation",
        "reminder-notification",
        "signup_milestone",
        "storage-billing-failed-1",
        "storage-billing-failed-2",
        "storage-billing-failed-3",
        "storage-billing-failed-4",
        "storage-files-deleted",
        "support-contribution-confirmation",
        "team-member-mention-notification",
        "team-removed-notification",
        "team-role-changed-notification",
        "team-storage-billing-failed",
        "test_failure_notification",
        "test_run_started",
        "test_run_summary",
        "usecase_submitted",
        "webhook-rate-limit-digest",
        "workflow-run-completed",
        "workflow-run-digest",
        "contract-audit-report",
        "accessibility-audit-report",
        "ci-failure-report",
    }
)
_ADMIN_EMAIL_TYPES = frozenset(
    {
        "contract-audit-report",
        "accessibility-audit-report",
        "ci-failure-report",
        "test_run_started",
        "test_run_summary",
        "test_failure_notification",
        "daily_ci_digest",
        "daily_issue_digest",
        "issue_report",
        "error_digest_weekly",
        "prometheus_alert",
        "operational_monitoring_digest",
        "health-status-alert",
        "chat-failure-alert",
        "openrouter_model_watch",
        "signup_milestone",
        "newsletter_milestone",
        "community_share_notification",
        "usecase_submitted",
        "cron_session_notification",
    }
)
_TEST_MARKERS = (
    "testacct",
    "openmates-e2e",
    "openmates.e2e",
    "e2e+",
    "+e2e",
    "e2e-",
    "+testacct",
    "+live-signup-",
)
# Signup admission domains are not proof that an ordinary consumer mailbox is a test.
_PUBLIC_MAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "yahoo.com",
        "icloud.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
    }
)


@dataclass(frozen=True)
class LiveEmailDecision:
    allowed: bool
    reason: str
    tags: tuple[str, ...]


def email_type_for_template(template: str) -> str:
    """Expose only registered template/report names in transport metadata."""
    return (
        template if isinstance(template, str) and template in _EMAIL_TYPES else "other"
    )


def _enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def _email(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(
        r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", normalized
    ):
        return ""
    return normalized


def _daily_signup_alias(
    recipient: str, email_type: str, env: Mapping[str, str], allowlist: set[str]
) -> bool:
    """One opt-in UTC-day alias for the already approved dedicated Gmail inbox."""
    if (
        not _enabled(env.get("OPENMATES_LIVE_SIGNUP_SMOKE_ALIAS_ENABLED", ""))
        or env.get("SERVER_ENVIRONMENT", "development").strip().lower()
        not in {"development", "dev"}
        or email_type != "confirm-email"
    ):
        return False
    base = _email(env.get("GMAIL_TEST_ADDRESS", ""))
    if not base or base not in allowlist:
        return False
    local, domain = base.rsplit("@", 1)
    if domain not in {"gmail.com", "googlemail.com"}:
        return False
    today = datetime.now(timezone.utc).date().isoformat()
    expected = f"{local.split('+', 1)[0]}+live-signup-{today}@{domain}"
    return recipient == expected


def live_email_policy(
    recipient: str,
    *,
    email_type: str = "other",
    admin_report: bool = False,
    test_traffic: bool = False,
    environ: Mapping[str, str] | None = None,
) -> LiveEmailDecision:
    """Decide before network I/O; rejection reasons contain no recipient data."""
    env = os.environ if environ is None else environ
    email_type = email_type_for_template(email_type)
    admin_report = admin_report or email_type in _ADMIN_EMAIL_TYPES
    environment = env.get("SERVER_ENVIRONMENT", "development").strip().lower()
    environment = {
        "prod": "production",
        "dev": "development",
        "self_host": "self-host",
    }.get(environment, environment)
    if environment not in {"production", "development", "staging", "self-host"}:
        environment = "other"
    if _enabled(env.get("CI", "")):
        environment = "ci"
    normalized = _email(recipient)
    allowlist = {
        _email(value)
        for value in env.get("OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST", "").split(",")
    } - {""}
    configured = {
        _email(value)
        for key, value in env.items()
        if key.startswith("OPENMATES_TEST_ACCOUNT") and key.endswith("EMAIL")
    } - {""}
    domain = normalized.rsplit("@", 1)[-1] if normalized else ""
    local = normalized.split("@", 1)[0] if normalized else ""
    signup_domains = {
        value.strip().lower()
        for value in env.get("SIGNUP_TEST_EMAIL_DOMAINS", "").split(",")
    } - _PUBLIC_MAIL_DOMAINS
    daily_signup_alias = _daily_signup_alias(normalized, email_type, env, allowlist)
    is_test = (
        test_traffic
        or daily_signup_alias
        or "+live-signup-" in local
        or normalized in configured
        or normalized in allowlist
    )
    if environment != "production":
        is_test = (
            is_test
            or any(marker in local for marker in _TEST_MARKERS)
            or domain in signup_domains
        )
    if _enabled(env.get("CI", "")) and not admin_report:
        is_test = True
    audience = "test" if is_test else ("admin" if admin_report else "user")
    tags = (
        f"environment:{environment}",
        f"email-type:{email_type_for_template(email_type)}",
        f"audience:{audience}",
    )
    if any(
        _enabled(env.get(key, ""))
        for key in (
            "CI_MAIL_CAPTURE",
            "OPENMATES_CI_MAIL_CAPTURE",
            "OPENMATES_CI_ISOLATED",
        )
    ):
        return LiveEmailDecision(False, "isolated_mail_capture", tags)
    if not normalized:
        return LiveEmailDecision(False, "invalid_recipient", tags)
    if domain == "mailosaur.net" or domain.endswith(".mailosaur.net"):
        return LiveEmailDecision(False, "retired_test_inbox", tags)
    if is_test and normalized not in allowlist and not daily_signup_alias:
        return LiveEmailDecision(False, "test_recipient_not_allowlisted", tags)
    return LiveEmailDecision(True, "allowed", tags)


def require_live_email(
    recipient: str,
    *,
    email_type: str,
    admin_report: bool = False,
    test_traffic: bool = False,
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    """Fail visibly in direct transports rather than treating rejection as sent."""
    decision = live_email_policy(
        recipient,
        email_type=email_type,
        admin_report=admin_report,
        test_traffic=test_traffic,
        environ=environ,
    )
    if not decision.allowed:
        raise ValueError(f"Live email rejected: {decision.reason}")
    return list(decision.tags)
