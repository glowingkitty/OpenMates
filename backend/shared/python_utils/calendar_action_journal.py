# Calendar action-journal payload construction.
# Pure snapshot helpers shared by execution and focused contract tests.
# This module does not authorize or execute undo operations.
# Preserve existing mutation snapshot behavior independently of the AI stack.
# Architecture: docs/architecture/app_skills.md

from typing import Any


def calendar_undo_payload(skill_id: str, results: list[dict[str, Any]]) -> dict[str, Any] | None:
    if skill_id not in {"create-event", "update-event", "delete-event"} or not results:
        return None
    undo_events: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict) or result.get("error"):
            continue
        calendar_id = result.get("calendar_id")
        if skill_id == "create-event":
            event = result.get("event") if isinstance(result.get("event"), dict) else {}
            event_id = event.get("id")
            if event_id and calendar_id:
                undo_events.append(
                    {
                        "undo_type": "delete_created_event",
                        "calendar_id": calendar_id,
                        "event_id": event_id,
                        "etag": event.get("etag"),
                    }
                )
        elif skill_id == "update-event":
            previous_event = result.get("previous_event") if isinstance(result.get("previous_event"), dict) else {}
            updated_event = result.get("event") if isinstance(result.get("event"), dict) else {}
            event_id = previous_event.get("id") or updated_event.get("id")
            if event_id and calendar_id and _calendar_snapshot_has_required_fields(previous_event):
                undo_events.append(
                    {
                        "undo_type": "restore_updated_event",
                        "calendar_id": calendar_id,
                        "event_id": event_id,
                        "etag": previous_event.get("etag"),
                        # Undo restores only while the event still has the etag our update produced.
                        "applied_etag": updated_event.get("etag"),
                        "changed_fields": _changed_fields(result.get("changed_fields")),
                        "snapshot": _calendar_event_snapshot(previous_event),
                    }
                )
        elif skill_id == "delete-event":
            deleted_event = result.get("deleted_event") if isinstance(result.get("deleted_event"), dict) else {}
            event_id = deleted_event.get("id") or result.get("event_id")
            if event_id and calendar_id and _calendar_snapshot_has_required_fields(deleted_event):
                undo_events.append(
                    {
                        "undo_type": "recreate_deleted_event",
                        "calendar_id": calendar_id,
                        "event_id": event_id,
                        "etag": deleted_event.get("etag"),
                        "snapshot": _calendar_event_snapshot(deleted_event),
                    }
                )
    return {"events": undo_events} if undo_events else None


def _calendar_snapshot_has_required_fields(event: dict[str, Any]) -> bool:
    return bool(event.get("title") and event.get("start") and event.get("end"))


def _calendar_event_snapshot(event: dict[str, Any]) -> dict[str, Any]:
    snapshot = {
        "title": event.get("title"),
        "start": event.get("start"),
        "end": event.get("end"),
        "location": event.get("location"),
        "description": event.get("description"),
        "attendees": event.get("attendees") if isinstance(event.get("attendees"), list) else [],
        "timezone": event.get("timezone"),
    }
    return {key: value for key, value in snapshot.items() if value not in (None, "", [])}


# Provider field names in changed_fields map back to snapshot keys.
_PROVIDER_FIELD_TO_SNAPSHOT = {
    "summary": "title", "start": "start", "end": "end", "location": "location",
    "description": "description", "attendees": "attendees",
}


def _changed_fields(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({_PROVIDER_FIELD_TO_SNAPSHOT[item] for item in value if item in _PROVIDER_FIELD_TO_SNAPSHOT})
