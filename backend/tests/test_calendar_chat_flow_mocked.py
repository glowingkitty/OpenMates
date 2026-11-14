# backend/tests/test_calendar_chat_flow_mocked.py
#
# Mocked end-to-end flow from a chat request to Google Calendar and back: the
# real main-processor loop receives a calendar tool call from a fake LLM,
# exchanges the client-submitted turn-token ref through the real token broker,
# runs the real Calendar skill against a stateful fake Google Calendar API and
# hands the structured result to the next LLM call. A revoked Google grant must
# become a "reconnect" tool result, never a failed turn or a new permission ask.
#
# Spec: specifications/features/app-skills/calendar/specification.yml

from __future__ import annotations

import asyncio
import contextlib
import json
from types import SimpleNamespace
from typing import Any

import httpx

from backend.tests.fake_google_calendar import FakeGoogleCalendar
from backend.tests.test_main_processor_invalid_tool_calls import (  # fixture import activates it here
    _repository_google_provider_catalogue,  # noqa: F401 - autouse provider catalogue fixture
    _run_mocked_protocol_guard_main_processor,
    main_processor,
)
from backend.tests.test_token_broker_refs import FakeCache, FakeEncryption

TEAM = "team-synthetic@example.org"
SCOPE = {"calendar_id": TEAM, "time_min": "2026-11-20T00:00:00Z", "time_max": "2026-11-21T00:00:00Z"}
REFRESH_TOKEN = "synthetic-refresh-token"
ACCESS_TOKEN = "synthetic-access-token"
_REAL_SEND = httpx.AsyncClient.send


class TurnCache(FakeCache):
    """Token-broker cache; the processor's focus-phase Redis client is absent here."""

    @property
    def client(self):
        return asyncio.sleep(0, result=None)


@contextlib.contextmanager
def _fake_google_network_only():
    """The harness forbids all network; let only the fake Google transport through."""
    blocked = httpx.AsyncClient.send
    httpx.AsyncClient.send = _REAL_SEND
    try:
        yield
    finally:
        httpx.AsyncClient.send = blocked


