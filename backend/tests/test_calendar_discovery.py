# Calendar discovery contract regressions.
# Provider mocks cover bounded requests and safe field normalization only.
# Live acceptance must exercise the deployed first-party OpenMates skill path.
# Architecture: docs/architecture/app_skills.md

import httpx
import pytest


# contract-test: supporting surface=rest_api assertions=calendar.discovery.target
@pytest.mark.anyio
async def test_provider_calendar_discovery_preserves_pagination_and_roles(monkeypatch):
    from backend.shared.providers.google_calendar.client import GoogleCalendarClient

    def handle(request):
        assert request.url.path == "/calendar/v3/users/me/calendarList"
        assert request.url.params["pageToken"] == "synthetic-next"
        assert request.url.params["showHidden"] == "true"
        assert request.url.params["maxResults"] == "25"
        return httpx.Response(200, json={"items": [{
            "id": "synthetic-calendar", "summary": "Synthetic calendar", "timeZone": "UTC",
            "accessRole": "writer", "primary": False, "hidden": True,
            "irrelevant_field": "excluded",
        }], "nextPageToken": "synthetic-more"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        **kwargs, transport=httpx.MockTransport(handle),
    ))
    result = await GoogleCalendarClient(access_token="synthetic-token").list_calendars(
        page_token="synthetic-next", show_hidden=True, max_results=25,
    )
    assert result == {"calendars": [{
        "id": "synthetic-calendar", "name": "Synthetic calendar", "timezone": "UTC",
        "access_role": "writer", "primary": False, "hidden": True,
    }], "next_page_token": "synthetic-more"}


# contract-test: supporting surface=rest_api assertions=calendar.discovery.target,connected-accounts.execution.client-mediated
@pytest.mark.anyio
async def test_calendar_discovery_requires_broker_context_and_returns_safe_scope_errors():
    from backend.apps.calendar.skills.list_calendars_skill import ListCalendarsSkill

    class Client:
        def __init__(self, *, access_token):
            assert access_token == "synthetic-token"

        async def list_calendars(self, **kwargs):
            request = httpx.Request("GET", "https://www.googleapis.com/calendar/v3/users/me/calendarList")
            response = httpx.Response(403, request=request, json={
                "error": {"errors": [{"reason": "insufficientPermissions"}], "message": "private provider text"},
            })
            response.raise_for_status()

    skill = object.__new__(ListCalendarsSkill)
    with pytest.raises(PermissionError):
        await skill.execute([{"access_token_handle": "synthetic-handle"}], calendar_client_factory=Client)
    result = await skill.execute(
        [{"access_token_handle": "synthetic-handle"}],
        connected_account_access_tokens={"synthetic-handle": "synthetic-token"},
        calendar_client_factory=Client,
    )
    assert result.results[0]["error"] == "google_calendar_missing_scope"
    assert result.results[0]["reconnect_required"] is True
    assert "calendars" not in result.results[0]
    assert "private provider text" not in result.model_dump_json()


# contract-test: supporting surface=rest_api assertions=calendar.discovery.target
def test_calendar_discovery_registered_as_first_party_read():
    from backend.shared.python_utils.connected_account_registry import connected_account_skill_config

    config = connected_account_skill_config("calendar", "list-calendars")
    assert config is not None
    assert config.action == "read"
    assert config.scope_kind == "provider_account"
