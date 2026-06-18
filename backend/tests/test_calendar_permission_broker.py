# backend/tests/test_calendar_permission_broker.py
#
# Calendar permission policy contracts for the connected-account broker.
# These tests intentionally exercise deterministic policy without calling Google.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

from backend.apps.ai.processing.permission_broker import (
    ConnectedAccountAction,
    PermissionDecision,
    decide_connected_account_action,
)


def test_calendar_write_defaults_to_ask() -> None:
    action = ConnectedAccountAction(
        app_id="calendar",
        action="write",
        account_ref="google-work",
        runtime_mode="always_ask",
    )

    decision = decide_connected_account_action(action)

    assert decision.decision == PermissionDecision.ASK_USER
    assert "Always ask" in decision.reason


def test_auto_decide_bulk_delete_asks_user() -> None:
    action = ConnectedAccountAction(
        app_id="calendar",
        action="delete",
        account_ref="google-work",
        runtime_mode="auto_decide",
        affected_count=2,
    )

    decision = decide_connected_account_action(action)

    assert decision.decision == PermissionDecision.ASK_USER
    assert "bulk delete" in decision.reason.lower()


def test_allow_automatically_does_not_prompt_when_authorized() -> None:
    action = ConnectedAccountAction(
        app_id="calendar",
        action="delete",
        account_ref="google-work",
        runtime_mode="allow_automatically",
        capability_enabled=True,
        oauth_grant_present=True,
        owner_verified=True,
        token_ref_scope_matches=True,
    )

    decision = decide_connected_account_action(action)

    assert decision.decision == PermissionDecision.ALLOW_WITHOUT_PROMPT


def test_technical_scope_mismatch_blocks() -> None:
    action = ConnectedAccountAction(
        app_id="calendar",
        action="read",
        account_ref="google-work",
        runtime_mode="allow_automatically",
        token_ref_scope_matches=False,
    )

    decision = decide_connected_account_action(action)

    assert decision.decision == PermissionDecision.TECHNICAL_BLOCK
    assert "scope" in decision.reason.lower()
