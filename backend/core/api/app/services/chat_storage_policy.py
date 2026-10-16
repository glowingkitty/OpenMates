"""Pure, conservative eligibility decisions for bounded encrypted chat storage.

This module selects only a stable prefix. The archive actor owns authorization,
copy verification, generation fencing, and eventual PostgreSQL pruning.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Collection, Mapping, Sequence


SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class WarmArchivePolicy:
    recent_main_chats: int = 10
    messages_per_chat: int = 100
    encrypted_message_bytes_per_chat: int = 2 * 1024 * 1024
    inactive_days: int = 30

    def __post_init__(self) -> None:
        if min(
            self.recent_main_chats, self.messages_per_chat,
            self.encrypted_message_bytes_per_chat, self.inactive_days,
        ) <= 0:
            raise ValueError("Warm archive limits must be positive")
        if self.messages_per_chat > 100:
            raise ValueError("Warm archive message limit exceeds the bounded 101-row reader")

    @classmethod
    def from_environment(cls) -> "WarmArchivePolicy":
        """Deployment knobs retain the approved defaults unless explicitly set."""
        return cls(
            recent_main_chats=int(os.getenv("CHAT_WARM_RECENT_MAIN_COUNT", "10")),
            messages_per_chat=int(os.getenv("CHAT_WARM_MESSAGES_PER_CHAT", "100")),
            encrypted_message_bytes_per_chat=int(os.getenv("CHAT_WARM_ENCRYPTED_BYTES_PER_CHAT", str(2 * 1024 * 1024))),
            inactive_days=int(os.getenv("CHAT_WARM_INACTIVE_DAYS", "30")),
        )


@dataclass(frozen=True)
class ArchivePrefixDecision:
    eligible: bool
    reason: str
    message_ids: tuple[str, ...] = ()
    through_timestamp: int | None = None
    through_message_id: str | None = None
    encrypted_payload_bytes: int = 0
    blocked_by_message_id: str | None = None


def _message_id(message: Mapping[str, Any]) -> str:
    value = message.get("client_message_id") or message.get("message_id")
    if not value:
        raise ValueError("Every message needs a stable client_message_id")
    return str(value)


def _message_time(message: Mapping[str, Any]) -> int:
    try:
        return int(message["created_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Every message needs a stable created_at timestamp") from exc


def _encrypted_bytes(message: Mapping[str, Any]) -> int:
    total = 0
    for field in ("encrypted_content", "encrypted_thinking_content"):
        value = message.get(field)
        if value is not None:
            if not isinstance(value, (str, bytes)):
                raise ValueError(f"{field} must be encrypted text or bytes")
            total += len(value.encode("utf-8") if isinstance(value, str) else value)
    return total


def select_archive_prefix(
    chat: Mapping[str, Any],
    messages: Sequence[Mapping[str, Any]],
    *,
    now_timestamp: int,
    recent_main_rank: int | None = None,
    checkpoint: Mapping[str, Any] | None = None,
    checkpoint_canonical_ack: bool = False,
    already_archived_message_ids: Collection[str] = (),
    pending_message_ids: Collection[str] = (),
    in_flight_message_ids: Collection[str] = (),
    has_processing_task: bool = False,
    child_result_delivered: bool = False,
    child_parent_consumed: bool = False,
    child_canonical_ack: bool = False,
    child_key_ack: bool = False,
    window_complete: bool = False,
    canonical_ciphertext_available: bool = False,
    required_inference_context: bool = False,
    has_pending_output: bool = False,
    policy: WarmArchivePolicy | None = None,
) -> ArchivePrefixDecision:
    """Select a fully acknowledged oldest prefix; never mutate or delete rows.

    `recent_main_rank` is zero-based among eligible main chats. Pinned and shared
    chats use the same limits. The caller supplies acknowledged state from durable
    persistence, rather than inferring it from Vault cache or task completion.
    """
    limits = policy or WarmArchivePolicy.from_environment()
    if not messages:
        return ArchivePrefixDecision(False, "no_messages")
    if not window_complete:
        return ArchivePrefixDecision(False, "incomplete_message_window")
    if not canonical_ciphertext_available:
        return ArchivePrefixDecision(False, "canonical_ciphertext_unavailable")
    if required_inference_context:
        return ArchivePrefixDecision(False, "required_inference_context")
    if has_pending_output:
        return ArchivePrefixDecision(False, "pending_output")
    if has_processing_task or chat.get("storage_state") in {"archiving", "promoting", "deleting"}:
        return ArchivePrefixDecision(False, "in_flight_chat")

    try:
        ordered = sorted(messages, key=lambda item: (_message_time(item), _message_id(item)))
        ids = [_message_id(message) for message in ordered]
    except ValueError:
        return ArchivePrefixDecision(False, "missing_stable_message_identity")
    if len(ids) != len(set(ids)):
        return ArchivePrefixDecision(False, "duplicate_message_identity")
    try:
        message_sizes = [_encrypted_bytes(message) for message in ordered]
    except ValueError:
        return ArchivePrefixDecision(False, "unsupported_canonical_ciphertext")
    archived = set(already_archived_message_ids)
    first_unarchived = next((index for index, message_id in enumerate(ids) if message_id not in archived), len(ids))
    if any(message_id in archived for message_id in ids[first_unarchived:]):
        return ArchivePrefixDecision(False, "noncontiguous_archive_prefix")
    if first_unarchived == len(ids):
        return ArchivePrefixDecision(False, "already_archived")

    child = bool(chat.get("is_sub_chat") or chat.get("parent_id"))
    if child:
        if not all((child_result_delivered, child_parent_consumed, child_canonical_ack, child_key_ack)):
            return ArchivePrefixDecision(False, "child_persistence_or_synthesis_pending")
        boundary = len(ordered)
        reason = "completed_child"
    else:
        if recent_main_rank is not None and recent_main_rank < 0:
            raise ValueError("recent_main_rank must be nonnegative")
        last_activity = int(chat.get("last_edited_overall_timestamp") or chat.get("updated_at") or 0)
        inactive = last_activity > 0 and last_activity <= now_timestamp - limits.inactive_days * SECONDS_PER_DAY
        outside_recent = recent_main_rank is not None and recent_main_rank >= limits.recent_main_chats
        if inactive or outside_recent:
            boundary = len(ordered)
            reason = "inactive" if inactive else "outside_recent_main"
        else:
            # Keep the newest bounded tail. The first limit reached determines
            # its length; an oversized newest row can leave an empty warm tail.
            kept = 0
            kept_bytes = 0
            for size in reversed(message_sizes):
                if kept >= limits.messages_per_chat or kept_bytes + size > limits.encrypted_message_bytes_per_chat:
                    break
                kept += 1
                kept_bytes += size
            boundary = len(ordered) - kept
            reason = "warm_tail_limit"

        if checkpoint is not None and checkpoint_canonical_ack:
            checkpoint_id = str(checkpoint.get("compressed_up_to_message_id") or "")
            checkpoint_time = checkpoint.get("compressed_up_to_timestamp")
            if checkpoint_id and checkpoint_time is not None and checkpoint.get("encrypted_summary"):
                matching = [index for index, message in enumerate(ordered) if
                            _message_id(message) == checkpoint_id and str(_message_time(message)) == str(checkpoint_time)]
                if matching:
                    checkpoint_boundary = matching[0] + 1
                    if checkpoint_boundary > boundary:
                        boundary = checkpoint_boundary
                        reason = "acknowledged_compression"
            # Legacy timestamp-only or unacknowledged checkpoints never extend
            # the archive boundary.

    boundary = max(first_unarchived, boundary)
    barrier_ids = set(pending_message_ids) | set(in_flight_message_ids)
    blocked_at = next((index for index in range(first_unarchived, boundary) if ids[index] in barrier_ids), None)
    if blocked_at is not None:
        boundary = blocked_at
    selected = ordered[first_unarchived:boundary]
    if not selected:
        return ArchivePrefixDecision(
            False, "pending_or_in_flight_prefix" if blocked_at is not None else "within_warm_limits",
            blocked_by_message_id=ids[blocked_at] if blocked_at is not None else None,
        )
    if any(not message.get("encrypted_content") for message in selected):
        return ArchivePrefixDecision(False, "unsupported_canonical_ciphertext")
    last = selected[-1]
    return ArchivePrefixDecision(
        True, reason, tuple(_message_id(message) for message in selected),
        _message_time(last), _message_id(last),
        sum(message_sizes[first_unarchived:boundary]),
        ids[blocked_at] if blocked_at is not None else None,
    )
