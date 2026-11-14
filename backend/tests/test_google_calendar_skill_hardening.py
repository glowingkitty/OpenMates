# backend/tests/test_google_calendar_skill_hardening.py
#
# Calendar skills against a stateful fake Google Calendar API (httpx transport):
# event-time validation, provider error classification, pagination, idempotent
# create, partial update with etag preconditions, delete absence reporting,
# missing scope / reconnect / provider outages as structured per-request
# results, and token-exchange failures that require reconnecting.
#
# Spec: specifications/features/app-skills/calendar/specification.yml

from __future__ import annotations

import httpx
import pytest

from backend.tests.fake_google_calendar import FakeGoogleCalendar

TOKENS = {"ath_1": "synthetic-access-token"}
TEAM = "team-synthetic@example.org"


def _skill(cls):
    return object.__new__(cls)


# ----------------------------------------------------------------- event times
@pytest.mark.parametrize(("start", "end", "zone", "expected_start", "expected_end"), [
    ("2026-11-20", "2026-11-21", None, {"date": "2026-11-20"}, {"date": "2026-11-21"}),
    ("2026-11-20", None, None, {"date": "2026-11-20"}, {"date": "2026-11-21"}),
    ("2026-11-20T10:00:00Z", "2026-11-20T11:00:00Z", None,
     {"dateTime": "2026-11-20T10:00:00Z"}, {"dateTime": "2026-11-20T11:00:00Z"}),
    ("2026-11-20T10:00:00", "2026-11-20T11:00:00", "Europe/Berlin",
     {"dateTime": "2026-11-20T10:00:00", "timeZone": "Europe/Berlin"},
     {"dateTime": "2026-11-20T11:00:00", "timeZone": "Europe/Berlin"}),
])
# contract-test: supporting surface=rest_api assertions=calendar.events.time-and-recurrence
def test_event_range_builds_timed_and_all_day_bodies(start, end, zone, expected_start, expected_end) -> None:
    from backend.shared.providers.google_calendar.event_body import event_range

    assert event_range(start, end, zone) == (expected_start, expected_end)


@pytest.mark.parametrize(("start", "end", "zone", "code"), [
    ("2026-11-20T10:00:00", "2026-11-20T11:00:00", None, "timezone_required"),
    ("2026-11-20T10:00:00Z", "2026-11-20T09:00:00Z", None, "end_before_start"),
    ("2026-11-20", "2026-11-20", None, "end_before_start"),
    ("2026-11-20", "2026-11-20T11:00:00Z", None, "mixed_all_day"),
    ("2026-11-20T10:00:00Z", None, None, "end_required"),
    ("2026-03-29T02:30:00", "2026-03-29T03:30:00", "Europe/Berlin", "nonexistent_local_time"),
    ("2026-10-25T02:30:00", "2026-10-25T03:30:00", "Europe/Berlin", "ambiguous_local_time"),
    ("2026-11-20T10:00:00", "2026-11-20T11:00:00", "Mars/Olympus", "invalid_timezone"),
    ("tomorrow at ten", "2026-11-20T11:00:00Z", None, "invalid_time"),
])
# contract-test: supporting surface=rest_api assertions=calendar.events.time-and-recurrence
def test_event_range_rejects_unsafe_times(start, end, zone, code) -> None:
    from backend.shared.providers.google_calendar.event_body import EventInputError, event_range

    with pytest.raises(EventInputError) as exc_info:
        event_range(start, end, zone)
    assert exc_info.value.code == code


# contract-test: supporting surface=rest_api assertions=calendar.events.safe-mutations
def test_idempotent_event_id_uses_google_alphabet_and_is_stable() -> None:
    from backend.shared.providers.google_calendar.event_body import idempotent_event_id

    first = idempotent_event_id("message-1:0:cal:Title")
    assert first == idempotent_event_id("message-1:0:cal:Title")
    assert first != idempotent_event_id("message-2:0:cal:Title")
    assert 5 <= len(first) <= 1024 and set(first) <= set("0123456789abcdefghijklmnopqrstuv")


