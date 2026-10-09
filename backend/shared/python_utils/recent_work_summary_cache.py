"""Process-local Vault ciphertexts for authorized active/recent chat summaries.

This deliberately has no Redis, database, filesystem or transcript fallback. A
worker restart loses the cache. Only actual processing writes renew eligibility;
navigation and reads cannot do so. Callers must pass server-verified authorization.
"""

from __future__ import annotations

import time
import math
import asyncio
import secrets
import json
from dataclasses import dataclass, field
from typing import Callable, Collection, Protocol

RECENT_WORK_WINDOW_SECONDS = 30 * 60
MAX_SUMMARY_CHARS = 4_000


class SummaryEncryption(Protocol):
    async def encrypt_with_user_key(self, plaintext: str, key_id: str) -> tuple[str, str]: ...
    async def decrypt_with_user_key(self, ciphertext: str, key_id: str) -> str | None: ...


@dataclass(frozen=True)
class SummarySource:
    """Content-free provenance; project_id never grants Project access."""

    owner_id: str
    chat_id: str
    project_id: str | None
    revision: str
    source_updated_at: float
    assistant_completed_at: float | None
    active: bool
    expires_at: float
    active_task_id: str | None = None
    source_kind: str = "authorized_processing_summary"


@dataclass(frozen=True)
class RecentChatSummary:
    source: SummarySource
    text: str = field(repr=False)


@dataclass(frozen=True)
class _EncryptedSummary:
    source: SummarySource
    vault_key_id: str = field(repr=False)
    ciphertext: str = field(repr=False)


@dataclass(frozen=True)
class SummaryCompletionPermit:
    turn_id: str
    owner_id: str
    chat_id: str
    task_id: str
    revision: str
    assistant_completed_at: float
    expires_at: float


