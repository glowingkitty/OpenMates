"""Account-free calendar event schema, uncertainty, and instruction contracts."""

import json
from pathlib import Path

import pytest
import yaml

from backend.apps.ai.utils.calendar_event_fences import (
    MAX_CONTEXT_EVENTS,
    is_calendar_event_fence,
    normalize_calendar_event_source,
)
from backend.apps.ai.utils.json_content_fences import json_content_embed_type


def source(primary=None, context=None):
    return json.dumps({
        "openmatesType": "calendar_event", "schemaVersion": 1,
        "primary_event": primary or {"title": "FOSDEM 2027", "start": "2027-01-30", "end": "2027-02-01"},
        "context_events": context or [],
    })


# contract-test: supporting surface=rest_api assertions=calendar-event.content.validated,calendar-event.preview.context-highlight
def test_all_day_range_keeps_dates_and_context_is_allowlisted():
    result = normalize_calendar_event_source(source(context=[
        {"title": "Flight", "start": "2027-01-29T17:00:00+01:00", "attendees": ["private@example.invalid"]},
        {"title": "Impossible", "start": "2027-02-30"},
    ]))
    assert result.model["primary_event"] == {"title": "FOSDEM 2027", "start": "2027-01-30", "end": "2027-02-01"}
    assert result.model["context_events"] == [{"title": "Flight", "start": "2027-01-29T17:00:00+01:00"}]
    assert result.status == "partial"
    assert result.warnings == [{"code": "invalid_context_event", "path": "context_events[1]"}]


@pytest.mark.parametrize("primary", [
    {"title": "", "start": "2027-01-30"},
    {"title": "X", "start": "2027-02-29"},
    {"title": "X", "start": "2027-01-30T10:00:00"},
    {"title": "X", "start": "2027-01-30", "end": "2027-01-30"},
    {"title": "X", "start": "2027-01-30", "end": "2027-01-31T10:00:00Z"},
    {"title": "X", "start": "2027-01-30T10:00:00+01:00", "end": "2027-01-30T08:00:00Z"},
    {"title": "X", "start": "2027-01-30T10:00:00+02:00", "timezone": "Europe/Brussels"},
    {"title": "X", "start": "2027-01-30", "source_url": "javascript:alert(1)"},
    {"title": "X", "start": "2027-01-30", "source_url": "https://secret@example.org/event"},
])
# contract-test: supporting surface=rest_api assertions=calendar-event.content.validated
def test_invalid_primary_is_never_exportable(primary):
    result = normalize_calendar_event_source(source(primary))
    assert result.status == "invalid_source"
    assert result.model is None
    assert result.parse_error


# contract-test: supporting surface=rest_api assertions=calendar-event.content.validated
def test_unknown_end_and_dst_disambiguation_are_preserved():
    primary = {"title": "Meeting", "start": "2027-10-31T02:30:00+01:00", "timezone": "Europe/Brussels"}
    result = normalize_calendar_event_source(source(primary))
    assert result.model["primary_event"] == primary
    assert "end" not in result.model["primary_event"]


# contract-test: supporting surface=rest_api assertions=calendar-event.preview.context-highlight
def test_context_is_bounded_deduplicated_and_cannot_change_primary():
    context = [{"title": str(i), "start": "2027-01-30"} for i in range(MAX_CONTEXT_EVENTS + 5)]
    result = normalize_calendar_event_source(source(context=context))
    assert len(result.model["context_events"]) == MAX_CONTEXT_EVENTS
    assert result.model["primary_event"]["title"] == "FOSDEM 2027"
    assert any(w["code"] == "context_limit" for w in result.warnings)
    primary = {"title": "Meeting", "start": "2027-01-30"}
    result = normalize_calendar_event_source(source(primary, [primary, primary]))
    assert result.model["context_events"] == []


# contract-test: supporting surface=rest_api assertions=calendar-event.streaming.saved-lifecycle
def test_only_explicit_calendar_fences_are_recognized():
    assert is_calendar_event_fence("openmates_calendar_event")
    assert is_calendar_event_fence("omcalendar")
    assert not is_calendar_event_fence("json")
    assert json_content_embed_type("openmates_mindmap") == "mindmap"
    assert json_content_embed_type("openmates_calendar_event") == "calendar_event"
    assert json_content_embed_type("python") is None
    assert normalize_calendar_event_source('{"openmatesType":"calendar_event"').model is None


# contract-test: supporting surface=rest_api assertions=calendar-event.assistant.relevant-research,calendar-event.privacy.explicit-local-export
def test_instructions_are_embed_gated_and_no_cloud_skill_is_added():
    root = Path(__file__).resolve().parents[2]
    app = yaml.safe_load((root / "backend/apps/calendar/app.yml").read_text())
    from backend.shared.python_schemas.app_metadata_schemas import AppInstructionDefinition, EmbedTypeDefinition
    instruction = next(i for i in app["instructions"] if "calendar_event" in i["for_embed_types"])
    assert AppInstructionDefinition.model_validate(instruction).for_embed_types == ["calendar_event"]
    assert "EXCLUSIVE" in instruction["instruction"]
    assert "context_events" in instruction["instruction"]
    assert "Never invent personal commitments" in instruction["instruction"]
    embed = next(i for i in app["embed_types"] if i["backend_type"] == "calendar_event")
    assert EmbedTypeDefinition.model_validate(embed).frontend_type == "calendar-event"
    assert embed["category"] == "direct"
    assert embed["content_catalog"]["enabled"] is True
    assert {s["id"] for s in app["skills"]} == {"list-calendars", "get-events", "create-event", "update-event", "delete-event"}
