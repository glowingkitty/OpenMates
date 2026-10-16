"""Provider-free scenario bodies used by isolated sealed-output replay."""

# contract-test-file: infrastructure

import pytest

from backend.apps.ai.testing.capacity_fixtures import generate_fixture, should_fail_child_prompt_save
from backend.apps.ai.utils.answer_recovery import ANSWER_RECOVERY_INSTRUCTION
from backend.apps.ai.utils.tool_protocol_guard import TOOL_PROTOCOL_CONTINUATION_PROMPT
from backend.shared.testing.mock_context import sign_live_marker


def _response(scenario: str) -> dict:
    result = generate_fixture("llm/gemini", {
        "model": "gemini-test", "messages": [{"role": "user", "content":
            f"STORAGE_CAPACITY_SCENARIO:{scenario}"}], "tools": [],
    })
    assert result is not None
    response = result["response"]
    assert response["type"] == "mixed_stream"
    return {
        **response,
        "body": "".join(
            chunk["value"] for chunk in response["chunks"]
            if chunk.get("kind") == "text" and isinstance(chunk.get("value"), str)
        ),
    }


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_recovery_fixture_has_code_and_versioned_diff_artifacts() -> None:
    embed = _response("recovery_embed")["body"]
    diff = _response("recovery_diff")["body"]
    assert embed.startswith("```python:recovery_demo.py\n")
    assert "stable_value = 7" in embed
    assert diff.startswith("```diff\n--- a/recovery_demo.py\n")
    assert "-    stable_value = 7\n+    stable_value = 8" in diff


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_recovery_fixture_checkpoint_and_failure_paths_remain_synthetic() -> None:
    assert "Synthetic post-checkpoint answer" in _response("recovery_checkpoint")["body"]
    failure = generate_fixture("llm/gemini", {
        "model": "gemini-test",
        "messages": [{"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:recovery_save_failure"}],
        "tools": [{"function": {"name": "start_sub_chats"}}],
    })
    assert failure is not None
    assert failure["response"]["chunks"][0]["value"]["function_name"] == "start_sub_chats"


