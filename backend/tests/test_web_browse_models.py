"""Offline provider policy and native accounting for Browse's internal helpers."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.shared.providers.browser_models import (
    BrowserModels,
    BrowserModelError,
    matched_quotations,
    parse_browser_json,
)


# contract-test: supporting surface=rest_api assertions=web-browse.structured-data,web-browse.truthful-completion
@pytest.mark.parametrize(
    "content",
    [
        '{"grounded":false,"answer_complete":true}',
        '```json\n{"grounded":false,"answer_complete":true}\n```',
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.structured-data,web-browse.truthful-completion
def test_text_helper_accepts_only_a_complete_json_document_or_single_fence(content):
    assert parse_browser_json(content) == {"grounded": False, "answer_complete": True}


# contract-test: supporting surface=rest_api assertions=web-browse.structured-data,web-browse.private-storage-and-api
@pytest.mark.parametrize(
    "content",
    [
        None,
        "",
        'Private value before {"grounded":true}',
        "```json\n{}\n``` trailing private value",
        "```json\n{}\n```\n```json\n{}\n```",
        '{"value":NaN}',
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.structured-data,web-browse.private-storage-and-api
def test_invalid_helper_response_has_content_free_diagnostics(content):
    with pytest.raises(BrowserModelError) as caught:
        parse_browser_json(content, purpose="verify_quotes")
    details = caught.value.safe_details
    assert details["model_error_code"] == "invalid_json"
    assert details["text_helper_purpose"] == "verify_quotes"
    assert "Private value" not in str(details)
    assert set(details) == {
        "model_error_code",
        "text_helper_purpose",
        "text_response_chars",
        "text_response_kind",
    }


@pytest.fixture
def models(monkeypatch):
    from backend.core.api.app.utils import config_manager

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        config_manager, "BACKEND_CONFIG_FILE", str(root / "config/backend_config.yml")
    )
    monkeypatch.setattr(config_manager, "PROVIDERS_CONFIG_DIR", str(root / "providers"))
    monkeypatch.setattr(config_manager, "PROVIDER_OVERLAY_CONFIG_DIR", None)
    monkeypatch.setattr(config_manager.ConfigManager, "_instance", None)
    return BrowserModels(
        SimpleNamespace(get_secret=AsyncMock(return_value="private-test-key")),
        before_attempt=AsyncMock(return_value="call-id"),
        after_attempt=AsyncMock(),
    )


def google_fallback(monkeypatch):
    module = ModuleType("backend.apps.ai.llm_providers.google_client")
    module._get_google_ai_studio_api_key = AsyncMock(return_value="private-test-key")
    module.invoke_google_ai_studio_chat_completions = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            usage=SimpleNamespace(
                prompt_token_count=100,
                candidates_token_count=10,
                thoughts_token_count=2,
                total_token_count=112,
                cache_read_input_tokens=None,
            ),
            direct_message_content='{"text":"Paris"}',
        )
    )
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module.invoke_google_ai_studio_chat_completions


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.structured-data
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "grounded,covered,acted,empty,expected",
    [
        (0.98, 0.93, 0.95, 0.01, True),
        (0.94, 0.99, 0.99, 0.01, False),
        (0.99, 0.89, 0.99, 0.01, False),
        (0.99, 0.99, 0.94, 0.01, False),
        (0.67, 0.03, 0.89, 0.01, False),
        (0.0, 0.0, 0.9, 0.01, False),
        (0.52, 0.15, 0.08, 0.01, False),
        (0.0, 0.0, 0.99, 0.99, True),
        (0.0, 0.0, 0.94, 0.99, False),
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.structured-data
async def test_completion_requires_grounded_complete_data_and_finished_interactions(
    models, grounded, covered, acted, empty, expected
):
    # A separate quote proof must also fail before a low first score can pass.
    models.generate = AsyncMock(
        return_value={"grounded": False, "answer_complete": False}
    )
    models.decision = AsyncMock(
        return_value=SimpleNamespace(
            answers={
                k: SimpleNamespace(noul=v)
                for k, v in {
                    "grounded": grounded,
                    "answer_complete": covered,
                    "interaction_complete": acted,
                    "empty": empty,
                }.items()
            }
        )
    )
    observed = {
        "url": "https://example.com/",
        "title": "Example Domain",
        "text": "Observed facts",
        "controls": [
            {
                "role": "textbox",
                "label": "Search",
                "value": "query",
                "options": ["not-needed"],
            }
        ],
    }
    assert (
        await models.verify("Read the page", observed, {"fact": "Observed facts"})
        is expected
    )
    state = models.decision.await_args.args[0]
    assert state["proposed_answer"]["sources"] == [
        {"url": observed["url"], "title": observed["title"]}
    ]
    assert state["observed_page"]["controls"] == [
        {"role": "textbox", "label": "Search", "value": "query"}
    ]
    assert models.no_results is (empty >= 0.95 and acted >= 0.95)


# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.structured-data
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "review,expected",
    [
        ({"grounded": True, "answer_complete": True}, True),
        ({"grounded": True, "answer_complete": False}, False),
        ({"grounded": False, "answer_complete": True}, False),
        ({"grounded": "true", "answer_complete": True}, False),
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.structured-data
async def test_literal_presence_also_requires_independent_meaning_and_coverage(
    models, review, expected
):
    models.decision = AsyncMock(
        return_value=SimpleNamespace(
            answers={
                k: SimpleNamespace(noul=v)
                for k, v in {
                    "grounded": 0.88,
                    "answer_complete": 0.41,
                    "interaction_complete": 0.98,
                    "empty": 0.01,
                }.items()
            }
        )
    )
    models.generate = AsyncMock(return_value=review)
    observation = {
        "url": "https://example.com/",
        "document_text": "Observed statement. Essential caveat.",
        "text": "Short display",
    }
    data = {
        "statement": "Observed statement. Essential caveat.",
        "source_url": "https://example.com/",
    }
    assert (
        await models.verify(
            "Quote the entire statement with its caveat and URL", observation, data
        )
        is expected
    )
    context = models.generate.await_args.args[0]
    assert context["purpose"] == "verify_quotes"
    assert [p["path"] for p in context["matched_quotations"]] == [
        "/statement",
        "/source_url",
    ]
    assert context["proposed_answer"] == data
    assert models.verification["grounding_score"] == 0.88


# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.structured-data
@pytest.mark.parametrize(
    "data",
    [
        {"claim": "Invented statement"},
        {"count": 3},
        {"available": True},
        {"claim": ""},
        {"rows": []},
        {},
        {"source_url": "https://unobserved.example/"},
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.structured-data
def test_unquoted_or_nonliteral_data_cannot_use_quotation_proof(data):
    assert (
        matched_quotations(
            data, {"url": "https://example.com/", "text": "Observed statement"}
        )
        is None
    )


# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.budgets-and-stop
@pytest.mark.asyncio
async def test_unfinished_website_action_cannot_be_overridden_by_quote_review(models):
    models.decision = AsyncMock(
        return_value=SimpleNamespace(
            answers={
                k: SimpleNamespace(noul=v)
                for k, v in {
                    "grounded": 0.98,
                    "answer_complete": 0.99,
                    "interaction_complete": 0.10,
                    "empty": 0.01,
                }.items()
            }
        )
    )
    models.generate = AsyncMock(
        return_value={"grounded": True, "answer_complete": True}
    )
    assert not await models.verify(
        "Open the next page",
        {"url": "https://example.com/", "text": "Observed statement"},
        {"quote": "Observed statement"},
    )
    models.generate.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_quote_review_has_a_small_native_output_bound(models, monkeypatch):
    monkeypatch.delenv("WEB_BROWSE_TOGETHER_ZDR_VERIFIED", raising=False)
    fallback = google_fallback(monkeypatch)
    fallback.return_value.direct_message_content = (
        '{"grounded":true,"answer_complete":true}'
    )
    assert await models.generate(
        {"purpose": "verify_quotes", "goal": "Review matched quotations"}
    ) == {"grounded": True, "answer_complete": True}
    assert fallback.await_args.kwargs["max_tokens"] == 256
    models.before_attempt.assert_awaited_once()
    models.after_attempt.assert_awaited_once()


def answers(**scores):
    return SimpleNamespace(
        answers={k: SimpleNamespace(noul=v) for k, v in scores.items()}
    )


PAGE = {
    "url": "https://example.com/",
    "title": "Example",
    "text": "Grow kits. Kit A costs 20 EUR.",
    "document_text": "Grow kits. Kit A costs 20 EUR.",
    "controls": [
        {
            "id": "0",
            "kind": "click",
            "role": "link",
            "label": "Next",
            "href": "https://example.com/2",
        },
        {"id": "1", "kind": "type", "role": "textbox", "label": "Search"},
        {"id": "2", "kind": "click", "role": "button", "label": "Filter"},
        {
            "id": "3",
            "kind": "select",
            "role": "combobox",
            "label": "Sort",
            "options": [{"label": "Price", "value": "price"}],
        },
        {"id": "4", "kind": "click", "role": "button", "label": "Checkout now"},
    ],
    "observation_id": "o1",
}


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.network-and-content
@pytest.mark.asyncio
async def test_gate_blocks_a_page_injection_even_for_plain_actions(models):
    models.decision = AsyncMock(return_value=answers(injection=0.9))
    reason = await models.gate(
        "Read the page", PAGE, [{"kind": "scroll", "delta": 400}]
    )
    assert reason == "The page contains untrusted instructions requiring review."
    models.decision.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.exclusive-takeover
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filter_safe,expected", [(0.99, None), (0.5, "The next action needs your review.")]
)
async def test_gate_asks_one_safe_question_per_non_plain_action_in_one_call(
    models, filter_safe, expected
):
    models.decision = AsyncMock(
        return_value=answers(injection=0.01, safe_2=0.99, safe_3=filter_safe)
    )
    batch = [
        {"kind": "scroll", "delta": 300},
        {"kind": "click", "target": "0"},
        {"kind": "type", "target": "1", "text": "private search words", "submit": True},
        {"kind": "click", "target": "2"},
    ]
    assert await models.gate("Find kits", PAGE, batch) == expected
    models.decision.assert_awaited_once()
    state, questions = models.decision.await_args.args
    assert set(questions) == {"injection", "safe_2", "safe_3"}
    assert [a["index"] for a in state["planned_actions"]] == [2, 3]
    assert "private search words" not in json.dumps(state)  # Typed text stays out.


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.exclusive-takeover
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        {"kind": "click", "target": "4"},
        {"kind": "goto", "url": "https://example.com/checkout"},
    ],
)
async def test_dangerous_target_blocks_the_batch_without_a_model_call(models, action):
    models.decision = AsyncMock()
    reason = await models.gate(
        "Buy nothing", PAGE, [{"kind": "scroll", "delta": 100}, action]
    )
    assert reason == "This action requires your control or explicit confirmation."
    models.decision.assert_not_awaited()


VALID_PLAN = {
    "notes": [{"fact": "Kit A is 20 EUR", "quote": "Kit A costs 20 EUR."}],
    "actions": [
        {"kind": "type", "target": "1", "text": "kits", "submit": True},
        {"kind": "select", "target": "3", "value": "price"},
        {"kind": "click", "target": 2},
    ],
    "done": False,
    "blocked": None,
}


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.text-helper
@pytest.mark.asyncio
async def test_plan_is_validated_against_the_observation(models):
    models.text_call = AsyncMock(return_value=VALID_PLAN)
    plan = await models.plan(
        task="Find kits",
        output_schema={"type": "object"},
        observation=PAGE,
        ledger=[],
        history=[],
    )
    assert plan["actions"][2] == {"kind": "click", "target": "2"}
    assert models.text_call.await_args.kwargs["output_tokens"] == 4096
    assert models.text_call.await_args.kwargs["purpose"] == "plan"
    finished = {**VALID_PLAN, "done": True}
    models.text_call = AsyncMock(return_value=finished)
    done = await models.plan(
        task="Find kits",
        output_schema={"type": "object"},
        observation=PAGE,
        ledger=[],
        history=[],
    )
    assert done["done"] and done["actions"] == []  # A finished plan never acts.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"actions": [{"kind": "click", "target": "99"}]},
        {"actions": [{"kind": "click", "target": "1"}]},
        {"actions": [{"kind": "click", "target": "0", "selector": "#x"}]},
        {"actions": [{"kind": "select", "target": "3", "value": "unobserved"}]},
        {"actions": [{"kind": "goto", "url": "http://example.com/"}]},
        {
            "actions": [
                {"kind": "goto", "url": "https://example.com/"},
                {"kind": "wait"},
            ]
        },
        {"actions": [{"kind": "scroll", "delta": 5000}]},
        {"actions": [{"kind": "run_script"}]},
        {"actions": [{"kind": "wait"}] * 7},
        {"actions": []},
        {"blocked": "something_else"},
        {"done": "yes"},
        {"notes": [{"fact": "x"}]},
        {"extra": True},
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.text-helper
async def test_invalid_plans_fail_with_a_content_free_code(models, change):
    models.text_call = AsyncMock(return_value={**VALID_PLAN, **change})
    with pytest.raises(BrowserModelError) as caught:
        await models.plan(
            task="Find kits",
            output_schema={"type": "object"},
            observation=PAGE,
            ledger=[],
            history=[],
        )
    assert caught.value.safe_details == {
        "model_error_code": "invalid_plan",
        "text_helper_purpose": "plan",
    }


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.text-helper
@pytest.mark.asyncio
async def test_one_invalid_plan_gets_a_single_metered_repair_attempt(models):
    models.text_call = AsyncMock(
        side_effect=[{**VALID_PLAN, "extra": True}, VALID_PLAN]
    )
    plan = await models.plan(
        task="Find kits",
        output_schema={"type": "object"},
        observation=PAGE,
        ledger=[],
        history=[],
    )
    assert plan["actions"]
    assert models.text_call.await_count == 2
    assert "previous_plan_rejected" in models.text_call.await_args.args[0]


# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.private-storage-and-api,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_private_account_planner_uses_the_permitted_route_with_admission(
    models, monkeypatch
):
    monkeypatch.setenv("WEB_BROWSE_TOGETHER_ZDR_VERIFIED", "true")
    models.private_account = True
    fallback = google_fallback(monkeypatch)
    fallback.return_value.direct_message_content = json.dumps(
        {"notes": [], "actions": [{"kind": "wait"}], "done": False, "blocked": None}
    )

    def forbidden(request):
        raise AssertionError("Private account context reached Together")

    transport(monkeypatch, forbidden)
    plan = await models.plan(
        task="Read my orders",
        output_schema={"type": "object"},
        observation=PAGE,
        ledger=[{"url": "https://example.com/", "title": "Example", "notes": []}],
        history=[{"kind": "click", "target": "0", "outcome": "executed"}],
    )
    assert plan["actions"] == [{"kind": "wait"}]
    assert fallback.await_args.kwargs["max_tokens"] == 4096
    context = json.loads(fallback.await_args.kwargs["messages"][1]["content"])
    assert context["page"]["controls"][0]["id"] == "0"
    assert context["evidence"]["pages"][0]["url"] == "https://example.com/"
    models.before_attempt.assert_awaited_once()
    models.after_attempt.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.structured-data
@pytest.mark.asyncio
async def test_verification_sees_the_ledger_and_quote_proof_accepts_ledger_quotes(
    models,
):
    models.decision = AsyncMock(
        return_value=answers(
            grounded=0.6, answer_complete=0.5, interaction_complete=0.99, empty=0.01
        )
    )
    models.generate = AsyncMock(
        return_value={"grounded": True, "answer_complete": True}
    )
    ledger = [
        {
            "url": "https://example.com/1",
            "title": "One",
            "notes": [{"fact": "Kit A", "quote": "Kit A costs 20 EUR."}],
        }
    ]
    observed = {"url": "https://example.com/2", "title": "Two", "text": "Kit B"}
    data = {"first": "Kit A costs 20 EUR.", "second": "Kit B"}
    assert await models.verify("List kits", observed, data, evidence=ledger) is True
    state = models.decision.await_args.args[0]
    assert state["observed_evidence"]["pages"] == ledger
    assert state["proposed_answer"]["sources"] == [
        {"url": "https://example.com/1", "title": "One"},
        {"url": "https://example.com/2", "title": "Two"},
    ]
    proofs = models.generate.await_args.args[0]["matched_quotations"]
    assert [p["source"] for p in proofs] == ["evidence", "document"]
    # Model-authored facts never count as literal evidence.
    assert (
        matched_quotations(
            {"x": "Kit A"},
            {"text": ""},
            [{"url": "u", "notes": [{"fact": "Kit A", "quote": "other"}]}],
        )
        is None
    )


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.text-helper
@pytest.mark.asyncio
async def test_jev_native_usage_has_exact_two_times_browse_price_and_no_public_skill_markup(
    models,
):
    await models.account(
        call_id="call",
        model="typesafe/jev-1.14",
        host="typesafe",
        usage={
            "input_tokens": 1_000_000,
            "output_tokens": 1000,
            "cache_read_input_tokens": 0,
        },
        elapsed=0.2,
    )
    assert models.cost == Decimal("0.042")
    from backend.shared.python_schemas.web_browse import charged_credits

    assert charged_credits(models.cost) == 84
    models.after_attempt.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_primary_together_model_receives_only_bounded_field_context(
    models, monkeypatch
):
    monkeypatch.setenv("WEB_BROWSE_TOGETHER_ZDR_VERIFIED", "true")
    fallback = google_fallback(monkeypatch)
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer private-test-key"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"text":"Paris"}'}}],
                "usage": {
                    "prompt_tokens": 300,
                    "completion_tokens": 50,
                    "total_tokens": 350,
                    "prompt_tokens_details": {"cached_tokens": 100},
                },
            },
        )

    transport(monkeypatch, handle)
    result = await models.generate(
        {"purpose": "extract", "goal": "Search for Paris", "field": {"label": "Search"}}
    )
    assert result == {"text": "Paris"}
    assert requests[0]["model"] == "deepseek-ai/DeepSeek-V4.1-Flash-1017"
    assert requests[0]["max_tokens"] == 2048
    assert models.attempts[0]["host"] == "together"
    assert models.cost == Decimal("0.0001206")
    fallback.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.private-storage-and-api
@pytest.mark.parametrize(
    "context,verified",
    [
        ({"purpose": "extract", "goal": "Search for Paris"}, False),
        (
            {
                "purpose": "extract",
                "goal": "Read this account",
                "private_account": True,
            },
            True,
        ),
        ({"purpose": "extract", "goal": "Search a medical diagnosis"}, True),
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.private-storage-and-api
@pytest.mark.asyncio
async def test_unverified_retention_or_ineligible_context_never_reaches_together(
    models, monkeypatch, context, verified
):
    monkeypatch.setenv(
        "WEB_BROWSE_TOGETHER_ZDR_VERIFIED", "true" if verified else "false"
    )
    fallback = google_fallback(monkeypatch)

    def forbidden(request):
        raise AssertionError("Ineligible context reached Together")

    transport(monkeypatch, forbidden)
    assert await models.generate(context) == {"text": "Paris"}
    assert fallback.await_args.kwargs["model_id"] == "gemini-3.8-flash"
    assert fallback.await_args.kwargs["thinking_level"] == "LOW"
    assert fallback.await_args.kwargs["request_attempts"] == 1
    assert fallback.await_args.kwargs["request_timeout_seconds"] == 20
    assert models.attempts[0]["host"] == "google_ai_studio"
    assert models.attempts[0]["usage"]["output_tokens"] == 12
    assert models.attempts[0]["usage"]["output_reasoning_tokens"] == 2
    assert models.attempts[0]["usage"]["cache_read_input_tokens"] == 0
    assert models.attempts[0]["usage"]["native_cache_read_input_tokens"] is None
    assert (
        models.attempts[0]["usage"]["cache_read_evidence"]
        == "google_generate_content_proto3_scalar_default"
    )


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.text-helper
@pytest.mark.asyncio
@pytest.mark.parametrize("incomplete", ["missing_total", "failed_response"])
async def test_google_protocol_default_never_fabricates_usage_for_incomplete_or_failed_calls(
    models, monkeypatch, incomplete
):
    monkeypatch.delenv("WEB_BROWSE_TOGETHER_ZDR_VERIFIED", raising=False)
    fallback = google_fallback(monkeypatch)
    response = fallback.return_value
    if incomplete == "missing_total":
        response.usage.total_token_count = None
    else:
        response.success = False
    with pytest.raises(BrowserModelError, match="accounting reconciliation"):
        await models.generate({"purpose": "extract", "goal": "Search for Paris"})
    assert models.attempts[0]["usage"]["cache_read_input_tokens"] is None


# contract-test: supporting surface=rest_api assertions=web-browse.structured-data,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_nonfinite_generated_numbers_fail_after_accounting_without_retry(
    models, monkeypatch
):
    monkeypatch.delenv("WEB_BROWSE_TOGETHER_ZDR_VERIFIED", raising=False)
    fallback = google_fallback(monkeypatch)
    fallback.return_value.direct_message_content = '{"data":{"value":NaN}}'
    with pytest.raises(BrowserModelError, match="invalid JSON"):
        await models.generate({"purpose": "extract", "goal": "Read an observed number"})
    fallback.assert_awaited_once()
    assert models.attempts[0]["complete"] is True and models.cost > 0


# contract-test: supporting surface=rest_api assertions=web-browse.budgets-and-stop,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_missing_google_key_stops_before_model_admission(models, monkeypatch):
    monkeypatch.delenv("WEB_BROWSE_TOGETHER_ZDR_VERIFIED", raising=False)
    fallback = google_fallback(monkeypatch)
    module = sys.modules["backend.apps.ai.llm_providers.google_client"]
    module._get_google_ai_studio_api_key.return_value = None
    with pytest.raises(BrowserModelError, match="unavailable"):
        await models.generate({"purpose": "extract", "goal": "Search for Paris"})
    models.before_attempt.assert_not_awaited()
    fallback.assert_not_awaited()
    assert models.attempts == []


# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_primary_admission_rejection_falls_back_once_with_its_own_native_usage(
    models, monkeypatch
):
    monkeypatch.setenv("WEB_BROWSE_TOGETHER_ZDR_VERIFIED", "true")
    fallback = google_fallback(monkeypatch)
    transport(monkeypatch, lambda request: httpx.Response(429, json={"error": "quota"}))
    assert await models.generate(
        {"purpose": "extract", "goal": "Search for Paris"}
    ) == {"text": "Paris"}
    assert len(models.attempts) == 2
    assert models.attempts[0]["cost_usd"] == "0"
    assert models.attempts[1]["model"] == "google/gemini-3.8-flash"
    fallback.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.budgets-and-stop
@pytest.mark.asyncio
async def test_missing_provider_usage_stops_without_free_success_or_blind_retry(
    models, monkeypatch
):
    monkeypatch.setenv("WEB_BROWSE_TOGETHER_ZDR_VERIFIED", "true")
    fallback = google_fallback(monkeypatch)
    transport(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": '{"text":"Paris"}'}}]}
        ),
    )
    with pytest.raises(BrowserModelError, match="accounting reconciliation"):
        await models.generate({"purpose": "extract", "goal": "Search for Paris"})
    assert len(models.attempts) == 1 and not models.attempts[0]["complete"]
    assert models.after_attempt.await_args.args[1]["complete"] is False
    fallback.assert_not_awaited()
