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
import argparse
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = REPO_ROOT / "backend/core/api/app/services"
LOCAL_CLEARTEXT_PATH = REPO_ROOT / "restricted_domains.txt"

# Make the audit work from a source checkout. Containers can still override this.
os.environ.setdefault("DOMAIN_SECURITY_CONFIG_DIR", str(DEFAULT_CONFIG_DIR))
sys.path.insert(0, str(REPO_ROOT))

from backend.core.api.app.services import domain_security  # noqa: E402

DomainSecurityService = domain_security.DomainSecurityService
_MIN_RESTRICTED_DOMAIN_COUNT = domain_security._MIN_RESTRICTED_DOMAIN_COUNT
_REQUIRED_RESTRICTED_DOMAINS = domain_security._REQUIRED_RESTRICTED_DOMAINS


def _load_local_cleartext_domains() -> set[str] | None:
    if not LOCAL_CLEARTEXT_PATH.exists():
        return None
    return {
        line.strip().lower()
        for line in LOCAL_CLEARTEXT_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def _audit_image_copy_contracts() -> list[str]:
    contracts = {
        "backend/core/api/Dockerfile": "COPY backend /app/backend",
        "backend/core/api/Dockerfile.selfhost": "COPY backend /app/backend",
        "backend/core/api/Dockerfile.celery": "COPY . /app/",
    }
    issues = []
    for relative_path, required_copy in contracts.items():
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        if required_copy not in source:
            issues.append(f"{relative_path} does not include the domain-policy source tree")

    signing_workflow = (REPO_ROOT / ".github/workflows/sign-domain-security-policy.yml").read_text(
        encoding="utf-8"
    )
    signing_contracts = (
        "policy_json:",
        "POLICY_JSON: ${{ inputs.policy_json }}",
        "printf '%s\\n' \"$POLICY_JSON\"",
    )
    for contract in signing_contracts:
        if contract not in signing_workflow:
            issues.append(f"sign-domain-security-policy.yml is missing safe policy input contract: {contract}")

    publish_workflow = (REPO_ROOT / ".github/workflows/publish-selfhost-images.yml").read_text(
        encoding="utf-8"
    )
    if "python scripts/audit_domain_security.py --verify-api-worker-selfhost-images" not in publish_workflow:
        issues.append("publish-selfhost-images.yml does not run the domain-security audit")
    return issues


def audit_domain_security(
    *,
    require_signed_bundle: bool = False,
    verify_images: bool = False,
) -> list[str]:
    """Return blocking audit issues for the encrypted domain-security policy."""
    issues: list[str] = []
    service = DomainSecurityService()

    try:
        service.load_security_config()
    except SystemExit as exc:
        return [f"domain security config failed to load: {exc}"]

    if require_signed_bundle and not service._using_signed_policy:
        issues.append("signed domain policy bundle is required but legacy policy loaded")

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

    if verify_images:
        issues.extend(_audit_image_copy_contracts())

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signed-bundle", action="store_true")
    parser.add_argument("--policy-path", type=Path)
    parser.add_argument("--signature-path", type=Path)
    parser.add_argument("--public-key-file", type=Path)
    parser.add_argument("--verify-api-worker-selfhost-images", action="store_true")
    args = parser.parse_args()

    if bool(args.policy_path) != bool(args.signature_path):
        parser.error("--policy-path and --signature-path must be supplied together")
    if args.policy_path:
        os.environ["DOMAIN_SECURITY_POLICY_PATH"] = str(args.policy_path)
        os.environ["DOMAIN_SECURITY_POLICY_SIGNATURE_PATH"] = str(args.signature_path)
    if args.public_key_file:
        domain_security._DOMAIN_POLICY_PUBLIC_KEY_B64 = args.public_key_file.read_text(
            encoding="ascii"
        ).strip()

    issues = audit_domain_security(
        require_signed_bundle=args.signed_bundle,
        verify_images=args.verify_api_worker_selfhost_images,
    )
    if issues:
        print("[domain-security] Audit failed:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print("[domain-security] Audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
