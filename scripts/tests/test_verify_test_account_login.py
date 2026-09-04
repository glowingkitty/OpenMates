#!/usr/bin/env python3
"""Tests for the fast E2E test-account login preflight.

The script under test talks to the real auth API in production use, but these
unit tests cover only deterministic hashing, TOTP generation, and credential
selection. They never load real account credentials or perform network calls.
"""

# contract-test-file: tooling

from __future__ import annotations

import base64
import hashlib
import json

from scripts import verify_test_account_login as login


def test_hash_helpers_match_web_login_payload_shape() -> None:
    email = "Person@Example.test"
    salt = b"0123456789abcdef"
    salt_b64 = base64.b64encode(salt).decode("ascii")

    assert login.hash_email(email) == base64.b64encode(hashlib.sha256(b"person@example.test").digest()).decode("ascii")
    assert login.hash_lookup_key("password", salt_b64) == base64.b64encode(hashlib.sha256(b"password" + salt).digest()).decode("ascii")
    assert login.derive_email_encryption_key(email, salt_b64) == base64.b64encode(hashlib.sha256(b"person@example.test" + salt).digest()).decode("ascii")


def test_totp_generation_matches_rfc_vector() -> None:
    secret = base64.b32encode(b"12345678901234567890").decode("ascii")

    assert login.generate_totp(secret, for_time=59, digits=8) == "94287082"


def test_load_test_account_uses_expanded_bundle(monkeypatch) -> None:
    monkeypatch.setenv(
        "OPENMATES_TEST_ACCOUNTS_EXPANDED_JSON",
        json.dumps({"21": {"email": "slot21@example.test", "password": "pw", "otpKey": "JBSWY3DPEHPK3PXP"}}),
    )

    account = login.load_test_account(21, allow_base_fallback=False)

    assert account == login.TestAccountCredentials(
        slot=21,
        email="slot21@example.test",
        password="pw",
        otp_key="JBSWY3DPEHPK3PXP",
    )


def test_multi_slot_preflight_does_not_reuse_base_credentials(monkeypatch) -> None:
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_EMAIL", "base@example.test")
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_PASSWORD", "pw")
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_OTP_KEY", "JBSWY3DPEHPK3PXP")

    result = login.verify_slots([1, 2], api_url="https://api.dev.openmates.org", web_origin="https://app.dev.openmates.org", timeout=1)

    assert result["status"] == "failed"
    assert [item["status"] for item in result["results"]] == ["skipped", "skipped"]
