"""Unit tests for the test-account 2FA reset helper.

These tests cover the pure argument/env helpers used by the operational script.
They intentionally avoid touching Directus, Redis, or Vault so they can run in
the normal pytest unit suite without secrets or infrastructure side effects.

Runtime behavior is exercised by the E2E account preflight spec.
"""

import base64
import hashlib

from backend.scripts.reset_test_2fa import _get_test_account_env, _hash_email


def test_get_test_account_env_prefers_numbered_slot(monkeypatch):
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_EMAIL", "base@example.test")
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_10_EMAIL", "slot10@example.test")

    assert _get_test_account_env("EMAIL", 10) == "slot10@example.test"


def test_get_test_account_env_falls_back_to_base_then_slot_one(monkeypatch):
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_EMAIL", "base@example.test")
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_1_EMAIL", "slot1@example.test")

    assert _get_test_account_env("EMAIL", 10) == "base@example.test"

    monkeypatch.delenv("OPENMATES_TEST_ACCOUNT_EMAIL")
    assert _get_test_account_env("EMAIL", 10) == "slot1@example.test"


def test_hash_email_matches_backend_normalization():
    normalized = "user@example.test"
    expected = base64.b64encode(hashlib.sha256(normalized.encode()).digest()).decode()

    assert _hash_email("  User@Example.Test  ") == expected
