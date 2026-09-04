# backend/tests/test_e2e_user_detection.py
#
# Tests for non-production E2E user detection used by backend best-effort jobs.
# These guards prevent scheduled/dev-only side effects from spending provider
# quota for deterministic Playwright accounts while proving production never
# uses the test-account heuristics.

import base64
import hashlib

from backend.shared.python_utils.e2e_user_detection import (
    configured_test_account_hashes,
    is_configured_test_account_profile,
    is_non_production_e2e_email,
    is_non_production_e2e_user_profile,
)


def _hash_email(email: str) -> str:
    return base64.b64encode(hashlib.sha256(email.lower().strip().encode()).digest()).decode()


# contract-test: supporting surface=cli assertions=daily-ai-tests.isolation.ordinary-inference-unchanged
def test_configured_test_account_email_is_detected_in_development(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_1_EMAIL", "testacct1@example.test")

    assert is_non_production_e2e_email("testacct1@example.test") is True
    assert _hash_email("testacct1@example.test") in configured_test_account_hashes()


# contract-test: supporting surface=cli assertions=daily-ai-tests.isolation.ordinary-inference-unchanged
def test_configured_test_account_hash_is_detected_in_profile(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_EMAIL", "openmates.e2e+testacct2@gmail.com")

    assert is_non_production_e2e_user_profile(
        {"hashed_email": _hash_email("openmates.e2e+testacct2@gmail.com")}
    ) is True
    assert is_configured_test_account_profile(
        {"hashed_email": _hash_email("openmates.e2e+testacct2@gmail.com")}
    ) is True


# contract-test: supporting surface=cli assertions=daily-ai-tests.isolation.ordinary-inference-unchanged
def test_signup_test_domain_is_detected_in_development(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("SIGNUP_TEST_EMAIL_DOMAINS", "mail.example.test")

    assert is_non_production_e2e_email("jul281200abc@mail.example.test") is True
    assert is_configured_test_account_profile({"email": "jul281200abc@mail.example.test"}) is False


# contract-test: direct surface=cli assertions=daily-ai-tests.isolation.ordinary-inference-unchanged
def test_e2e_detection_is_disabled_in_production(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_EMAIL", "testacct1@example.test")
    monkeypatch.setenv("SIGNUP_TEST_EMAIL_DOMAINS", "example.test")

    assert is_non_production_e2e_email("testacct1@example.test") is False
    assert is_non_production_e2e_user_profile({"email": "testacct1@example.test"}) is False
