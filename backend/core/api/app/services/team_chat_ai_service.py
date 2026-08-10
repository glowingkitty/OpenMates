"""Team chat AI trigger helpers.

Teams V1 stores ordinary team messages without AI unless a user explicitly
mentions OpenMates. Keeping this logic pure makes CLI, SDK, WebSocket, and tests
share the same trigger contract.
"""

from typing import Any

from backend.core.api.app.services.directus.team_methods import hash_id


OPENMATES_MENTION = "@openmates"


def should_trigger_team_ai(message_content: str, *, is_team_chat: bool) -> bool:
    if not is_team_chat:
        return True
    return OPENMATES_MENTION in (message_content or "").casefold()


def format_sender_attributed_content(content: str, sender_name: str | None) -> str:
    if not sender_name:
        return content
    return f"[{sender_name}]: {content}"


def extract_team_ai_context(payload: dict[str, Any], message_payload: dict[str, Any]) -> dict[str, str | None]:
    team_id = payload.get("team_id") or message_payload.get("team_id")
    if not isinstance(team_id, str) or not team_id:
        return {"team_id": None, "team_id_hash": None, "team_workspace_type": None, "team_object_id_hash": None}
    team_id_hash = payload.get("team_id_hash") or hash_id(team_id)
    workspace_type = payload.get("team_workspace_type") or message_payload.get("team_workspace_type") or "chat"
    object_id_hash = payload.get("team_object_id_hash") or message_payload.get("team_object_id_hash")
    if not isinstance(object_id_hash, str) and workspace_type == "chat":
        chat_id = payload.get("chat_id") or message_payload.get("chat_id")
        object_id_hash = hash_id(chat_id) if isinstance(chat_id, str) and chat_id else None
    return {
        "team_id": team_id,
        "team_id_hash": team_id_hash if isinstance(team_id_hash, str) else hash_id(team_id),
        "team_workspace_type": workspace_type if isinstance(workspace_type, str) else "chat",
        "team_object_id_hash": object_id_hash if isinstance(object_id_hash, str) else None,
    }
