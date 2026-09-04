"""Tests for dev signup-account cleanup guardrails.

The cleanup script protects dev from stale Playwright signup accounts that
consume signup-limit slots. These tests stay intentionally string-focused so the
guardrails can run without Docker, Directus, or live user data. They verify the
SQL preserves configured test accounts, admins, and content-bearing users before
any apply-mode deletion can happen.
"""
# contract-test-file: tooling

import pytest

from scripts import cleanup_dev_signup_accounts as cleanup
from scripts.cleanup_dev_signup_accounts import (
    KnownAccountHash,
    candidate_cte,
    configured_account_hashes_from_payload,
    is_auto_safe_username,
    known_values_sql,
    parse_args,
)


def test_known_values_sql_escapes_labels_and_hashes() -> None:
    sql = known_values_sql([KnownAccountHash(label="slot'1", hashed_email="hash'value")])

    assert "slot''1" in sql
    assert "hash''value" in sql


def test_candidate_query_preserves_known_admin_and_content_users() -> None:
    sql = candidate_cte([KnownAccountHash(label="1", hashed_email="hash")])

    assert "coalesce(u.is_admin, false) = false" in sql
    assert "k.hashed_email is null" in sql
    assert "c.chat_count = 0" in sql
    assert "c.message_count = 0" in sql
    assert "c.embed_count = 0" in sql
    assert "u.signup_started_at is not null" in sql
    assert "u.last_opened like '/chat/%'" in sql


def test_apply_requires_explicit_confirmation() -> None:
    args = parse_args(["--apply", "--confirm-delete-zero-content-users"])

    assert args.apply is True
    assert args.confirm_delete_zero_content_users is True


def test_protected_account_payload_hashes_emails_without_retaining_plaintext() -> None:
    accounts = configured_account_hashes_from_payload([
        {"slot": 16, "email": "reserved@example.test"},
        {"slot": 21, "email": "expanded@example.test"},
    ])

    assert [account.label for account in accounts] == ["16", "21"]
    assert all("@" not in account.hashed_email for account in accounts)


def test_auto_safe_cleanup_only_selects_old_incomplete_accounts() -> None:
    sql = candidate_cte(
        [KnownAccountHash(label="1", hashed_email="hash")],
        auto_safe=True,
        older_than_days=7,
    )

    assert "coalesce(u.signup_completed, false) = false" in sql
    assert "u.last_access < now() - interval '7 days'" in sql


def test_auto_safe_cleanup_refuses_non_development_environment(monkeypatch) -> None:
    monkeypatch.setattr(cleanup, "get_server_environment", lambda: "production")

    with pytest.raises(SystemExit, match="outside SERVER_ENVIRONMENT=development"):
        cleanup.main([
            "--apply",
            "--auto-safe",
            "--automated-daily-cleanup",
            "--protected-accounts-json",
            "[]",
        ])


def test_auto_safe_cleanup_requires_exact_distinct_slots(monkeypatch) -> None:
    monkeypatch.setattr(cleanup, "get_server_environment", lambda: "development")
    duplicate_accounts = [
        {"slot": slot, "email": f"acct-{min(slot, 26)}@example.test"}
        for slot in range(1, 28)
    ]

    with pytest.raises(SystemExit, match="exactly slots 1-27 with distinct emails"):
        cleanup.main([
            "--apply",
            "--auto-safe",
            "--automated-daily-cleanup",
            "--protected-accounts-json",
            __import__("json").dumps(duplicate_accounts),
        ])


@pytest.mark.parametrize("username", [
    "testacct1abc123",
    "testacct27abc123",
    "cliprov14abc123",
    "cliprov20abc123",
    "ref_abc123def456",
    "aug22110559abc",
])
def test_auto_safe_username_accepts_exact_generated_formats(username: str) -> None:
    assert is_auto_safe_username(username) is True


@pytest.mark.parametrize("username", [
    "testacct0abc123",
    "testacct28abc123",
    "cliprov13abc123",
    "cliprov21abc123",
    "ref_short",
    "aug32110559abc",
    "aug22240559abc",
    "Aug22110559abc",
    "mayor",
])
def test_auto_safe_username_rejects_near_matches(username: str) -> None:
    assert is_auto_safe_username(username) is False