# ------------------------------------------------------------ error mapping
@pytest.mark.parametrize(("status", "reason", "headers", "code", "reconnect"), [
    (401, "authError", {}, "google_calendar_reconnect_required", True),
    (403, "insufficientPermissions", {}, "google_calendar_missing_scope", True),
    (403, "rateLimitExceeded", {}, "google_calendar_rate_limited", False),
    (429, "rateLimitExceeded", {"Retry-After": "7"}, "google_calendar_rate_limited", False),
    (403, "requiredAccessLevel", {}, "google_calendar_forbidden", False),
    (404, "notFound", {}, "google_calendar_not_found", False),
    (409, "duplicate", {}, "google_calendar_duplicate", False),
    (410, "deleted", {}, "google_calendar_gone", False),
    (412, "conditionNotMet", {}, "google_calendar_conflict", False),
    (503, "backendError", {}, "google_calendar_provider_error", False),
])
# contract-test: supporting surface=rest_api assertions=calendar.connection.scopes
def test_provider_errors_are_classified(status, reason, headers, code, reconnect) -> None:
    from backend.shared.providers.google_calendar.errors import classify_status_error

    response = httpx.Response(status, headers=headers, json={"error": {"errors": [{"reason": reason}]}})
    error = classify_status_error(response)
    assert error.code == code
    assert error.reconnect_required is reconnect
    if headers:
        assert error.to_result()["retry_after_seconds"] == 7


# ---------------------------------------------------------------- list / read
# contract-test: supporting surface=rest_api assertions=calendar.discovery.target
@pytest.mark.anyio
async def test_list_calendars_returns_roles_and_missing_scope_is_not_empty() -> None:
    from backend.apps.calendar.skills.list_calendars_skill import ListCalendarsSkill

    google = FakeGoogleCalendar()
    result = await _skill(ListCalendarsSkill).execute(
        [{"access_token_handle": "ath_1"}], connected_account_access_tokens=TOKENS,
        calendar_client_factory=google.client_factory(),
    )
    roles = {item["id"]: item["access_role"] for item in result.results[0]["calendars"]}
    assert roles[TEAM] == "writer" and roles["holidays-synthetic@example.org"] == "reader"

    google.granted_scopes = set()
    denied = await _skill(ListCalendarsSkill).execute(
        [{"access_token_handle": "ath_1"}], connected_account_access_tokens=TOKENS,
        calendar_client_factory=google.client_factory(),
    )
    assert denied.results[0]["error"] == "google_calendar_missing_scope"
    assert denied.results[0]["reconnect_required"] is True
    assert "calendars" not in denied.results[0]
    assert denied.error == "google_calendar_missing_scope"


# contract-test: supporting surface=rest_api assertions=calendar.read.search-availability
@pytest.mark.anyio
async def test_get_events_paginates_without_silent_truncation_and_searches() -> None:
    from backend.apps.calendar.skills.get_events_skill import GetEventsSkill

    google = FakeGoogleCalendar()
    for day in (20, 21, 22):
        google.add_event(TEAM, f"evt{day}", summary=f"Sync {day}",
                         start={"dateTime": f"2026-11-{day}T09:00:00Z"}, end={"dateTime": f"2026-11-{day}T10:00:00Z"})
    google.add_event(TEAM, "allday", summary="Offsite", start={"date": "2026-11-23"}, end={"date": "2026-11-24"})
    request = {"calendar_id": TEAM, "time_min": "2026-11-01T00:00:00Z", "time_max": "2026-12-01T00:00:00Z",
               "access_token_handle": "ath_1"}
    skill = _skill(GetEventsSkill)
    first = (await skill.execute([request], connected_account_access_tokens=TOKENS,
                                 calendar_client_factory=google.client_factory())).results[0]
    assert [event["id"] for event in first["events"]] == ["evt20", "evt21"]
    assert first["has_more"] is True
    second = (await skill.execute([{**request, "page_token": first["next_page_token"]}],
                                  connected_account_access_tokens=TOKENS,
                                  calendar_client_factory=google.client_factory())).results[0]
    assert [event["id"] for event in second["events"]] == ["evt22", "allday"]
    assert second["has_more"] is False
    assert second["events"][1]["all_day"] is True and second["events"][1]["end"] == "2026-11-24"

    searched = (await skill.execute([{**request, "query": "offsite"}], connected_account_access_tokens=TOKENS,
                                    calendar_client_factory=google.client_factory())).results[0]
    assert [event["id"] for event in searched["events"]] == ["allday"]
    assert google.requests[-1].url.params["q"] == "offsite"


