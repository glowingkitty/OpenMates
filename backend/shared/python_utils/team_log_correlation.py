"""Content-free correlation fields for Team chat operational logs."""

import hashlib


def team_correlation_fields(
    *, team_id: str, chat_id: str, message_id: str, task_id: str | None = None,
) -> str:
    """Hash opaque IDs so API and AI worker stages can be joined after log redaction."""
    identifiers = {"team_hash": team_id, "chat_hash": chat_id, "message_hash": message_id}
    if task_id is not None:
        identifiers["task_hash"] = task_id
    if any(not isinstance(value, str) or not value for value in identifiers.values()):
        raise ValueError("Team correlation requires nonempty opaque identifiers")
    return " ".join(
        f"{label}={hashlib.sha256(value.encode('utf-8')).hexdigest()}"
        for label, value in identifiers.items()
    )
