"""Commit ciphertext revisions built by a hosted Project sandbox, never over a newer revision."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException

from backend.core.api.app.services.embed_version_transaction_service import (
    EmbedVersionTransactionError,
    EmbedVersionTransactionService,
)
from backend.core.api.app.services.project_sandbox_service import ProjectSandboxHandle
from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError,
    ProjectWriteAuthorizationService,
)
from backend.shared.providers.e2b_project_sandbox import ProjectSandboxError

logger = logging.getLogger(__name__)

MAX_MERGE_ATTEMPTS = 3
COMMITTED_EVENT = "send_embed_revision_committed"
Publisher = Callable[[str, dict], Awaitable[None]]
HeadLoader = Callable[..., Awaitable[dict]]


@dataclass
class WritebackResult:
    """Outcome of committing the revisions of one sandbox operation (paths and codes only, no content)."""

    committed: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    conflicts: list[dict[str, str]] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {"committed": self.committed, "merged": self.merged,
                "conflicts": self.conflicts, "rejected": self.rejected}


def cache_event_publisher(cache_service: Any, user_id: str) -> Publisher:
    """Publish to the user's devices over the Redis fan-out that works from a Celery worker."""

    async def publish(event_type: str, payload: dict) -> None:
        redis = await cache_service.client
        if redis:
            await redis.publish(f"user_cache_events:{user_id}",
                                json.dumps({"event_type": event_type, "payload": payload}))

    return publish


ITEM_ACTIONS = {"delete": "delete", "move": "rename"}


def _own_digest(transaction: dict) -> str:
    """The sandbox's Project-key HMAC, passed through unchanged (never recomputed server-side)."""
    digest = transaction.get("proposal_digest")
    return digest if isinstance(digest, str) else ""


async def commit_revisions(
    handle: ProjectSandboxHandle, revisions: list[dict], *, user_id: str, chat_id: str, project_id: str,
    team_id: Optional[str], operation_id: str, directus_service: Any, cache_service: Any,
    connection_manager_publish: Optional[Publisher] = None, head_loader: Optional[HeadLoader] = None,
) -> WritebackResult:
    """Apply the revisions strictly in order; each is followed by ``/v1/committed`` before the next.

    After a failure, later revisions of the same path are skipped: they were built on the base that
    was not committed.
    """
    publish = connection_manager_publish or cache_event_publisher(cache_service, user_id)
    authorization = ProjectWriteAuthorizationService(directus_service, cache_service)
    transactions = EmbedVersionTransactionService(directus_service)
    result = WritebackResult()
    failed_paths: set[str] = set()
    for rev in revisions:
        path = str(rev.get("path") or "")
        embed_id = str(rev.get("embed_id") or "")
        kind = str(rev.get("kind") or "update")
        transaction = rev.get("transaction")
        if not path or not isinstance(transaction, dict) or (kind not in ITEM_ACTIONS and not embed_id):
            result.rejected.append({"path": path, "code": "invalid_revision"})
            continue
        if path in failed_paths:
            result.rejected.append({"path": path, "code": "skipped_after_failure"})
            continue
        before = len(result.rejected) + len(result.conflicts)
        common = dict(user_id=user_id, chat_id=chat_id, project_id=project_id, team_id=team_id,
                      operation_id=operation_id, authorization=authorization, publish=publish)
        if kind in ITEM_ACTIONS:
            await _apply_item_transaction(handle, rev, path, kind, dict(transaction), result,
                                          directus_service=directus_service, **common)
        else:
            await _commit_one(handle, rev, path, embed_id, kind, dict(transaction), result,
                              directus_service=directus_service, transactions=transactions,
                              head_loader=head_loader, **common)
        if len(result.rejected) + len(result.conflicts) > before:
            failed_paths.add(path)
    return result


async def _authorize(authorization, *, user_id, chat_id, project_id, team_id, operation_id, digest) -> None:
    await authorization.authorize_sandbox_write(
        user_id=user_id, chat_id=chat_id, project_id=project_id, operation_id=operation_id,
        proposal_digest=digest, team_id=team_id)
    await authorization.consume_sandbox_write(
        user_id=user_id, chat_id=chat_id, project_id=project_id, operation_id=operation_id,
        proposal_digest=digest, team_id=team_id)


