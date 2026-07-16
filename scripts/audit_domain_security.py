#!/usr/bin/env python3
"""Audit the encrypted OpenMates domain-security policy.

This script is a deterministic guard for the company-domain blocklist. It loads
the same encrypted files used by the API service, verifies minimum sentinel
domains, checks suffix-safe subdomain behavior, and compares against the local
cleartext source when that ignored file is available.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = REPO_ROOT / "backend/core/api/app/services"
LOCAL_CLEARTEXT_PATH = REPO_ROOT / "restricted_domains.txt"

# Make the audit work from a source checkout. Containers can still override this.
os.environ.setdefault("DOMAIN_SECURITY_CONFIG_DIR", str(DEFAULT_CONFIG_DIR))
sys.path.insert(0, str(REPO_ROOT))

from backend.core.api.app.services.domain_security import (  # noqa: E402
    DomainSecurityService,
    _MIN_RESTRICTED_DOMAIN_COUNT,
    _REQUIRED_RESTRICTED_DOMAINS,
)


def _load_local_cleartext_domains() -> set[str] | None:
    if not LOCAL_CLEARTEXT_PATH.exists():
        return None
    return {
        line.strip().lower()
        for line in LOCAL_CLEARTEXT_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def audit_domain_security() -> list[str]:
    """Return blocking audit issues for the encrypted domain-security policy."""
    issues: list[str] = []
    service = DomainSecurityService()

    try:
        service.load_security_config()
    except SystemExit as exc:
        return [f"domain security config failed to load: {exc}"]

    if len(service.restricted_domains) < _MIN_RESTRICTED_DOMAIN_COUNT:
        issues.append(
            f"restricted domain count {len(service.restricted_domains)} is below "
            f"minimum {_MIN_RESTRICTED_DOMAIN_COUNT}"
        )

    missing_sentinels = sorted(_REQUIRED_RESTRICTED_DOMAINS - service.restricted_domains)
    if missing_sentinels:
        issues.append("missing required sentinel domains: " + ", ".join(missing_sentinels))

    blocked_cases = [
        "user@google.com",
        "user@research.google.com",
        "user@siemens.com",
        "user@labs.siemens.com",
        "user@rheinmetall.com",
        "user@careers.rheinmetall.com",
        "user@spotify.com",
        "user@podcasts.spotify.com",
    ]
    for email in blocked_cases:
        is_allowed, _reason = service.validate_email_domain(email)
        if is_allowed:
            issues.append(f"expected {email} to be blocked")

    allowed_cases = [
        "user@notgoogle.com",
        "user@google.com.evil.test",
        "user@notspotify.com",
        "user@spotify.com.evil.test",
        "user@example.com",
    ]
    for email in allowed_cases:
        is_allowed, reason = service.validate_email_domain(email)
        if not is_allowed:
            issues.append(f"expected {email} to be allowed, got: {reason}")

    cleartext_domains = _load_local_cleartext_domains()
    if cleartext_domains is not None:
        missing_from_encrypted = sorted(cleartext_domains - service.restricted_domains)
        extra_in_encrypted = sorted(service.restricted_domains - cleartext_domains)
        if missing_from_encrypted:
            issues.append("cleartext domains missing from encrypted config: " + ", ".join(missing_from_encrypted))
        if extra_in_encrypted:
            issues.append("encrypted config has domains absent from cleartext source: " + ", ".join(extra_in_encrypted))

    return issues


def main() -> int:
    issues = audit_domain_security()
    if issues:
        print("[domain-security] Audit failed:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print("[domain-security] Audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