# contract-test: supporting surface=rest_api assertions=calendar.read.search-availability
@pytest.mark.anyio
async def test_get_events_rejects_unbounded_or_offsetless_intervals_without_calling_google() -> None:
    from backend.apps.calendar.skills.get_events_skill import GetEventsSkill

    google = FakeGoogleCalendar()
    response = await _skill(GetEventsSkill).execute([
        {"calendar_id": TEAM, "time_min": "2026-11-01T00:00:00", "time_max": "2026-11-02T00:00:00Z",
         "access_token_handle": "ath_1"},
        {"calendar_id": TEAM, "time_min": "2026-01-01T00:00:00Z", "time_max": "2028-01-01T00:00:00Z",
         "access_token_handle": "ath_1"},
        {"calendar_id": TEAM, "access_token_handle": "ath_1"},
    ], connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory())
    assert [item["error"] for item in response.results] == [
        "calendar_timezone_required", "calendar_interval_too_long", "calendar_invalid_input",
    ]
    assert google.requests == []


# contract-test: supporting surface=rest_api assertions=calendar.read.search-availability
@pytest.mark.anyio
async def test_one_failed_calendar_does_not_hide_the_others_and_outage_is_retryable() -> None:
    from backend.apps.calendar.skills.get_events_skill import GetEventsSkill

    google = FakeGoogleCalendar()
    google.add_event(TEAM, "evt1", summary="Kept", start={"dateTime": "2026-11-20T09:00:00Z"},
                     end={"dateTime": "2026-11-20T10:00:00Z"})
    google.fail_next = [httpx.ConnectError("synthetic outage")]
    bounds = {"time_min": "2026-11-01T00:00:00Z", "time_max": "2026-12-01T00:00:00Z", "access_token_handle": "ath_1"}
    response = await _skill(GetEventsSkill).execute(
        [{"calendar_id": "primary-synthetic@example.org", **bounds}, {"calendar_id": TEAM, **bounds}],
        connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory(),
    )
    assert response.results[0] == {
        "calendar_id": "primary-synthetic@example.org", "error": "google_calendar_unavailable",
        "reconnect_required": False, "retryable": True,
    }
    assert [event["title"] for event in response.results[1]["events"]] == ["Kept"]
    assert response.error is None


# contract-test: supporting surface=rest_api assertions=connected-accounts.execution.client-mediated
@pytest.mark.anyio
async def test_skills_refuse_to_run_without_a_broker_issued_handle() -> None:
    from backend.apps.calendar.skills.create_event_skill import CreateEventSkill
    from backend.apps.calendar.skills.get_events_skill import GetEventsSkill

    google = FakeGoogleCalendar()
    with pytest.raises(PermissionError):
        await _skill(GetEventsSkill).execute(
            [{"calendar_id": TEAM, "time_min": "2026-11-01T00:00:00Z", "time_max": "2026-11-02T00:00:00Z",
              "access_token_handle": "ath_forged"}],
            connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory(),
        )
    with pytest.raises(PermissionError):
        await _skill(CreateEventSkill).execute(
            [{"calendar_id": TEAM, "title": "x", "start": "2026-11-20", "access_token_handle": "ath_1"}],
            connected_account_access_tokens=None, calendar_client_factory=google.client_factory(),
        )
    assert google.requests == []


# ----------------------------------------------------------------- mutations
# contract-test: supporting surface=rest_api assertions=calendar.events.safe-mutations,calendar.events.external-effects
@pytest.mark.anyio
async def test_create_is_idempotent_per_message_and_never_notifies_by_default() -> None:
    from backend.apps.calendar.skills.create_event_skill import CreateEventSkill

    google = FakeGoogleCalendar()
    request = {"calendar_id": TEAM, "title": "Planning hold", "start": "2026-11-20T10:00:00",
               "end": "2026-11-20T11:00:00", "timezone": "Europe/Berlin", "reminder_minutes": [10],
               "access_token_handle": "ath_1"}
    skill = _skill(CreateEventSkill)
    first = await skill.execute([request], connected_account_access_tokens=TOKENS,
                                calendar_client_factory=google.client_factory(), message_id="message-1")
    retry = await skill.execute([request], connected_account_access_tokens=TOKENS,
                                calendar_client_factory=google.client_factory(), message_id="message-1")
    assert first.results[0]["status"] == "created"
    assert retry.results[0]["status"] == "already_created"
    assert retry.results[0]["event"]["id"] == first.results[0]["event"]["id"]
    assert len([key for key in google.events if key[0] == TEAM]) == 1
    insert = google.requests[0]
    assert insert.url.params["sendUpdates"] == "none"
    created = google.events[(TEAM, first.results[0]["event"]["id"])]
    assert created["start"] == {"dateTime": "2026-11-20T10:00:00", "timeZone": "Europe/Berlin"}
    assert created["reminders"] == {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}]}
    assert "attendees" not in created and first.results[0]["invited_attendees"] == []