# contract-test-file: infrastructure
def test_protocol_fixture_requires_clean_answer_only_recovery() -> None:
    request = {"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:recovery_protocol"}
    initial = generate_fixture("llm/gemini", {
        "model": "gemini-test", "messages": [request],
        "tools": [{"function": {"name": "web-search"}}],
    })
    assert initial is not None
    initial_chunks = initial["response"]["chunks"]
    assert initial_chunks[0]["value"].startswith("Verified prefix:")
    assert "```toon" in initial_chunks[1]["value"]
    assert not any(chunk.get("value", {}).get("function_name") == "web-search"
                   for chunk in initial_chunks if isinstance(chunk.get("value"), dict))

    initial_empty_tools = generate_fixture("llm/gemini", {
        "model": "gemini-test", "messages": [request], "tools": [],
    })
    assert initial_empty_tools is not None
    empty_tool_chunks = initial_empty_tools["response"]["chunks"]
    assert empty_tool_chunks[0]["value"].startswith("Verified prefix:")
    assert "```toon" in empty_tool_chunks[1]["value"]

    initial_no_tools = generate_fixture("llm/gemini", {
        "model": "gemini-test", "messages": [request], "tools": None,
    })
    assert initial_no_tools is not None
    no_tool_chunks = initial_no_tools["response"]["chunks"]
    assert no_tool_chunks[0]["value"].startswith("Verified prefix:")
    assert "```toon" in no_tool_chunks[1]["value"]

    old_retry = generate_fixture("llm/gemini", {
        "model": "gemini-test", "messages": [request, {
            "role": "user", "content": TOOL_PROTOCOL_CONTINUATION_PROMPT,
        }], "tools": None,
    })
    assert old_retry is not None
    retry_chunks = old_retry["response"]["chunks"]
    assert retry_chunks[0]["value"].startswith("Verified prefix:")
    assert "```toon" in retry_chunks[1]["value"]

    clean = generate_fixture("llm/gemini", {
        "model": "gemini-test", "messages": [request, {
            "role": "system", "content": ANSWER_RECOVERY_INSTRUCTION,
        }], "tools": None,
    })
    assert clean is not None
    assert clean["response"]["chunks"][0]["value"] == "The safe continuation is complete."


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_detached_docs_fixture_generates_a_local_document_without_provider_tools() -> None:
    body = _response("recovery_detached_doc")["body"]
    assert body.startswith("```docx_model\n")
    assert body.endswith("\n```\n")
    import json

    document = json.loads(body.split("\n", 1)[1].rsplit("\n```", 1)[0])
    assert document == {
        "title": "Synthetic detached document",
        "filename": "Recovery_Detached_Document.docx",
        "blocks": [
            {"type": "heading", "text": "Synthetic detached document"},
            {"type": "paragraph", "text": "Durable worker output after disconnect."},
        ],
    }


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_child_prompt_save_failure_requires_current_signed_replay_marker(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    monkeypatch.setenv("OPENMATES_STORAGE_CAPACITY_FIXTURES", "true")
    monkeypatch.setenv("DAILY_AI_TEST_CONTEXT_SECRET", "synthetic-unit-secret")
    user_id = "44444444-4444-4444-8444-444444444444"
    prompt = "STORAGE_CAPACITY_SCENARIO:recovery_save_failure"
    marker = sign_live_marker(
        "<<<TEST_LIVE_MOCK:storage_capacity_v1>>>", user_id,
        is_allowlisted_test_account=True,
    )
    assert marker
    assert should_fail_child_prompt_save(f"{prompt} {marker}", user_id)
    assert not should_fail_child_prompt_save(prompt, user_id)
    assert not should_fail_child_prompt_save(f"STORAGE_CAPACITY_SCENARIO:child {marker}", user_id)
    with pytest.raises(RuntimeError, match="Invalid or unauthorized TEST_LIVE marker"):
        should_fail_child_prompt_save(f"{prompt} {marker}", "different-user")
    with pytest.raises(RuntimeError, match="Invalid or unauthorized TEST_LIVE marker"):
        should_fail_child_prompt_save(f"{prompt} <<<TEST_LIVE_MOCK:storage_capacity_v1>>>", user_id)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    assert not should_fail_child_prompt_save(f"{prompt} {marker}", user_id)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.parametrize("model", ["gemini-test", "gpt-test"])
def test_composite_recovery_fixture_uses_events_tool_then_final_answer(model: str) -> None:
    request = {"role": "user", "content": "STORAGE_CAPACITY_SCENARIO:recovery_composite"}
    preprocessing = generate_fixture("llm/preprocessing", {
        "model": model, "messages": [request],
        "tools": [{"function": {"name": "analyze_request_properties"}}],
    })
    assert preprocessing is not None
    args = preprocessing["response"]["chunks"][0]["value"]["function_arguments_parsed"]
    assert args["relevant_app_skills"] == ["events-search"]
    assert args["enable_subchats"] is False

    kwargs = {"model": model, "messages": [request],
              "tools": [{"function": {"name": "events-search"}}]}
    initial = generate_fixture("llm/main", kwargs)
    assert initial is not None
    call = initial["response"]["chunks"][0]["value"]
    assert call["function_name"] == "events-search"
    assert call["function_arguments_parsed"] == {"requests": [{
        "query": "39c3", "conference": "39c3", "provider": "pretalx",
        "past_events": True, "count": 10,
    }]}
    final = generate_fixture("llm/main", {**kwargs, "messages": [request, {
        "role": "tool", "name": "events-search", "content": "Synthetic events returned.",
    }]})
    assert final is not None
    assert final["response"]["chunks"][0] == {
        "kind": "text", "value": "The ten synthetic recovery events are ready.",
    }
    assert generate_fixture("llm/main", {**kwargs, "tools": []}) is None
    assert generate_fixture("llm/main", {**kwargs, "tools": [{"function": {"name": "web-search"}}]}) is None


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_composite_recovery_pretalx_cassette_replays_ten_ordered_events_without_network() -> None:
    import httpx
    from pathlib import Path

    from backend.apps.events.providers import pretalx
    from backend.shared.testing.api_response_cache import ApiResponseCache
    from backend.shared.testing.caching_http_transport import CachingHTTPTransport
    from backend.shared.testing.mock_context import activate_mock_mode, deactivate_mock_mode

    def forbidden_network(request):
        raise AssertionError(f"Synthetic recovery must not contact {request.url}")

    root = Path(__file__).resolve().parents[1] / "apps/ai/testing/api_cache"
    cache = ApiResponseCache(root=root)
    url = pretalx.CONFERENCES["39c3"]["schedule_url"]
    fingerprint = cache.fingerprint_http_request(method="GET", url=url, body=None)
    assert (root / "storage_capacity_v1/pretalx" / f"{fingerprint}.json").is_file()
    activate_mock_mode("mock", "storage_capacity_v1")
    try:
        async with httpx.AsyncClient(transport=CachingHTTPTransport(
            httpx.MockTransport(forbidden_network), cache, "pretalx",
        )) as client:
            response = await client.get(url)
    finally:
        deactivate_mock_mode()
    assert response.status_code == 200
    events = [pretalx._normalize_event(event, "39c3")
              for event in pretalx._extract_schedule_events(response.json())]
    ordered = pretalx._rank_events(events, "39c3", "39c3")
    assert len(ordered) == len({event["id"] for event in ordered}) == 10
    assert [event["title"] for event in ordered] == [
        f"Synthetic Recovery Event {index:02d}" for index in range(1, 11)
    ]
    assert all(event["url"].startswith("https://example.test/") for event in ordered)
    # Distinct sessions stay beyond the event skill's 90-minute semantic
    # duplicate window even though their synthetic numbered titles are similar.
    from datetime import datetime

    starts = [datetime.fromisoformat(event["date_start"]) for event in ordered]
    assert all((right - left).total_seconds() > 90 * 60
               for left, right in zip(starts, starts[1:]))
