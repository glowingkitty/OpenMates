# backend/apps/ai/processing/orchestration_skill_gate.py
#
# Which async skill calls the orchestration gate in main_processor lets through,
# and how a refused call's processing placeholder is settled.
#
# Async skills are refused inside sub-chat orchestrations because their workers
# bill outside the orchestration reservation ledger. A root turn also carries an
# orchestration id as soon as start_sub_chats is offered, even when no child is
# ever spawned, which used to refuse every Code Run of an ordinary coding turn.
# A root-turn Code Run is the user's own request, not cascading sub-chat work:
# on the user's machine the server only opens a review, and in E2B it is billed
# per started minute against the user's credits under the Code Run per-turn
# limits (code-run.billing.rate-limits), exactly as before orchestration roots
# existed. Sub-chats stay refused. Spec: feature.app-skill.code-run
# code-run.execution.wait-or-continue, code-run.cloud.commands.

from __future__ import annotations

from typing import Any

BLOCKED_IN_ORCHESTRATION_MESSAGE = (
    "Long-running background skills are unavailable inside bounded sub-chat trees."
)


def is_root_turn_code_run(request_data: Any, app_id: str, skill_id: str) -> bool:
    """Return True for a Code Run call of the root turn (not a sub-chat)."""
    if (app_id, skill_id) != ("code", "run"):
        return False
    return not getattr(request_data, "is_sub_chat", False) and not getattr(request_data, "sub_chat_depth", 0)


async def settle_blocked_placeholders(
    placeholder_embed_data: dict[str, Any] | None,
    *,
    embed_service: Any,
    app_id: str,
    skill_id: str,
    request_data: Any,
    user_vault_key_id: str,
    task_id: str,
    log_prefix: str,
) -> list[str]:
    """Move the refused call's processing placeholder(s) to error status.

    Without this the inline "Processing…" card stays open forever, because no
    worker exists that would ever finish it. Returns the settled embed ids.
    """
    if not placeholder_embed_data:
        return []
    placeholders = (
        placeholder_embed_data.get("placeholders", [])
        if placeholder_embed_data.get("multiple") else [placeholder_embed_data]
    )
    settled: list[str] = []
    for placeholder in placeholders:
        embed_id = placeholder.get("embed_id")
        if not embed_id:
            continue
        await embed_service.update_embed_status_to_error(
            embed_id=embed_id,
            app_id=app_id,
            skill_id=skill_id,
            error_message=BLOCKED_IN_ORCHESTRATION_MESSAGE,
            chat_id=request_data.chat_id,
            message_id=request_data.message_id,
            user_id=request_data.user_id,
            user_id_hash=request_data.user_id_hash,
            user_vault_key_id=user_vault_key_id,
            task_id=task_id,
            log_prefix=log_prefix,
        )
        settled.append(embed_id)
    return settled