# contract-test: supporting surface=rest_api assertions=calendar.discovery.target,calendar.events.safe-mutations
@pytest.mark.anyio
async def test_create_requires_an_explicit_writable_calendar() -> None:
    from backend.apps.calendar.skills.create_event_skill import CreateEventSkill

    google = FakeGoogleCalendar()
    response = await _skill(CreateEventSkill).execute([
        {"title": "No target", "start": "2026-11-20", "access_token_handle": "ath_1"},
        {"calendar_id": "holidays-synthetic@example.org", "title": "Read only", "start": "2026-11-20",
         "access_token_handle": "ath_1"},
        {"calendar_id": "deleted-synthetic@example.org", "title": "Gone", "start": "2026-11-20",
         "access_token_handle": "ath_1"},
    ], connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory())
    assert [item["error"] for item in response.results] == [
        "calendar_invalid_input", "google_calendar_forbidden", "google_calendar_not_found",
    ]
    assert not google.events


# contract-test: supporting surface=rest_api assertions=calendar.events.safe-mutations
@pytest.mark.anyio
async def test_uncertain_create_outcome_is_reported_as_uncertain() -> None:
    from backend.apps.calendar.skills.create_event_skill import CreateEventSkill

    google = FakeGoogleCalendar()
    google.fail_next = [httpx.ReadTimeout("synthetic timeout after dispatch")]
    response = await _skill(CreateEventSkill).execute(
        [{"calendar_id": TEAM, "title": "Maybe", "start": "2026-11-20", "access_token_handle": "ath_1"}],
        connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory(),
        message_id="message-2",
    )
    assert response.results[0]["error"] == "google_calendar_outcome_uncertain"
    assert "status" not in response.results[0]


# contract-test: supporting surface=rest_api assertions=calendar.events.safe-mutations
@pytest.mark.anyio
async def test_update_is_partial_and_guarded_by_etag() -> None:
    from backend.apps.calendar.skills.update_event_skill import UpdateEventSkill

    google = FakeGoogleCalendar()
    original = google.add_event(TEAM, "evt1", summary="Review", location="Room 1", description="Agenda",
                                start={"dateTime": "2026-11-20T09:00:00Z"}, end={"dateTime": "2026-11-20T10:00:00Z"})
    original_etag = original["etag"]  # the fake mutates the stored dict on PATCH
    skill = _skill(UpdateEventSkill)
    response = await skill.execute(
        [{"calendar_id": TEAM, "event_id": "evt1", "title": "Review v2", "location": "",
          "access_token_handle": "ath_1"}],
        connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory(),
    )
    result = response.results[0]
    assert result["status"] == "updated" and result["changed_fields"] == ["location", "summary"]
    patch = google.requests[-1]
    assert patch.method == "PATCH" and patch.headers["if-match"] == '"etag-1"'
    stored = google.events[(TEAM, "evt1")]
    assert stored["summary"] == "Review v2" and stored["location"] == ""
    assert stored["description"] == "Agenda" and stored["start"] == {"dateTime": "2026-11-20T09:00:00Z"}

    stale = await skill.execute(
        [{"calendar_id": TEAM, "event_id": "evt1", "title": "Overwrite", "expected_etag": original_etag,
          "access_token_handle": "ath_1"}],
        connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory(),
    )
    assert stale.results[0]["error"] == "google_calendar_conflict"
    assert google.events[(TEAM, "evt1")]["summary"] == "Review v2"

    # Someone edits the event between our re-read and the PATCH: Google answers 412.
    google.fail_next = [httpx.Response(200, json=dict(google.events[(TEAM, "evt1")])),
                        httpx.Response(412, json={"error": {"errors": [{"reason": "conditionNotMet"}]}})]
    raced = await skill.execute(
        [{"calendar_id": TEAM, "event_id": "evt1", "title": "Race", "access_token_handle": "ath_1"}],
        connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory(),
    )
    assert raced.results[0]["error"] == "google_calendar_conflict"


