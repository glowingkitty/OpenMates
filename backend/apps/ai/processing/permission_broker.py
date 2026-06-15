# backend/apps/ai/processing/permission_broker.py
#
# Deterministic permission policy for provider-backed connected-account actions.
# The LLM can propose actions, but this module authorizes or asks at the technical
# action/account boundary before token broker exchange or provider mutation.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PermissionDecision(StrEnum):
    """Permission broker outcomes."""

    ALLOW_WITHOUT_PROMPT = "allow_without_prompt"
    ASK_USER = "ask_user"
    TECHNICAL_BLOCK = "technical_block"


@dataclass(frozen=True)
class ConnectedAccountAction:
    """Normalized action proposal for connected-account policy checks."""

    app_id: str
    action: str
    account_ref: str
    runtime_mode: str
    capability_enabled: bool = True
    oauth_grant_present: bool = True
    owner_verified: bool = True
    token_ref_scope_matches: bool = True
    affected_count: int = 1
    recurring: bool = False
    external_attendees: bool = False
    broad_date_range: bool = False
    ambiguous_target: bool = False


@dataclass(frozen=True)
class ConnectedAccountDecision:
    """Decision result with a short user/debug-safe reason."""

    decision: PermissionDecision
    reason: str


def decide_connected_account_action(
    action: ConnectedAccountAction,
) -> ConnectedAccountDecision:
    """Apply deterministic policy before any provider token exchange."""

    technical_block = _technical_block_reason(action)
    if technical_block:
        return ConnectedAccountDecision(
            decision=PermissionDecision.TECHNICAL_BLOCK,
            reason=technical_block,
        )

    runtime_mode = action.runtime_mode.strip().lower()
    if runtime_mode == "always_ask":
        return ConnectedAccountDecision(
            decision=PermissionDecision.ASK_USER,
            reason="Always ask is enabled for this action.",
        )
    if runtime_mode == "allow_automatically":
        return ConnectedAccountDecision(
            decision=PermissionDecision.ALLOW_WITHOUT_PROMPT,
            reason="Allow automatically is enabled and technical checks passed.",
        )
    if runtime_mode != "auto_decide":
        return ConnectedAccountDecision(
            decision=PermissionDecision.ASK_USER,
            reason="Unknown runtime mode; asking user.",
        )

    ask_reason = _auto_decide_ask_reason(action)
    if ask_reason:
        return ConnectedAccountDecision(
            decision=PermissionDecision.ASK_USER,
            reason=ask_reason,
        )

    return ConnectedAccountDecision(
        decision=PermissionDecision.ALLOW_WITHOUT_PROMPT,
        reason="Auto decide permitted this narrow action.",
    )


def assert_rest_connected_account_execution_allowed(
    action: ConnectedAccountAction,
    offline_grant: dict[str, Any] | None,
) -> None:
    """REST/API-key callers need a separate explicit offline automation grant."""

    if _offline_grant_allows(action, offline_grant):
        return
    raise PermissionError(
        "Provider-backed connected-account skills require client-held refresh tokens "
        "from web, CLI, or Apple unless an explicit offline automation grant exists."
    )


def _technical_block_reason(action: ConnectedAccountAction) -> str | None:
    if not action.capability_enabled:
        return "Requested action exceeds selected connected-account capability."
    if not action.oauth_grant_present:
        return "Requested action exceeds current provider OAuth grant."
    if not action.owner_verified:
        return "Connected account owner check failed."
    if not action.token_ref_scope_matches:
        return "Token-broker ref scope does not match the requested action."
    return None


def _auto_decide_ask_reason(action: ConnectedAccountAction) -> str | None:
    if action.ambiguous_target:
        return "Auto decide asks when the target account or object is ambiguous."
    if action.broad_date_range and action.action == "read":
        return "Auto decide asks for broad calendar read ranges."
    if action.action == "delete" and action.affected_count > 1:
        return "Auto decide asks for bulk delete actions."
    if action.action in {"update", "delete"} and action.recurring:
        return "Auto decide asks for recurring event updates or deletes."
    if action.action in {"write", "update", "delete", "send"} and action.external_attendees:
        return "Auto decide asks for actions involving external attendees or recipients."
    return None


def _offline_grant_allows(
    action: ConnectedAccountAction,
    offline_grant: dict[str, Any] | None,
) -> bool:
    if not offline_grant or offline_grant.get("revoked"):
        return False
    if offline_grant.get("app_id") != action.app_id:
        return False
    if offline_grant.get("account_ref") != action.account_ref:
        return False
    if action.action not in set(offline_grant.get("actions") or []):
        return False
    expires_at = offline_grant.get("expires_at")
    if expires_at is not None and int(expires_at) <= int(time.time()):
        return False
    return True
