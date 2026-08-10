"""
Durable coordination for the chat recovery protocol cutover.

Directus serializes every mutation on one authoritative singleton row. Redis
contains only a replaceable read-through snapshot and never admits work.
"""

import logging
from typing import Any

from backend.core.api.app.services.chat_recovery_service import (
    ChatRecoveryProtocolError,
    ChatRecoveryService,
)

logger = logging.getLogger(__name__)


def legacy_completion_requires_persistence(task_result: Any) -> bool:
    return (
        isinstance(task_result, dict)
        and task_result.get("_celery_task_state") == "SUCCESS"
        and task_result.get("main_processing_output") is not None
        and not task_result.get("interrupted_by_soft_time_limit", False)
        and not task_result.get("interrupted_by_revocation", False)
    )


class CutoverBlockedError(RuntimeError):
    """Raised when protocol activation prerequisites are not satisfied."""


class EpochRollbackError(RuntimeError):
    """Raised when a caller attempts to lower the recorded protocol epoch."""


class ChatRecoveryCutoverController:
    STATE_CACHE_KEY = "chat_recovery:cutover:state"
    EPOCH_ONE = 1
    UPDATE_REQUIRED_MESSAGE = (
        "Please update OpenMates before sending another saved chat message."
    )

    def __init__(self, cache_service: Any, directus_service: Any) -> None:
        self.cache_service = cache_service
        self.recovery_service = ChatRecoveryService(directus_service)

    async def _cache_state(self, state: dict[str, Any]) -> None:
        try:
            cached = await self.cache_service.set(self.STATE_CACHE_KEY, state)
        except Exception:
            logger.warning("Failed to refresh replaceable chat recovery cutover cache", exc_info=True)
            return
        if not cached:
            logger.warning("Failed to refresh replaceable chat recovery cutover cache")

    async def get_state(self, *, authoritative: bool = False) -> dict[str, Any]:
        if not authoritative:
            try:
                cached = await self.cache_service.get(self.STATE_CACHE_KEY)
            except Exception:
                logger.warning("Chat recovery cutover cache read failed; reading authority", exc_info=True)
                cached = None
            if isinstance(cached, dict) and all(
                key in cached for key in ("protocol_epoch", "sends_paused", "legacy_in_flight")
            ):
                return cached
        state = await self.recovery_service.execute(
            "get_cutover_state", {"protocol_version": 1}
        )
        await self._cache_state(state)
        return state

    async def get_epoch(self, *, authoritative: bool = False) -> int:
        return int(
            (await self.get_state(authoritative=authoritative)).get("protocol_epoch", 0)
        )

    async def admit_legacy_inference(self, task_identity: str) -> dict[str, Any]:
        result = await self.recovery_service.execute(
            "admit_legacy_inference",
            {"protocol_version": 1, "task_identity": task_identity},
        )
        await self._cache_state(result)
        return result

    async def release_legacy_inference(self, task_identity: str) -> dict[str, Any]:
        result = await self.recovery_service.execute(
            "release_legacy_inference",
            {"protocol_version": 1, "task_identity": task_identity},
        )
        await self._cache_state(result)
        return result

    async def mark_legacy_inference_completed(
        self, task_identity: str
    ) -> dict[str, Any]:
        result = await self.recovery_service.execute(
            "mark_legacy_inference_completed",
            {"protocol_version": 1, "task_identity": task_identity},
        )
        await self._cache_state(result)
        return result

    async def authorize_legacy_completion(
        self, task_identity: str
    ) -> dict[str, Any]:
        return await self.recovery_service.execute(
            "authorize_legacy_completion",
            {"protocol_version": 1, "task_identity": task_identity},
        )

    async def set_sends_paused(self, paused: bool) -> dict[str, Any]:
        result = await self.recovery_service.execute(
            "set_sends_paused", {"protocol_version": 1, "sends_paused": paused}
        )
        await self._cache_state(result)
        return result

    async def activate_epoch_one(self, connection_manager: Any) -> None:
        await self.recovery_service.execute(
            "cleanup_expired", {"protocol_version": 1}
        )
        state = await self.get_state(authoritative=True)
        if state["legacy_in_flight"] != 0:
            raise CutoverBlockedError(
                f"Cannot activate epoch 1 with {state['legacy_in_flight']} legacy turns in flight"
            )
        if not state["sends_paused"]:
            raise CutoverBlockedError("Cannot activate epoch 1 while saved-chat sends are enabled")

        error_frame = {
            "type": "error",
            "payload": {
                "code": "client_update_required",
                "message": self.UPDATE_REQUIRED_MESSAGE,
            },
        }
        for user_connections in list(connection_manager.active_connections.values()):
            for websocket in list(user_connections.values()):
                await websocket.send_json(error_frame)
                await websocket.close(code=1012, reason="Client update required")

        try:
            result = await self.recovery_service.execute(
                "activate_protocol_epoch",
                {"protocol_version": 1, "target_epoch": self.EPOCH_ONE},
            )
        except ChatRecoveryProtocolError as exc:
            if exc.code == "protocol_epoch_rollback":
                raise EpochRollbackError("Protocol epoch cannot be lowered") from exc
            raise CutoverBlockedError(f"Protocol activation rejected: {exc.code}") from exc
        await self._cache_state(result)
