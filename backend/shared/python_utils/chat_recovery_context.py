"""Task-local public-key context for saving client-openable unattended outputs.

Only public identity material is stored here. ContextVar isolation prevents
concurrent Celery coroutine tasks from borrowing another chat's recovery key.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


class RequiredRecoveryOutputError(RuntimeError):
    """A required sealed output could not be saved before dependent work."""


@dataclass(frozen=True)
class RecoveryOutputContext:
    owner_id: str
    owner_hash: str
    root_chat_id: str
    target_chat_id: str
    turn_id: str
    preflight_id: str
    inference_task_id: str
    public_key: str
    key_version: int


@dataclass(frozen=True)
class LegacyOutputContext:
    """Epoch-0 saved-chat admission, with no client recovery key."""

    owner_id: str
    owner_hash: str
    legacy_task_identity: str
    root_chat_id: str
    root_turn_id: str | None
    root_user_message_id: str
    target_chat_id: str


@dataclass(frozen=True)
class VerifiedOutputProducer:
    """Authoritative worker classification; never constructed from Celery headers alone."""

    classification: str  # registered_ai or authorized_direct
    intent_id: str
    task_id: str
    task_name: str
    kwargs_binding: str
    primary_embed_id: str
    primary_message_id: str
    target_chat_id: str
    owner_hash: str
    hashed_team_id: str | None = None
    intent_kind: str | None = None
    expected_embed_version: int | None = None
    session_nonce: str | None = None


@dataclass(frozen=True)
class AuthenticatedDirectSkill:
    """REST principal already checked by the API skill dispatch boundary."""

    owner_id: str
    owner_hash: str
    app_id: str
    skill_id: str
    team_id: str | None = None


active_recovery_output_context: ContextVar[RecoveryOutputContext | None] = ContextVar(
    "active_recovery_output_context", default=None,
)

active_legacy_output_context: ContextVar[LegacyOutputContext | None] = ContextVar(
    "active_legacy_output_context", default=None,
)

active_verified_output_producer: ContextVar[VerifiedOutputProducer | None] = ContextVar(
    "active_verified_output_producer", default=None,
)

active_authenticated_direct_skill: ContextVar[AuthenticatedDirectSkill | None] = ContextVar(
    "active_authenticated_direct_skill", default=None,
)