class RecentWorkSummaryCache:
    """Bounded memory-only cache, isolated by owner and chat.

    ``active`` means an authorized inference is doing actual work, not that a chat
    is open in navigation. A completed response uses its completion timestamp as
    the expiry anchor. Explicit dependencies do not resurrect expired ciphertext.
    """

    def __init__(self, *, clock: Callable[[], float] = time.time, max_entries: int = 512):
        if max_entries < 1:
            raise ValueError("Summary cache capacity must be positive")
        self._clock = clock
        self._max_entries = max_entries
        self._entries: dict[tuple[str, str], _EncryptedSummary] = {}
        self._revocation_generation = 0
        self._expiry_handles: dict[tuple[str, str], asyncio.TimerHandle] = {}
        self._completion_permits: dict[str, SummaryCompletionPermit] = {}
        self._permit_handles: dict[str, asyncio.TimerHandle] = {}

    def _remove_permit(self, ticket: str) -> None:
        self._completion_permits.pop(ticket, None)
        handle = self._permit_handles.pop(ticket, None)
        if handle:
            handle.cancel()

    def mint_completion_permit(self, *, owner_id: str, chat_id: str, task_id: str,
                               revision: str, turn_id: str) -> str:
        """Called only after live owner/current-task validation before final delivery."""
        now = self._clock()
        if len(self._completion_permits) >= self._max_entries:
            self._remove_permit(next(iter(self._completion_permits)))
        ticket = secrets.token_urlsafe(32)
        self._completion_permits[ticket] = SummaryCompletionPermit(
            turn_id, owner_id, chat_id, task_id, revision, now, now + 120,
        )
        self._permit_handles[ticket] = asyncio.get_running_loop().call_later(120, self._remove_permit, ticket)
        return ticket

    def completion_permit(self, ticket: str, *, owner_id: str, chat_id: str,
                          task_id: str, revision: str) -> SummaryCompletionPermit | None:
        permit = self._completion_permits.get(ticket)
        if permit and permit.expires_at <= self._clock():
            self._remove_permit(ticket)
            return None
        if permit and (permit.owner_id, permit.chat_id, permit.task_id, permit.revision) == (owner_id, chat_id, task_id, revision):
            return permit
        return None

    def consume_completion_permit(self, ticket: str) -> None:
        self._remove_permit(ticket)

    def discard_revision(self, *, owner_id: str, chat_id: str, revision: str) -> None:
        """Discard a stale writer's own result without deleting a newer source."""
        key = (owner_id, chat_id)
        entry = self._entries.get(key)
        if entry and entry.source.revision == revision:
            self._remove(key)

    def _remove(self, key: tuple[str, str]) -> None:
        self._entries.pop(key, None)
        handle = self._expiry_handles.pop(key, None)
        if handle:
            handle.cancel()

    def prune(self) -> None:
        now = self._clock()
        for key, entry in list(self._entries.items()):
            if entry.source.expires_at <= now:
                self._remove(key)

    async def put(
        self, *, owner_id: str, chat_id: str, project_id: str | None,
        revision: str, text: str, vault_key_id: str, encryption: SummaryEncryption,
        authorized: bool, active: bool = False, assistant_completed_at: float | None = None,
        source_updated_at: float | None = None, active_task_id: str | None = None,
        source_kind: str = "authorized_processing_summary",
    ) -> bool:
        """Encrypt a transient authorized processing summary; refuse stale sources."""
        now = self._clock()
        updated = now if source_updated_at is None else source_updated_at
        anchor = updated if active else assistant_completed_at
        if (
            not authorized or not owner_id or not chat_id or not vault_key_id
            or not revision or not isinstance(text, str) or not text.strip()
            or not math.isfinite(updated) or anchor is not None and not math.isfinite(anchor)
            or updated > now or anchor is None or anchor > now
            or anchor + RECENT_WORK_WINDOW_SECONDS <= now
        ):
            return False
        key = (owner_id, chat_id)
        generation = self._revocation_generation
        previous = self._entries.get(key)
        if previous and previous.source.source_updated_at > updated:
            return False
        # No plaintext remains in the resident record, including its repr.
        ciphertext, _version = await encryption.encrypt_with_user_key(text.strip()[:MAX_SUMMARY_CHARS], vault_key_id)
        if not isinstance(ciphertext, str) or not ciphertext.startswith("vault:v"):
            return False
        if self._revocation_generation != generation:
            return False
        current = self._entries.get(key)
        if current is not previous:
            return False  # A newer concurrent source won; never overwrite it.
        expires_at = anchor + RECENT_WORK_WINDOW_SECONDS
        if expires_at <= self._clock():
            return False
        self.prune()
        if key not in self._entries and len(self._entries) >= self._max_entries:
            oldest = min(self._entries, key=lambda candidate: self._entries[candidate].source.expires_at)
            self._remove(oldest)
        self._remove(key)
        self._entries[key] = _EncryptedSummary(
            SummarySource(owner_id, chat_id, project_id, revision, updated,
                          assistant_completed_at, active, expires_at, active_task_id, source_kind),
            vault_key_id, ciphertext,
        )
        # A single expiry callback deletes idle ciphertext; no content-bearing
        # job or recurring inference/direction poll is scheduled.
        self._expiry_handles[key] = asyncio.get_running_loop().call_later(
            expires_at - self._clock(), self._remove, key,
        )
        return True

    def mark_active(self, *, owner_id: str, chat_id: str, vault_key_id: str, task_id: str) -> bool:
        """Renew work activity from an authorized processing boundary, never a read."""
        key = (owner_id, chat_id)
        entry = self._entries.get(key)
        now = self._clock()
        if not entry or entry.source.expires_at <= now or entry.vault_key_id != vault_key_id:
            return False
        from dataclasses import replace
        self._remove(key)
        self._entries[key] = _EncryptedSummary(replace(entry.source, active=True, active_task_id=task_id,
            source_updated_at=now, expires_at=now + RECENT_WORK_WINDOW_SECONDS), entry.vault_key_id, entry.ciphertext)
        self._expiry_handles[key] = asyncio.get_running_loop().call_later(RECENT_WORK_WINDOW_SECONDS, self._remove, key)
        return True

    def candidates(self, *, owner_id: str, authorized_chat_ids: Collection[str]) -> list[SummarySource]:
        """Inspect only eligible authorized metadata without decryption or renewal."""
        self.prune()
        allowed = set(authorized_chat_ids)
        return [entry.source for (owner, chat), entry in self._entries.items()
                if owner == owner_id and chat in allowed]

    async def get(
        self, *, owner_id: str, chat_id: str, authorized_chat_ids: Collection[str],
        vault_key_id: str, encryption: SummaryEncryption,
    ) -> RecentChatSummary | None:
        """Read a still-authorized copy; a miss remains a miss."""
        self.prune()
        key = (owner_id, chat_id)
        entry = self._entries.get(key)
        if chat_id not in authorized_chat_ids or entry is None or entry.vault_key_id != vault_key_id:
            return None
        plaintext = await encryption.decrypt_with_user_key(entry.ciphertext, vault_key_id)
        # Revocation, replacement and expiry may happen during Vault I/O.
        if self._entries.get(key) is not entry or entry.source.expires_at <= self._clock():
            self.prune()
            return None
        if not isinstance(plaintext, str) or not plaintext.strip():
            return None
        return RecentChatSummary(entry.source, plaintext[:MAX_SUMMARY_CHARS])

    def revoke_chat(self, *, owner_id: str, chat_id: str) -> None:
        """Delete on chat deletion, access revocation or owner logout."""
        key = (owner_id, chat_id)
        self._remove(key)
        self._revocation_generation += 1
        transient_context_handoff_store.revoke(owner_id=owner_id, chat_id=chat_id)
        for ticket, permit in list(self._completion_permits.items()):
            if permit.owner_id == owner_id and permit.chat_id == chat_id:
                self._remove_permit(ticket)

    def revoke_owner(self, owner_id: str) -> None:
        # Also fences an in-flight write when no resident entry exists yet.
        self._revocation_generation += 1
        transient_context_handoff_store.revoke(owner_id=owner_id)
        for owner, chat in list(self._entries):
            if owner == owner_id:
                self.revoke_chat(owner_id=owner, chat_id=chat)
        for ticket, permit in list(self._completion_permits.items()):
            if permit.owner_id == owner_id:
                self._remove_permit(ticket)


