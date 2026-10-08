"""Team chat AI trigger helpers.

Teams V1 stores ordinary team messages without AI unless a user explicitly
mentions OpenMates or a configured Mate. Keeping this logic pure makes CLI, SDK, WebSocket, and tests
share the same trigger contract.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Any

from backend.apps.ai.utils.mate_utils import load_mates_config
from backend.core.api.app.schemas.chat import AIHistoryMessage
from backend.core.api.app.services.directus.team_methods import hash_id
from backend.shared.python_utils.client_ciphertext import validate_client_encrypted_chat_payload


_OPENMATES_MENTION = re.compile(r"(?<![\w@])@openmates(?![\w-])", re.IGNORECASE)
_MATE_MENTION = re.compile(r"(?<![\w@])@mate:([a-z0-9_-]+)(?![\w-])", re.IGNORECASE)


@lru_cache(maxsize=1)
def _known_mate_ids() -> frozenset[str]:
    mates_dir = Path(__file__).resolve().parents[4] / "apps" / "ai" / "mates"
    return frozenset(mate.category.casefold() for mate in load_mates_config(str(mates_dir)))


@dataclass(frozen=True)
class TeamMessageTransport:
    encrypted_content: str
    should_trigger_ai: bool
    inference_history: tuple[AIHistoryMessage, ...] | None
    mentioned_user_ids: tuple[str, ...]

    @property
    def ai_sender_name(self) -> str | None:
        """Keep the invoking human's name when the encrypted turn invokes AI."""
        return self.inference_history[-1].sender_name if self.inference_history else None


def should_trigger_team_ai(message_content: str, *, is_team_chat: bool) -> bool:
    if not is_team_chat:
        return True
    content = message_content or ""
    if _OPENMATES_MENTION.search(content):
        return True
    known_ids = _known_mate_ids()
    return any(match.group(1).casefold() in known_ids for match in _MATE_MENTION.finditer(content))


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
        raise ValueError("Team AI invocation history must end with an @openmates or known Mate mention")
    return TeamMessageTransport(encrypted_content, True, history, mentioned_user_ids)


def normalize_team_ai_inference_request(inference_request: dict[str, Any]) -> dict[str, Any]:
    """Bind the same validated Team history at preflight and inference enqueue.

    The client supplies compact history objects. The receive handler later uses
    AIHistoryMessage objects whose JSON form includes optional null fields.
    Canonicalizing both requests here keeps the commitment stable without
    excluding either the invocation or plaintext history from the HMAC.
    """
    message = inference_request.get("message")
    if not isinstance(message, dict):
        raise ValueError("Team AI inference requires a message envelope")
    transport = parse_team_message_transport(inference_request, message)
    if not transport.should_trigger_ai or transport.inference_history is None:
        raise ValueError("Team AI inference requires a valid invocation")
    canonical_history = [item.model_dump(mode="json") for item in transport.inference_history]
    submitted_history = inference_request.get("message_history")
    if submitted_history is not None:
        if not isinstance(submitted_history, list):
            raise ValueError("Team AI message history must be an array")
        allowed_fields = set(AIHistoryMessage.model_fields)
        if any(not isinstance(item, dict) or set(item) - allowed_fields for item in submitted_history):
            raise ValueError("Team AI message history has unsupported fields")
        try:
            submitted_canonical = [AIHistoryMessage.model_validate(item).model_dump(mode="json")
                                   for item in submitted_history]
        except ValueError as exc:
            raise ValueError("Team AI message history is invalid") from exc
        if submitted_canonical != canonical_history:
            raise ValueError("Team AI message history differs from the invocation")
    return {**inference_request, "message_history": canonical_history}


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
