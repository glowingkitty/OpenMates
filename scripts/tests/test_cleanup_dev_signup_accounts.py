"""Tests for dev signup-account cleanup guardrails.

The cleanup script protects dev from stale Playwright signup accounts that
consume signup-limit slots. These tests stay intentionally string-focused so the
guardrails can run without Docker, Directus, or live user data. They verify the
SQL preserves configured test accounts, admins, and content-bearing users before
any apply-mode deletion can happen.
"""

from scripts.cleanup_dev_signup_accounts import (
    KnownAccountHash,
    candidate_cte,
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


def test_apply_requires_explicit_confirmation() -> None:
    args = parse_args(["--apply", "--confirm-delete-zero-content-users"])

    assert args.apply is True
    assert args.confirm_delete_zero_content_users is True