# Separate from the existing Redis-backed 72-hour full-message cache.
recent_work_summary_cache = RecentWorkSummaryCache()

PRIVATE_CONTEXT_FIELDS = frozenset({
    "accepted_plan_context",
    "custom_rule_documents", "project_focus_catalog", "project_focus_documents",
    "project_context_documents", "related_task_candidates",
    "async_tool_completion",
    "async_tool_history",
})


@dataclass(frozen=True)
class _ContextHandoff:
    owner_id: str
    chat_id: str
    turn_id: str
    request_id: str
    expires_at: float
    ciphertext: str = field(repr=False)
    vault_key_id: str = field(repr=False)
    project_binding: tuple[str, str] | None = None


class TransientContextHandoffStore:
    """API-only Vault ciphertext handoffs; queues carry random references only."""

    def __init__(self, *, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._entries: dict[str, _ContextHandoff] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self._revocation_generation = 0

    def _remove(self, reference: str) -> None:
        self._entries.pop(reference, None)
        timer = self._timers.pop(reference, None)
        if timer:
            timer.cancel()

    async def seal(self, *, owner_id: str, chat_id: str, turn_id: str, request_id: str,
                   fields: dict, encryption: SummaryEncryption, vault_key_id: str,
                   project_binding: tuple[str, str] | None = None) -> str | None:
        if set(fields) - PRIVATE_CONTEXT_FIELDS:
            return None
        text = json.dumps(fields, ensure_ascii=False)
        if len(text.encode()) > 200_000:
            return None
        generation = self._revocation_generation
        ciphertext, _ = await encryption.encrypt_with_user_key(text, vault_key_id)
        if not ciphertext.startswith("vault:v") or generation != self._revocation_generation:
            return None
        if len(self._entries) >= 256:
            self._remove(next(iter(self._entries)))
        reference = secrets.token_urlsafe(32)
        self._entries[reference] = _ContextHandoff(owner_id, chat_id, turn_id, request_id,
            self._clock() + 1200, ciphertext, vault_key_id, project_binding)
        self._timers[reference] = asyncio.get_running_loop().call_later(1200, self._remove, reference)
        return reference

    def project_binding(self, reference: str) -> tuple[str, str] | None:
        entry = self._entries.get(reference)
        return entry.project_binding if entry else None

    async def open(self, reference: str, *, owner_id: str, chat_id: str, turn_id: str,
                   request_id: str, encryption: SummaryEncryption, vault_key_id: str) -> dict | None:
        entry = self._entries.get(reference)
        if not entry:
            return None
        if entry.expires_at <= self._clock():
            self._remove(reference)
            return None
        if (entry.owner_id, entry.chat_id, entry.turn_id, entry.request_id, entry.vault_key_id) != (owner_id, chat_id, turn_id, request_id, vault_key_id):
            return None
        plaintext = await encryption.decrypt_with_user_key(entry.ciphertext, vault_key_id)
        if self._entries.get(reference) is not entry or entry.expires_at <= self._clock():
            return None
        value = json.loads(plaintext) if plaintext else None
        return value if isinstance(value, dict) and not set(value) - PRIVATE_CONTEXT_FIELDS else None

    def revoke(self, *, owner_id: str, chat_id: str | None = None) -> None:
        self._revocation_generation += 1
        for reference, entry in list(self._entries.items()):
            if entry.owner_id == owner_id and (chat_id is None or entry.chat_id == chat_id):
                self._remove(reference)


transient_context_handoff_store = TransientContextHandoffStore()