async def _apply_item_transaction(handle, rev, path, kind, transaction, result, *, user_id, chat_id,
                                  project_id, team_id, operation_id, directus_service, authorization,
                                  publish) -> None:
    """Delete or move: the Project-item rename/delete route logic, called directly with its checks."""
    from backend.core.api.app.routes.project_item_links import apply_item_link_operation

    action = transaction.get("action")
    body = transaction.get("body")
    item_id = transaction.get("item_id")
    digest = _own_digest(transaction)
    if action != ITEM_ACTIONS[kind] or not isinstance(body, dict) or not isinstance(item_id, str) or not digest:
        result.rejected.append({"path": path, "code": "invalid_revision"})
        return
    op_id = str(body.get("operation_id") or operation_id)
    try:
        await _authorize(authorization, user_id=user_id, chat_id=chat_id, project_id=project_id,
                         team_id=team_id, operation_id=op_id, digest=digest)
        await apply_item_link_operation(
            directus_service, action, project_id=project_id, project_item_id=item_id, body=body,
            user_id=user_id, team_id=team_id)
    except ProjectWriteAuthorizationError as exc:
        logger.warning("Sandbox write-back rejected: code=%s", exc.code)
        result.rejected.append({"path": path, "code": exc.code})
        return
    except HTTPException as exc:
        logger.warning("Sandbox %s rejected (status %s)", kind, exc.status_code)
        result.rejected.append({"path": path, "code": str(exc.detail)})
        return
    result.committed.append(path)
    await _after_commit(handle, publish, path, str(rev.get("embed_id") or ""), None, chat_id=chat_id,
                        operation_id=op_id, kind=kind, tell_daemon=False)


async def _commit_one(handle, rev, path, embed_id, kind, transaction, result, *, user_id, chat_id,
                      project_id, team_id, operation_id, directus_service, authorization, transactions,
                      publish, head_loader) -> None:
    merged = False
    for _attempt in range(MAX_MERGE_ATTEMPTS):
        digest = _own_digest(transaction)
        if not digest:
            result.rejected.append({"path": path, "code": "invalid_revision"})
            return
        op_id = str(transaction.get("operation_id") or operation_id)
        payload = {**transaction, "operation_id": op_id, "embed_id": embed_id, "project_id": project_id,
                   "chat_id": chat_id, "proposal_digest": digest}
        if team_id:
            payload["team_id"] = team_id
        else:
            payload.pop("team_id", None)
        try:
            await _authorize(authorization, user_id=user_id, chat_id=chat_id, project_id=project_id,
                             team_id=team_id, operation_id=op_id, digest=digest)
            outcome = await transactions.commit_sandbox_revision(payload, user_id=user_id)
        except (ProjectWriteAuthorizationError, EmbedVersionTransactionError) as exc:
            logger.warning("Sandbox write-back rejected: code=%s", exc.code)
            result.rejected.append({"path": path, "code": exc.code})
            return
        if outcome.get("status") == "committed":
            (result.merged if merged else result.committed).append(path)
            await _after_commit(handle, publish, path, embed_id, outcome.get("current_revision"),
                                chat_id=chat_id, operation_id=op_id, kind="update" if merged else kind)
            return
        # Stale base: another device committed first. Merge on top of its head, never over it.
        head = await _load_head(head_loader, directus_service, user_id, project_id, embed_id, team_id)
        if head is None:
            result.rejected.append({"path": path, "code": "head_unavailable"})
            return
        try:
            answer = await handle.client.call("/v1/merge", {"path": path, "head": head})
        except ProjectSandboxError as exc:
            result.rejected.append({"path": path, "code": f"merge_{exc.code}"})
            return
        if answer.get("status") == "merged":
            merged = True
            revision = answer.get("revision")
            if not isinstance(revision, dict):
                # The local file simply took the other device's head: nothing to commit.
                result.merged.append(path)
                return
            transaction = dict(revision.get("transaction") or {})
            continue
        result.conflicts.append({"path": path, "conflict_text": str(answer.get("conflict_text") or "")})
        return
    result.rejected.append({"path": path, "code": "merge_retries_exhausted"})

async def _load_head(head_loader, directus_service, user_id, project_id, embed_id, team_id):
    loader = head_loader
    if loader is None:
        from backend.core.api.app.routes.embeds_api import build_project_embed_head as loader
    try:
        return await loader(directus_service=directus_service, user_id=user_id, project_id=project_id,
                            embed_id=embed_id, team_id=team_id)
    except HTTPException as exc:
        logger.warning("Sandbox write-back could not load the newer head (status %s)", exc.status_code)
        return None


async def _after_commit(handle, publish, path, embed_id, version, *, chat_id, operation_id, kind,
                        tell_daemon: bool = True) -> None:
    if tell_daemon and version is not None:
        try:
            await handle.client.call("/v1/committed",
                                     {"path": path, "embed_id": embed_id, "version_number": version})
        except ProjectSandboxError as exc:
            logger.warning("Sandbox daemon did not take the committed base: %s", exc.code)
    # No path and no content: the client decrypts the embed itself.
    await publish(COMMITTED_EVENT, {
        "embed_id": embed_id, "current_revision": version, "operation_id": operation_id,
        "chat_id": chat_id, "kind": kind, "source": "project_sandbox"})
