"""UUID check for chat ids that may be non-UUID (incognito / external API chats)."""
import uuid


def is_valid_uuid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False
