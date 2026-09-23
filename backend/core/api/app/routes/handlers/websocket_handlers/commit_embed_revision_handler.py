"""Authorize and atomically publish one client-encrypted Project file revision."""

from __future__ import annotations

import logging
from typing import Any

from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.embed_version_transaction_service import (
    EmbedVersionTransactionError,
    EmbedVersionTransactionService,
)
from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError,
    ProjectWriteAuthorizationService,
)

logger = logging.getLogger(__name__)


async def _result(
    manager: ConnectionManager,
    user_id: str,
    device_fingerprint_hash: str,
    *,
    request_id: Any,
    operation_id: Any,
    embed_id: Any,
    status: str,
    **extra: Any,
) -> None:
    await manager.send_personal_message(
        {
            "type": "commit_embed_revision_result",
            "payload": {
                "request_id": request_id,
                "operation_id": operation_id,
                "embed_id": embed_id,
                "status": status,
                **extra,
            },
        },
        user_id,
        device_fingerprint_hash,
    )


async def handle_commit_embed_revision(
    *,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    user_otel_attrs: dict[str, Any] | None = None,
) -> None:
    request_id = payload.get("request_id")
    operation_id = payload.get("operation_id")
    embed_id = payload.get("embed_id")
    transaction_payload = {key: value for key, value in payload.items() if key != "request_id"}

    span, token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span

        span, token = start_ws_handler_span(
            "commit_embed_revision", user_id, payload, user_otel_attrs
        )
    except Exception:
        pass

    try:
        required = ("request_id", "operation_id", "embed_id", "project_id", "chat_id", "proposal_digest")
        if any(not isinstance(payload.get(field), str) or not payload[field] for field in required):
            await _result(
                manager, user_id, device_fingerprint_hash,
                request_id=request_id, operation_id=operation_id, embed_id=embed_id,
                status="rejected", code="invalid_request",
            )
            return

        authorization = ProjectWriteAuthorizationService(directus_service, cache_service)
        transaction = EmbedVersionTransactionService(directus_service)
        try:
            # Keep approval consumption adjacent to the durable transaction. The
            # authorization service makes identical operation retries replay-safe.
            await authorization.require_write_authorization(
                requester_user_id=user_id,
                chat_id=payload["chat_id"],
                project_id=payload["project_id"],
                operation_id=payload["operation_id"],
                proposal_digest=payload["proposal_digest"],
                team_id=payload.get("team_id"),
                consume_approval=True,
            )
            result = await transaction.commit(transaction_payload, user_id=user_id)
        except ProjectWriteAuthorizationError as exc:
            await _result(
                manager, user_id, device_fingerprint_hash,
                request_id=request_id, operation_id=operation_id, embed_id=embed_id,
                status="rejected", code=exc.code,
            )
            return
        except EmbedVersionTransactionError as exc:
            await _result(
                manager, user_id, device_fingerprint_hash,
                request_id=request_id, operation_id=operation_id, embed_id=embed_id,
                status="rejected", code=exc.code,
            )
            return

        await _result(
            manager, user_id, device_fingerprint_hash,
            request_id=request_id, operation_id=operation_id, embed_id=embed_id,
            status=result.get("status", "rejected"),
            current_revision=result.get("current_revision"),
            **({"idempotent": True} if result.get("idempotent") else {}),
        )
        if result.get("status") == "committed":
            await manager.broadcast_to_user(
                message={
                    "type": "embed_revision_committed",
                    "payload": {
                        "embed_id": embed_id,
                        "current_revision": result.get("current_revision"),
                    },
                },
                user_id=user_id,
                exclude_device_hash=device_fingerprint_hash,
            )
    except Exception:
        logger.exception("Failed to commit encrypted embed revision for user %s", user_id)
        await _result(
            manager, user_id, device_fingerprint_hash,
            request_id=request_id, operation_id=operation_id, embed_id=embed_id,
            status="rejected", code="transaction_failed",
        )
    finally:
        if span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span

                end_ws_handler_span(span, token)
            except Exception:
                pass
