"""Team chat AI trigger helpers.

Teams V1 stores ordinary team messages without AI unless a user explicitly
mentions OpenMates. Keeping this logic pure makes CLI, SDK, WebSocket, and tests
share the same trigger contract.
"""

OPENMATES_MENTION = "@openmates"


def should_trigger_team_ai(message_content: str, *, is_team_chat: bool) -> bool:
    if not is_team_chat:
        return True
    return OPENMATES_MENTION in (message_content or "").casefold()


def format_sender_attributed_content(content: str, sender_name: str | None) -> str:
    if not sender_name:
        return content
    return f"[{sender_name}]: {content}"
