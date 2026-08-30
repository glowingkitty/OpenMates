# backend/shared/python_utils/e2e_user_detection.py
#
# Shared helpers for identifying deterministic OpenMates E2E users in
# non-production environments. This lets backend jobs avoid expensive or
# side-effectful best-effort work for Playwright accounts without hardcoding
# test-account details into product services.
#
# Production always returns False so real users are never classified by these
# development-only heuristics.

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any, Mapping


_PRODUCTION_ENVIRONMENTS = {"production", "prod"}
_TEST_LOCAL_MARKERS = (
    "testacct",
    "openmates-e2e",
    "openmates.e2e",
    "e2e+",
    "+e2e",
    "e2e-",
    "+testacct",
)


def is_non_production_environment() -> bool:
    return os.getenv("SERVER_ENVIRONMENT", "development").strip().lower() not in _PRODUCTION_ENVIRONMENTS


def _normalized_email(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    email = value.strip().lower()
    return email if "@" in email else ""


def _configured_test_account_emails() -> set[str]:
    emails: set[str] = set()
    for key, value in os.environ.items():
        if not key.startswith("OPENMATES_TEST_ACCOUNT") or not key.endswith("EMAIL"):
            continue
        email = _normalized_email(value)
        if email:
            emails.add(email)
    return emails


def configured_test_account_hashes() -> set[str]:
    hashes: set[str] = set()
    for email in _configured_test_account_emails():
        digest = hashlib.sha256(email.encode()).digest()
        hashes.add(base64.b64encode(digest).decode())
    return hashes


def _signup_test_domains() -> set[str]:
    raw_domains = os.getenv("SIGNUP_TEST_EMAIL_DOMAINS", "")
    return {domain.strip().lower() for domain in raw_domains.split(",") if domain.strip()}


def is_non_production_e2e_email(email: Any) -> bool:
    if not is_non_production_environment():
        return False

    normalized = _normalized_email(email)
    if not normalized:
        return False

    configured_emails = _configured_test_account_emails()
    if normalized in configured_emails:
        return True

    local_part, domain = normalized.rsplit("@", 1)
    if any(marker in local_part for marker in _TEST_LOCAL_MARKERS):
        return True

    if domain in _signup_test_domains():
        return True

    return False


def is_non_production_e2e_user_profile(profile: Mapping[str, Any] | None) -> bool:
    if not is_non_production_environment() or not profile:
        return False

    for email_key in ("email", "user_email", "contact_email"):
        if is_non_production_e2e_email(profile.get(email_key)):
            return True

    hashed_email = profile.get("hashed_email")
    return isinstance(hashed_email, str) and hashed_email in configured_test_account_hashes()


def is_configured_test_account_profile(profile: Mapping[str, Any] | None) -> bool:
    """Strict test-account check for dev-only controls that can affect spend."""
    if not is_non_production_environment() or not profile:
        return False

    configured_emails = _configured_test_account_emails()
    for email_key in ("email", "user_email", "contact_email"):
        if _normalized_email(profile.get(email_key)) in configured_emails:
            return True

    hashed_email = profile.get("hashed_email")
    return isinstance(hashed_email, str) and hashed_email in configured_test_account_hashes()
