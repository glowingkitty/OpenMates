"""Durable admission and dispatch for an assistant turn the server starts on its own.

An automatic turn (for example the interpreting turn after a spawned chat's report,
``specifications/features/chat-orchestration/specification.yml``) has no user send that
went through ``message_received_handler``. The AI worker still refuses any saved-chat
task without durable admission ("Saved AI task lacks durable admission authority"), so
this helper does what the ordinary send path does:

1. admit the turn with the chat recovery cutover controller under the stable identity
   ``sha256("{user_id}:{chat_id}:{message_id}")``, scoped to the chat's owner and team;
2. dispatch it through the in-process ``ai.ask`` skill with ``legacy_cutover_task_id``
   set, which binds the broker task to that admission before the worker claims it.

The returned task id equals the admission identity. Callers hold the chat's active-task
marker under that id before calling and release it when this raises.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ServerTurnNotAdmitted(RuntimeError):
    """The cutover controller refused the turn; nothing was dispatched."""


def server_turn_identity(user_id: str, chat_id: str, message_id: str) -> str:
    """Stable task identity of a server-started turn (same form as an ordinary user send)."""
    return hashlib.sha256(f"{user_id}:{chat_id}:{message_id}".encode()).hexdigest()


async def admit_and_dispatch_server_turn(
    *, cache_service: Any, directus_service: Any, request: dict[str, Any],
) -> str:
    """Admit ``request`` (an ``ai.ask`` internal request dict) and dispatch it; return its task id.

    Raises ``ServerTurnNotAdmitted`` when the admission is refused or was already used, and
    ``RuntimeError`` when the dispatcher answers with another task id.
    """
    from backend.core.api.app.services.chat_recovery_cutover import ChatRecoveryCutoverController
    from backend.core.api.app.services.skill_registry import get_global_registry

    user_id, chat_id, message_id = request["user_id"], request["chat_id"], request["message_id"]
    identity = server_turn_identity(user_id, chat_id, message_id)
    metadata = await directus_service.chat.get_chat_metadata(chat_id, admin_required=True) or {}
    hashed_team_id = metadata.get("hashed_team_id") or None
    controller = ChatRecoveryCutoverController(cache_service, directus_service)
    admission = await controller.admit_legacy_inference(
        identity,
        actor_user_id=user_id,
        hashed_user_id=hashlib.sha256(user_id.encode()).hexdigest(),
        chat_id=chat_id,
        first_message_id=message_id,
        hashed_team_id=hashed_team_id,
    )
    if admission.get("admitted") is not True:
        # idempotent: this exact turn was admitted before; a second dispatch would answer twice.
        raise ServerTurnNotAdmitted(
            "server turn already admitted" if admission.get("idempotent") else "server turn not admitted"
        )
    try:
        response = await get_global_registry().dispatch_skill(
            # ai.ask binds the broker task with team_id_hash; it must match the admitted scope.
            "ai", "ask", {**request, "legacy_cutover_task_id": identity, "team_id_hash": hashed_team_id},
        )
    except Exception:
        # Nothing reached the broker: free the admission so a later attempt can run this turn.
        await controller.release_legacy_inference(identity)
        raise
    task_id = response.get("task_id") if isinstance(response, dict) else None
    if task_id != identity:
        raise RuntimeError("ai.ask returned a task id that differs from the server turn admission")
    logger.info("Server-started turn admitted and dispatched chat=%s task=%s", chat_id, task_id)
    return task_id
