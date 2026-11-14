# backend/tests/test_figma_chat_flow_mocked.py
#
# Mocked flow from a chat request to Figma and back: the real main-processor
# loop receives a design-get_design tool call from a fake LLM, exchanges the
# client-submitted turn-token ref through the real token broker, runs the real
# GetDesignSkill against the fake Figma REST API with the synthetic fixture file
# and hands the structured result (including code_handoff) to the next LLM
# call. A revoked Figma grant becomes a "reconnect" tool result.
#
# Spec: specifications/features/app-skills/design-figma/specification.yml

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from backend.tests.fake_figma_api import FILE_KEY, FakeFigmaApi
from backend.tests.test_calendar_chat_flow_mocked import TurnCache, _fake_google_network_only
from backend.tests.test_main_processor_invalid_tool_calls import (  # fixture import activates it here
    _repository_google_provider_catalogue,  # noqa: F401 - autouse provider catalogue fixture
    _run_mocked_protocol_guard_main_processor,
    main_processor,
)
from backend.tests.test_token_broker_refs import FakeEncryption

SCOPE = {"provider": "figma"}
REFRESH_TOKEN = "synthetic-figma-refresh-token"
ACCESS_TOKEN = "synthetic-figma-token"
FIGMA_URL = f"https://www.figma.com/design/{FILE_KEY}/Synthetic-Landing"


async def _turn_token_ref(cache: TurnCache) -> dict[str, Any]:
    from backend.core.api.app.services.token_broker import TokenBrokerService

    async def never(_refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("refs are created without an exchange")

    broker = TokenBrokerService(cache_service=cache, encryption_service=FakeEncryption(), exchange_refresh_token=never)
    ref = await broker.create_turn_token_ref(
        user_id="user-1", user_vault_key_id="vault-key", connected_account_id="figma-acct-1",
        chat_id="chat-1", message_id="message-1", app_id="design", allowed_actions=["read"],
        refresh_token_envelope={"refresh_token": REFRESH_TOKEN}, provider_id="figma", action_scope=SCOPE,
    )
    return {"connected_account_id": "figma-acct-1", "app_id": "design", "provider_id": "figma",
            "allowed_actions": ["read"], "turn_token_ref": ref.turn_token_ref, "action_scope": SCOPE}


async def _run_design_turn(monkeypatch, *, exchange, figma: FakeFigmaApi):
    from backend.apps.ai.processing import connected_account_execution
    from backend.apps.design.skills.get_design_skill import GetDesignSkill

    monkeypatch.setattr(connected_account_execution, "exchange_refresh_token_for_provider", lambda _provider: exchange)
    dispatched: list[dict[str, Any]] = []

    async def run_real_skill(**kwargs):
        arguments = kwargs["arguments"]
        dispatched.append(arguments)
        with _fake_google_network_only():  # restores httpx send for the fake transport only
            response = await object.__new__(GetDesignSkill).execute(
                arguments["requests"],
                connected_account_access_tokens=arguments["_connected_account_access_tokens"],
                figma_client_factory=figma.client_factory(),
            )
        return [response.model_dump(exclude_none=True)]

    monkeypatch.setattr(main_processor, "execute_skill_with_multiple_requests", run_real_skill)
    cache = TurnCache()
    token_ref = await _turn_token_ref(cache)
    prompt = "Build this landing page as a web app: " + FIGMA_URL
    tool_arguments = {"requests": [{"figma_url": FIGMA_URL, "include": ["frames", "components", "styles"]}]}
    tool = {"type": "function", "function": {"name": "design-get_design", "description": "Read a Figma design."}}
    output, calls = await _run_mocked_protocol_guard_main_processor(
        monkeypatch,
        [
            [{"fake_google_tool_call": "design-get_design", "arguments": tool_arguments, "tool_call_id": "call-fig"}],
            ["I will build the Desktop and Mobile screens."],
        ],
        generated_tools=[tool],
        discovered_apps_metadata={"design": SimpleNamespace(skills=[SimpleNamespace(
            id="get_design", parallel_safe=False, exclude_fields_for_llm=None, pricing=None,
            tool_schema={"type": "object", "properties": {"requests": {"type": "array", "items": {"type": "object"}}},
                         "required": ["requests"]},
        )], instructions=[], focuses=[])},
        preprocessing_overrides={"selected_app_ids": ["design"], "relevant_app_skills": ["design-get_design"]},
        request_overrides={"connected_account_token_refs": [token_ref],
                           "current_user_content": prompt,
                           "message_history": [{"role": "user", "content": prompt}]},
        cache_service=cache,
        encryption_service=FakeEncryption(),
        user_vault_key_id="vault-key",
    )
    tool_results = [message for message in calls[-1]["message_history"]
                    if message.get("role") == "tool" and message.get("tool_call_id") == "call-fig"]
    assert len(tool_results) == 1
    return output, calls, dispatched, tool_results[0]["content"], cache


# contract-test: supporting surface=rest_api assertions=design-figma.execution.token-lifecycle,design-figma.handoff.design-to-code
async def test_chat_figma_link_reads_design_through_broker_and_returns_handoff_to_llm(monkeypatch) -> None:
    figma = FakeFigmaApi(access_token=ACCESS_TOKEN)
    exchanged: list[str] = []

    async def exchange(refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        exchanged.append(refresh_token)
        return {"access_token": ACCESS_TOKEN, "expires_in": 7776000}

    output, calls, dispatched, content, cache = await _run_design_turn(monkeypatch, exchange=exchange, figma=figma)

    assert exchanged == [REFRESH_TOKEN]
    assert dispatched[0]["requests"][0]["access_token_handle"].startswith("ath_")
    assert [r.url.path for r in figma.requests] == [f"/v1/files/{FILE_KEY}"]
    assert figma.requests[0].headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert "Synthetic Landing" in content and "Desktop" in content
    assert "code_handoff" in content and "--brand-primary" in content
    for secret in (REFRESH_TOKEN, ACCESS_TOKEN):
        assert secret not in json.dumps(calls[-1]["message_history"])
        assert secret not in json.dumps(cache.values)
    assert "Desktop and Mobile" in "".join(chunk for chunk in output if isinstance(chunk, str))


# contract-test: supporting surface=rest_api assertions=design-figma.execution.token-lifecycle
async def test_revoked_figma_grant_becomes_reconnect_result_not_failed_turn(monkeypatch) -> None:
    from backend.shared.providers.figma.oauth import FigmaOAuthTokenExchangeError

    figma = FakeFigmaApi(access_token=ACCESS_TOKEN)

    async def revoked(_refresh_token: str, _scope: dict[str, Any]) -> dict[str, Any]:
        raise FigmaOAuthTokenExchangeError(
            operation="refresh token exchange", status_code=400, provider_error="invalid_grant",
            provider_error_description=None,
        )

    output, _calls, dispatched, content, _cache = await _run_design_turn(monkeypatch, exchange=revoked, figma=figma)

    assert dispatched == [] and figma.requests == []
    payload = json.loads(content)
    assert payload["status"] == "reconnect_required"
    assert payload["app_id"] == "design" and payload["skill_id"] == "get_design"
    assert not any(isinstance(chunk, dict) and chunk.get("__awaiting_connected_account_permission__")
                   for chunk in output)
