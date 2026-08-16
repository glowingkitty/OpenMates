"""Team chat AI trigger helpers.

Teams V1 stores ordinary team messages without AI unless a user explicitly
mentions OpenMates. Keeping this logic pure makes CLI, SDK, WebSocket, and tests
share the same trigger contract.
"""

from dataclasses import dataclass
from typing import Any

from backend.core.api.app.schemas.chat import AIHistoryMessage
from backend.core.api.app.services.directus.team_methods import hash_id
from backend.shared.python_utils.client_ciphertext import validate_client_encrypted_chat_payload


OPENMATES_MENTION = "@openmates"


@dataclass(frozen=True)
class TeamMessageTransport:
    encrypted_content: str
    should_trigger_ai: bool
    inference_history: tuple[AIHistoryMessage, ...] | None
    mentioned_user_ids: tuple[str, ...]


def should_trigger_team_ai(message_content: str, *, is_team_chat: bool) -> bool:
    if not is_team_chat:
        return True
    return OPENMATES_MENTION in (message_content or "").casefold()


def parse_team_message_transport(payload: dict[str, Any], message_payload: dict[str, Any]) -> TeamMessageTransport:
    """Validate the split Team transport without exposing ordinary plaintext."""
    if not extract_team_ai_context(payload, message_payload)["team_id"]:
        raise ValueError("Team message transport requires team_id")

    encrypted_content = message_payload.get("encrypted_content")
    if not isinstance(encrypted_content, str):
        raise ValueError("Team messages require client ciphertext")
    validate_client_encrypted_chat_payload(str(message_payload.get("message_id") or "unknown"), encrypted_content)
    if "content" in message_payload:
        raise ValueError("Team message plaintext must not be sent in the message envelope")

    mentioned_user_ids = tuple(
        dict.fromkeys(
            user_id
            for user_id in message_payload.get("team_member_mentions", [])
            if isinstance(user_id, str) and user_id
        )
    )
    invocation = payload.get("team_ai_invocation")
    if invocation is None:
        return TeamMessageTransport(encrypted_content, False, None, mentioned_user_ids)
    if not isinstance(invocation, dict) or not isinstance(invocation.get("history"), list):
        raise ValueError("Team AI invocation requires full current chat history")

    history = tuple(AIHistoryMessage.model_validate(item) for item in invocation["history"])
    if not history or history[-1].role != "user" or not should_trigger_team_ai(history[-1].content, is_team_chat=True):
        raise ValueError("Team AI invocation history must end with an @openmates user message")
    return TeamMessageTransport(encrypted_content, True, history, mentioned_user_ids)


def format_sender_attributed_content(content: str, sender_name: str | None) -> str:
    if not sender_name:
        return content
    return f"[{sender_name}]: {content}"


def extract_team_ai_context(payload: dict[str, Any], message_payload: dict[str, Any]) -> dict[str, str | None]:
    team_id = payload.get("team_id") or message_payload.get("team_id")
    if not isinstance(team_id, str) or not team_id:
        return {"team_id": None, "team_id_hash": None, "team_workspace_type": None, "team_object_id_hash": None}
    team_id_hash = hash_id(team_id)
    workspace_type = payload.get("team_workspace_type") or message_payload.get("team_workspace_type") or "chat"
    object_id_hash = payload.get("team_object_id_hash") or message_payload.get("team_object_id_hash")
    if not isinstance(object_id_hash, str) and workspace_type == "chat":
        chat_id = payload.get("chat_id") or message_payload.get("chat_id")
        object_id_hash = hash_id(chat_id) if isinstance(chat_id, str) and chat_id else None
    return {
        "team_id": team_id,
        "team_id_hash": team_id_hash,
        "team_workspace_type": workspace_type if isinstance(workspace_type, str) else "chat",
        "team_object_id_hash": object_id_hash if isinstance(object_id_hash, str) else None,
    }
