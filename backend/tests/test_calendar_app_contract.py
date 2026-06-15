# backend/tests/test_calendar_app_contract.py
#
# Calendar app contract tests for the connected-account permission platform.
# These tests keep the app metadata and skill execution boundary aligned with
# the client-mediated token-broker model before live Google tests are enabled.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

from pathlib import Path

import yaml

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CALENDAR_APP_CONFIG = REPO_ROOT / "backend" / "apps" / "calendar" / "app.yml"


def test_calendar_skills_are_not_rest_api_executable() -> None:
    with CALENDAR_APP_CONFIG.open("r", encoding="utf-8") as handle:
        app_config = yaml.safe_load(handle)

    skill_ids = {skill["id"] for skill in app_config["skills"]}
    assert skill_ids == {
        "get-events",
        "create-event",
        "update-event",
        "delete-event",
    }
    for skill in app_config["skills"]:
        assert skill["api_config"]["expose_post"] is False
        requests_schema = skill["tool_schema"]["properties"]["requests"]["items"]
        assert "access_token_handle" not in requests_schema.get("properties", {})


def test_calendar_get_events_requires_access_token_handle() -> None:
    from backend.apps.calendar.skills.get_events_skill import GetEventsSkill

    request = GetEventsSkill.build_provider_request(
        calendar_id="primary",
        time_min="2026-06-15T00:00:00Z",
        time_max="2026-06-16T00:00:00Z",
        access_token_handle="ath_test",
    )

    assert request.calendar_id == "primary"
    assert request.access_token_handle == "ath_test"


def test_calendar_mutation_skills_require_access_token_handle() -> None:
    from backend.apps.calendar.skills.create_event_skill import CreateEventSkill
    from backend.apps.calendar.skills.delete_event_skill import DeleteEventSkill
    from backend.apps.calendar.skills.update_event_skill import UpdateEventSkill

    with pytest.raises(ValueError, match="access_token_handle"):
        CreateEventSkill.build_provider_request(
            calendar_id="primary",
            title="Demo",
            start="2026-06-15T10:00:00Z",
            end="2026-06-15T10:30:00Z",
            access_token_handle="",
        )

    create_request = CreateEventSkill.build_provider_request(
        calendar_id="primary",
        title="Demo",
        start="2026-06-15T10:00:00Z",
        end="2026-06-15T10:30:00Z",
        access_token_handle="ath_123",
    )
    update_request = UpdateEventSkill.build_provider_request(
        calendar_id="primary",
        event_id="event-1",
        title="Demo updated",
        start="2026-06-15T11:00:00Z",
        end="2026-06-15T11:30:00Z",
        access_token_handle="ath_123",
    )
    delete_request = DeleteEventSkill.build_provider_request(
        calendar_id="primary",
        event_id="event-1",
        access_token_handle="ath_123",
    )

    assert create_request.access_token_handle == "ath_123"
    assert update_request.event_id == "event-1"
    assert delete_request.access_token_handle == "ath_123"


@pytest.mark.anyio
async def test_calendar_get_events_executes_provider_with_hidden_access_token() -> None:
    from backend.apps.calendar.skills.get_events_skill import GetEventsSkill
    from backend.shared.providers.google_calendar.models import CalendarEvent

    calls = []

    class FakeCalendarClient:
        def __init__(self, *, access_token: str) -> None:
            self.access_token = access_token

        async def list_events(self, *, calendar_id: str, time_min: str, time_max: str):
            calls.append((self.access_token, calendar_id, time_min, time_max))
            return [CalendarEvent(id="event-1", title="Demo")]

    skill = object.__new__(GetEventsSkill)
    response = await skill.execute(
        [
            {
                "calendar_id": "primary",
                "time_min": "2026-06-15T00:00:00Z",
                "time_max": "2026-06-16T00:00:00Z",
                "access_token_handle": "ath_123",
            }
        ],
        connected_account_access_tokens={"ath_123": "access-secret"},
        calendar_client_factory=FakeCalendarClient,
    )

    assert calls == [
        (
            "access-secret",
            "primary",
            "2026-06-15T00:00:00Z",
            "2026-06-16T00:00:00Z",
        )
    ]
    assert response.results[0]["events"][0]["id"] == "event-1"


@pytest.mark.anyio
async def test_calendar_mutation_skills_execute_provider_with_hidden_access_token() -> None:
    from backend.apps.calendar.skills.create_event_skill import CreateEventSkill
    from backend.apps.calendar.skills.delete_event_skill import DeleteEventSkill
    from backend.apps.calendar.skills.update_event_skill import UpdateEventSkill
    from backend.shared.providers.google_calendar.models import CalendarEvent

    calls = []

    class FakeCalendarClient:
        def __init__(self, *, access_token: str) -> None:
            self.access_token = access_token

        async def create_event(self, **kwargs):
            calls.append(("create", self.access_token, kwargs))
            return CalendarEvent(id="created-1", title=kwargs["title"])

        async def update_event(self, **kwargs):
            calls.append(("update", self.access_token, kwargs))
            return CalendarEvent(id=kwargs["event_id"], title=kwargs["title"])

        async def delete_event(self, **kwargs):
            calls.append(("delete", self.access_token, kwargs))
            return {"status": "deleted", "event_id": kwargs["event_id"]}

    create_skill = object.__new__(CreateEventSkill)
    update_skill = object.__new__(UpdateEventSkill)
    delete_skill = object.__new__(DeleteEventSkill)
    token_context = {"ath_123": "access-secret"}

    create_response = await create_skill.execute(
        [
            {
                "calendar_id": "primary",
                "title": "Demo",
                "start": "2026-06-15T10:00:00Z",
                "end": "2026-06-15T10:30:00Z",
                "access_token_handle": "ath_123",
            }
        ],
        connected_account_access_tokens=token_context,
        calendar_client_factory=FakeCalendarClient,
    )
    update_response = await update_skill.execute(
        [
            {
                "calendar_id": "primary",
                "event_id": "created-1",
                "title": "Demo updated",
                "start": "2026-06-15T11:00:00Z",
                "end": "2026-06-15T11:30:00Z",
                "access_token_handle": "ath_123",
            }
        ],
        connected_account_access_tokens=token_context,
        calendar_client_factory=FakeCalendarClient,
    )
    delete_response = await delete_skill.execute(
        [{"calendar_id": "primary", "event_id": "created-1", "access_token_handle": "ath_123"}],
        connected_account_access_tokens=token_context,
        calendar_client_factory=FakeCalendarClient,
    )

    assert [call[0] for call in calls] == ["create", "update", "delete"]
    assert all(call[1] == "access-secret" for call in calls)
    assert create_response.results[0]["event"]["id"] == "created-1"
    assert update_response.results[0]["event"]["title"] == "Demo updated"
    assert delete_response.results[0] == {
        "calendar_id": "primary",
        "status": "deleted",
        "event_id": "created-1",
    }