async def _turn_token_ref(cache: TurnCache) -> dict[str, Any]:
    from backend.core.api.app.services.token_broker import TokenBrokerService

    async def never(_refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("refs are created without an exchange")

    broker = TokenBrokerService(cache_service=cache, encryption_service=FakeEncryption(), exchange_refresh_token=never)
    ref = await broker.create_turn_token_ref(
        user_id="user-1", user_vault_key_id="vault-key", connected_account_id="acct-1",
        chat_id="chat-1", message_id="message-1", app_id="calendar", allowed_actions=["read"],
        refresh_token_envelope={"refresh_token": REFRESH_TOKEN}, provider_id="google", action_scope=SCOPE,
    )
    return {"connected_account_id": "acct-1", "app_id": "calendar", "provider_id": "google",
            "allowed_actions": ["read"], "turn_token_ref": ref.turn_token_ref, "action_scope": SCOPE}


async def _run_calendar_turn(monkeypatch, *, exchange, google: FakeGoogleCalendar):
    from backend.apps.ai.processing import connected_account_execution
    from backend.apps.calendar.skills.get_events_skill import GetEventsSkill

    monkeypatch.setattr(connected_account_execution, "exchange_refresh_token_for_provider", lambda _provider: exchange)
    dispatched: list[dict[str, Any]] = []

    async def run_real_skill(**kwargs):
        arguments = kwargs["arguments"]
        dispatched.append(arguments)
        with _fake_google_network_only():
            response = await object.__new__(GetEventsSkill).execute(
                arguments["requests"],
                connected_account_access_tokens=arguments["_connected_account_access_tokens"],
                calendar_client_factory=google.client_factory(),
            )
        return [response.model_dump(exclude_none=True)]

    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", run_real_skill)
    cache = TurnCache()
    token_ref = await _turn_token_ref(cache)
    tool_arguments = {"requests": [{"calendar_id": TEAM, "time_min": SCOPE["time_min"], "time_max": SCOPE["time_max"]}]}
    tool = {"type": "function", "function": {"name": "calendar-get-events", "description": "Read events."}}
    output, calls = await _run_mocked_protocol_guard_main_processor(
        monkeypatch,
        [
            [{"fake_google_tool_call": "calendar-get-events", "arguments": tool_arguments, "tool_call_id": "call-cal"}],
            ["Here is your day."],
        ],
        generated_tools=[tool],
        discovered_apps_metadata={"calendar": SimpleNamespace(skills=[SimpleNamespace(
            id="get-events", parallel_safe=False, exclude_fields_for_llm=None, pricing=None,
            tool_schema={"type": "object", "properties": {"requests": {"type": "array", "items": {"type": "object"}}},
                         "required": ["requests"]},
        )], instructions=[], focuses=[])},
        preprocessing_overrides={"selected_app_ids": ["calendar"], "relevant_app_skills": ["calendar-get-events"]},
        request_overrides={"connected_account_token_refs": [token_ref],
                           "current_user_content": "What is on my team calendar on 20 November?",
                           "message_history": [{"role": "user", "content": "What is on my team calendar on 20 November?"}]},
        cache_service=cache,
        encryption_service=FakeEncryption(),
        user_vault_key_id="vault-key",
    )
    tool_results = [message for message in calls[-1]["message_history"]
                    if message.get("role") == "tool" and message.get("tool_call_id") == "call-cal"]
    assert len(tool_results) == 1
    return output, calls, dispatched, tool_results[0]["content"], cache


# contract-test: supporting surface=rest_api assertions=connected-accounts.execution.client-mediated,calendar.read.search-availability
async def test_chat_calendar_request_reads_events_through_broker_and_returns_result_to_llm(monkeypatch) -> None:
    google = FakeGoogleCalendar(access_token=ACCESS_TOKEN)
    google.add_event(TEAM, "evt1", summary="Design review", start={"dateTime": "2026-11-20T09:00:00Z"},
                     end={"dateTime": "2026-11-20T10:00:00Z"})
    google.add_event(TEAM, "evt2", summary="Next week", start={"dateTime": "2026-11-27T09:00:00Z"},
                     end={"dateTime": "2026-11-27T10:00:00Z"})
    exchanged: list[str] = []

    async def exchange(refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        exchanged.append(refresh_token)
        return {"access_token": ACCESS_TOKEN, "expires_in": 3600}

    output, calls, dispatched, content, cache = await _run_calendar_turn(monkeypatch, exchange=exchange, google=google)

    assert exchanged == [REFRESH_TOKEN]
    request = dispatched[0]["requests"][0]
    assert request["access_token_handle"].startswith("ath_")
    assert google.requests and google.requests[0].headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert google.requests[0].url.params["timeMin"] == SCOPE["time_min"]
    assert "Design review" in content and "Next week" not in content
    # Neither the refresh token nor the access token reaches the model or the stored cache in clear text.
    for secret in (REFRESH_TOKEN, ACCESS_TOKEN):
        assert secret not in json.dumps(calls[-1]["message_history"])
        assert secret not in json.dumps(cache.values)
    assert "Here is your day." in "".join(chunk for chunk in output if isinstance(chunk, str))


# contract-test: supporting surface=rest_api assertions=connected-accounts.lifecycle.reconnect-revoke
async def test_revoked_google_grant_becomes_reconnect_result_not_failed_turn(monkeypatch) -> None:
    from backend.shared.providers.google_calendar.oauth import GoogleOAuthTokenExchangeError

    google = FakeGoogleCalendar(access_token=ACCESS_TOKEN)

    async def revoked(_refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        raise GoogleOAuthTokenExchangeError(
            operation="refresh token exchange", status_code=400, provider_error="invalid_grant",
            provider_error_description="Token has been expired or revoked.",
        )

    output, _calls, dispatched, content, _cache = await _run_calendar_turn(monkeypatch, exchange=revoked, google=google)

    assert dispatched == [] and google.requests == []
    payload = json.loads(content)
    assert payload["status"] == "reconnect_required"
    assert payload["app_id"] == "calendar" and payload["skill_id"] == "get-events"
    assert not any(isinstance(chunk, dict) and chunk.get("__awaiting_connected_account_permission__")
                   for chunk in output)
