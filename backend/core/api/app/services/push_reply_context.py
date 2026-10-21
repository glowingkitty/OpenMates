"""Strict server-owned routing for encrypted native notification replies.

This is routing metadata, never reply authorization. The app must revalidate its
current authenticated account/profile and exact chat/message before sending.
"""
import base64
import hashlib
import re
import uuid


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HASH = re.compile(r"[0-9a-f]{64}")


def canonical_reply_id(value: object) -> bool:
    return isinstance(value, str) and bool(_UUID.fullmatch(value)) and uuid.UUID(value).int != 0


def valid_reply_registration(context_id: object, public_key: object, version: object, device_id: object) -> bool:
    if (not canonical_reply_id(context_id) or uuid.UUID(context_id).version != 4
            or version != "x25519-aesgcm-v1"):
        return False
    if not isinstance(device_id, str) or not device_id.strip() or len(device_id) > 256:
        return False
    if not isinstance(public_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", public_key):
        return False
    raw = base64.urlsafe_b64decode(public_key + "=")
    # The zero point can never produce a usable X25519 shared secret.
    return len(raw) == 32 and any(raw) and base64.urlsafe_b64encode(raw).decode().rstrip("=") == public_key


def reply_workspace(metadata: object, user_id: str, chat_id: str) -> dict | None:
    """Missing scope is invalid; explicit durable NULL is required for Personal."""
    if not isinstance(metadata, dict) or metadata.get("id") != chat_id or "hashed_team_id" not in metadata:
        return None
    team_hash = metadata["hashed_team_id"]
    if isinstance(team_hash, str) and _HASH.fullmatch(team_hash):
        return {"kind": "team", "hashed_team_id": team_hash}
    if (team_hash is None and metadata.get("hashed_user_id") == hashlib.sha256(user_id.encode()).hexdigest()
            and metadata.get("chat_visibility") in (None, "team")
            and metadata.get("participant_user_hashes") is None
            and metadata.get("participant_key_envelopes") is None):
        return {"kind": "personal"}
    return None


def build_reply_context(target: dict, user_id: object, chat_id: object, message_id: object, workspace: object) -> dict | None:
    """Combine trusted event identity with this authenticated registration only."""
    if not all(canonical_reply_id(value) for value in (user_id, chat_id, message_id)):
        return None
    if target.get("reply_context_owner_id") != user_id or not valid_reply_registration(
        target.get("reply_context_id"), target.get("notification_public_key"),
        target.get("encryption_version"), target.get("device_id"),
    ):
        return None
    if workspace == {"kind": "personal"}:
        scope = {"kind": "personal"}
    elif (isinstance(workspace, dict) and set(workspace) == {"kind", "hashed_team_id"}
          and workspace.get("kind") == "team" and isinstance(workspace.get("hashed_team_id"), str)
          and _HASH.fullmatch(workspace["hashed_team_id"])):
        scope = dict(workspace)
    else:
        return None
    notification_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"openmates:chat-reply:v1:{user_id}:{chat_id}:{message_id}"))
    return {
        "version": 1, "registration_context_id": target["reply_context_id"],
        "recipient_account_id": user_id, "notification_id": notification_id,
        "chat_id": chat_id, "message_id": message_id, "workspace": scope,
    }