# contract-test: supporting surface=rest_api assertions=calendar.events.time-and-recurrence,calendar.events.safe-mutations
@pytest.mark.anyio
async def test_update_rejects_empty_changes_and_recurring_events_without_mutation() -> None:
    from backend.apps.calendar.skills.update_event_skill import UpdateEventSkill

    google = FakeGoogleCalendar()
    google.add_event(TEAM, "evt1", summary="One-off", start={"date": "2026-11-20"}, end={"date": "2026-11-21"})
    google.add_event(TEAM, "series_1", summary="Weekly", recurringEventId="series",
                     start={"dateTime": "2026-11-20T09:00:00Z"}, end={"dateTime": "2026-11-20T10:00:00Z"})
    response = await _skill(UpdateEventSkill).execute([
        {"calendar_id": TEAM, "event_id": "evt1", "access_token_handle": "ath_1"},
        {"calendar_id": TEAM, "event_id": "series_1", "title": "Moved", "access_token_handle": "ath_1"},
        {"calendar_id": TEAM, "event_id": "evt1", "start": "2026-11-20T09:00:00Z", "access_token_handle": "ath_1"},
    ], connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory())
    assert [item["error"] for item in response.results] == [
        "calendar_nothing_to_update", "calendar_recurring_not_supported", "calendar_mixed_all_day",
    ]
    assert all(request.method == "GET" for request in google.requests)


# contract-test: supporting surface=rest_api assertions=calendar.events.safe-mutations
@pytest.mark.anyio
async def test_delete_reports_absence_accurately() -> None:
    from backend.apps.calendar.skills.delete_event_skill import DeleteEventSkill

    google = FakeGoogleCalendar()
    google.add_event(TEAM, "evt1", summary="Drop me", start={"dateTime": "2026-11-20T09:00:00Z"},
                     end={"dateTime": "2026-11-20T10:00:00Z"})
    skill = _skill(DeleteEventSkill)
    first = await skill.execute([{"calendar_id": TEAM, "event_id": "evt1", "access_token_handle": "ath_1"}],
                                connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory())
    again = await skill.execute([{"calendar_id": TEAM, "event_id": "evt1", "access_token_handle": "ath_1"},
                                 {"calendar_id": TEAM, "event_id": "never", "access_token_handle": "ath_1"}],
                                connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory())
    assert first.results[0]["status"] == "deleted"
    assert google.requests[1].headers["if-match"] == '"etag-1"'
    assert google.requests[1].url.params["sendUpdates"] == "none"
    assert again.results[0]["status"] == "already_deleted"
    assert again.results[1]["error"] == "google_calendar_not_found"


# contract-test: supporting surface=rest_api assertions=calendar.connection.scopes
@pytest.mark.anyio
async def test_expired_access_token_asks_to_reconnect_for_every_skill() -> None:
    from backend.apps.calendar.skills.delete_event_skill import DeleteEventSkill
    from backend.apps.calendar.skills.get_events_skill import GetEventsSkill

    google = FakeGoogleCalendar(access_token="a-different-token")
    read = await _skill(GetEventsSkill).execute(
        [{"calendar_id": TEAM, "time_min": "2026-11-01T00:00:00Z", "time_max": "2026-11-02T00:00:00Z",
          "access_token_handle": "ath_1"}],
        connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory(),
    )
    delete = await _skill(DeleteEventSkill).execute(
        [{"calendar_id": TEAM, "event_id": "evt1", "access_token_handle": "ath_1"}],
        connected_account_access_tokens=TOKENS, calendar_client_factory=google.client_factory(),
    )
    for response in (read, delete):
        assert response.results[0]["error"] == "google_calendar_reconnect_required"
        assert response.results[0]["reconnect_required"] is True


# ------------------------------------------------- token exchange failures
# contract-test: supporting surface=rest_api assertions=connected-accounts.lifecycle.reconnect-revoke
def test_revoked_grant_becomes_a_reconnect_payload_without_secrets() -> None:
    from backend.shared.providers.google_calendar.oauth import GoogleOAuthTokenExchangeError
    from backend.shared.python_utils.connected_account_errors import connected_account_exchange_failure_payload

    revoked = GoogleOAuthTokenExchangeError(
        operation="refresh token exchange", status_code=400, provider_error="invalid_grant",
        provider_error_description="Token has been expired or revoked.",
    )
    outage = GoogleOAuthTokenExchangeError(
        operation="refresh token exchange", status_code=503, provider_error=None, provider_error_description=None,
    )
    payload = connected_account_exchange_failure_payload(revoked, app_id="calendar", skill_id="get-events")
    assert payload["status"] == "reconnect_required" and payload["provider_id"] == "google"
    assert "revoked" not in str(payload)
    assert connected_account_exchange_failure_payload(
        outage, app_id="calendar", skill_id="get-events",
    )["status"] == "provider_unavailable"
