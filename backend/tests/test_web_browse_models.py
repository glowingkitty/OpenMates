"""Offline provider policy and native accounting for Browse's internal helpers."""

from __future__ import annotations

from copy import deepcopy
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
from backend.shared.providers.browser_planner import validate_plan


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
    # Jev alone decides here; the text review is a separate, later call.
    models.generate = AsyncMock(
        return_value={
            "grounded": True,
            "answer_complete": True,
            "interaction_complete": True,
        }
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
    history = {
        "steps": [{"kind": "click", "label": "Search", "url": observed["url"]}],
        "visited_urls": [observed["url"]],
    }
    assert (
        await models.verify(
            "Read the page", observed, {"fact": "Observed facts"}, history=history
        )
        is expected
    )
    models.generate.assert_not_awaited()
    state = models.decision.await_args.args[0]
    assert state["proposed_answer"]["sources"] == [
        {"url": observed["url"], "title": observed["title"]}
    ]
    assert state["observed_page"]["controls"] == [
        {"role": "textbox", "label": "Search", "value": "query"}
    ]
    assert state["interaction_history"] == history
    assert models.no_results is (empty >= 0.95 and acted >= 0.95)


# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.structured-data
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply,expected",
    [
        (
            {"grounded": True, "answer_complete": True, "interaction_complete": True},
            (True, True, True),
        ),
        (
            {"grounded": True, "answer_complete": False, "interaction_complete": True},
            (True, False, True),
        ),
        (
            {"grounded": "true", "answer_complete": 1, "interaction_complete": "yes"},
            (False, False, False),
        ),
        ({"grounded": True, "answer_complete": True}, (True, True, False)),
        (["grounded"], (False, False, False)),
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.structured-data
async def test_review_accepts_only_strict_booleans_and_sees_the_interaction_history(
    models, reply, expected
):
    models.generate = AsyncMock(return_value=reply)
    observation = {
        "url": "https://example.com/",
        "document_text": "Observed statement. Essential caveat.",
        "text": "Short display",
    }
    data = {
        "statement": "Observed statement. Essential caveat.",
        "count": 3,
        "source_url": "https://example.com/",
    }
    history = {"steps": [], "visited_urls": ["https://example.com/"]}
    verdict = await models.review(
        "Quote the statement with its caveat and URL",
        observation,
        data,
        history=history,
    )
    assert (
        verdict["grounded"],
        verdict["answer_complete"],
        verdict["interaction_complete"],
    ) == expected
    context = models.generate.await_args.args[0]
    assert context["purpose"] == "verify_quotes"
    # The number leaf is not a quotation proof, and it does not fail the review.
    assert [p["path"] for p in context["matched_quotations"]] == [
        "/statement",
        "/source_url",
    ]
    assert context["proposed_answer"] == data
    assert context["interaction_history"] == history
    assert models.verification["review_grounded"] == float(expected[0])
    assert models.verification["review_complete"] == float(expected[1])
    assert models.verification["review_interaction"] == float(expected[2])


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
def test_unquoted_or_nonliteral_data_is_never_listed_as_a_quotation(data):
    assert (
        matched_quotations(
            data, {"url": "https://example.com/", "text": "Observed statement"}
        )
        == []
    )


# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.structured-data
def test_more_quotations_than_the_cap_sends_the_first_four_hundred():
    rows = [{"name": f"Kit {i}", "price": i} for i in range(450)]
    text = " ".join(f"Kit {i}" for i in range(450))
    proofs = matched_quotations({"rows": rows}, {"url": "u", "text": text})
    assert len(proofs) == 400
    assert proofs[0] == {"path": "/rows/0/name", "value": "Kit 0", "source": "document"}
    assert proofs[-1]["path"] == "/rows/399/name"


# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.budgets-and-stop
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.budgets-and-stop
async def test_jev_verify_never_runs_the_text_review_itself(models):
    models.decision = AsyncMock(
        return_value=answers(
            grounded=0.98, answer_complete=0.99, interaction_complete=0.10, empty=0.01
        )
    )
    models.generate = AsyncMock(
        return_value={
            "grounded": True,
            "answer_complete": True,
            "interaction_complete": True,
        }
    )
    assert not await models.verify(
        "Open the next page",
        {"url": "https://example.com/", "text": "Observed statement"},
        {"quote": "Observed statement"},
    )
    models.generate.assert_not_awaited()
    assert models.verification["interaction_score"] == 0.10


# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.cost-accounting
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.cost-accounting
async def test_quote_review_has_a_small_native_output_bound(models, monkeypatch):
    monkeypatch.delenv("WEB_BROWSE_TOGETHER_ZDR_VERIFIED", raising=False)
    fallback = google_fallback(monkeypatch)
    fallback.return_value.direct_message_content = (
        '{"grounded":true,"answer_complete":true,"interaction_complete":true}'
    )
    assert await models.generate(
        {"purpose": "verify_quotes", "goal": "Review matched quotations"}
    ) == {"grounded": True, "answer_complete": True, "interaction_complete": True}
    assert fallback.await_args.kwargs["max_tokens"] == 256
    assert (
        "interaction_complete" in fallback.await_args.kwargs["messages"][0]["content"]
    )
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
        {
            "id": "1",
            "kind": "type",
            "role": "textbox",
            "label": "Search",
            "value": "earlier private words",
        },
        {"id": "2", "kind": "click", "role": "button", "label": "Filter"},
        {
            "id": "3",
            "kind": "select",
            "role": "combobox",
            "label": "Sort",
            "options": [{"label": "Price", "value": "price"}],
        },
        {"id": "4", "kind": "click", "role": "button", "label": "Checkout now"},
        {"id": "5", "kind": "click", "role": "button", "label": "Search"},
    ],
    "observation_id": "o1",
}


def gate_decisions(injection=0.01, **safe):
    """Jev fake keyed by question set; `safe` maps a target label to its score."""

    async def decide(state, questions, screenshot=None):
        if "injection" in questions:
            return answers(injection=injection)
        label = state["target"].get("label") or state["target"].get("url")
        return answers(safe=safe.get(label, 0.99))

    return AsyncMock(side_effect=decide)


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.network-and-content
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.network-and-content
async def test_gate_blocks_a_page_injection_even_for_plain_actions(models):
    models.decision = gate_decisions(injection=0.9)
    reason = await models.gate(
        "Read the page", PAGE, [{"kind": "scroll", "delta": 400}]
    )
    assert reason == "The page contains untrusted instructions requiring review."
    models.decision.assert_awaited_once()
    assert models.verification["gate_injection_score"] == 0.9


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.exclusive-takeover
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filter_safe,expected", [(0.99, None), (0.5, "The next action needs your review.")]
)
# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.exclusive-takeover
async def test_gate_asks_one_single_target_decision_per_non_plain_action(
    models, filter_safe, expected
):
    models.decision = gate_decisions(Filter=filter_safe)
    batch = [
        {"kind": "scroll", "delta": 300},
        {"kind": "click", "target": "0"},
        {"kind": "select", "target": "3", "value": "price"},
        {"kind": "type", "target": "1", "text": "private search words", "submit": True},
        {"kind": "click", "target": "2"},
    ]
    assert await models.gate("Find kits", PAGE, batch) == expected
    calls = [c.args for c in models.decision.await_args_list]
    # One injection question plus one decision each for the submitting type and the button.
    assert sorted(tuple(questions) for _, questions in calls) == [
        ("injection",),
        ("safe",),
        ("safe",),
    ]
    targets = [state["target"] for state, questions in calls if "safe" in questions]
    assert sorted(t["label"] for t in targets) == ["Filter", "Search"]
    for state, questions in calls:
        if "safe" in questions:
            assert set(state) == {"goal", "target", "page_title"}
            assert questions["safe"]["instructions"].startswith(
                "Is activating this target"
            )
    typed = next(t for t in targets if t["label"] == "Search")
    assert "Enter" in typed["effect"]
    # Neither the typed text nor a field's current value reaches the gate.
    assert "private" not in json.dumps([c for c in calls])
    assert models.verification["gate_safe_score"] == min(filter_safe, 0.99)
    assert models.verification["gate_safe_questions"] == 2.0


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.exclusive-takeover
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.exclusive-takeover
async def test_choosing_values_then_clicking_search_asks_only_about_the_button(models):
    models.decision = gate_decisions()
    batch = [
        {"kind": "select", "target": "3", "value": "price"},
        {"kind": "type", "target": "1", "text": "kits"},
        {"kind": "click", "target": "5"},
    ]
    assert await models.gate("Search kits by price", PAGE, batch) is None
    safe = [
        c.args[0]["target"]
        for c in models.decision.await_args_list
        if "safe" in c.args[1]
    ]
    assert safe == [{"id": "5", "kind": "click", "role": "button", "label": "Search"}]
    assert models.decision.await_count == 2


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.cost-accounting
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.cost-accounting
async def test_a_failed_gate_call_propagates_only_after_every_call_finished(models):
    finished = []

    async def decide(state, questions, screenshot=None):
        if "injection" in questions:
            raise BrowserModelError("The browser model quote is unavailable.")
        finished.append(state["target"]["label"])
        return answers(safe=0.99)

    models.decision = AsyncMock(side_effect=decide)
    with pytest.raises(BrowserModelError):
        await models.gate("Find kits", PAGE, [{"kind": "click", "target": "2"}])
    assert finished == ["Filter"]


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.exclusive-takeover
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        {"kind": "click", "target": "4"},
        {"kind": "goto", "url": "https://example.com/checkout"},
        {"kind": "select", "target": "3", "value": "price", "label": "Pay now"},
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.exclusive-takeover
async def test_dangerous_target_blocks_the_batch_without_a_model_call(models, action):
    page = deepcopy(PAGE)
    if action["kind"] == "select":
        # Field preparation asks no model question, but the code check still applies.
        page["controls"][3]["label"] = "Pay now with saved card"
    models.decision = AsyncMock()
    reason = await models.gate(
        "Buy nothing", page, [{"kind": "scroll", "delta": 100}, action]
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
# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.text-helper
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


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.text-helper
def test_tolerated_plan_variations_execute_only_validated_fields():
    plan = validate_plan(
        {
            "thoughts": "ignored",
            "notes": [
                {"fact": "Kit A", "quote": "Kit A costs 20 EUR.", "page": 1},
                {"fact": "no quote"},
                "loose text",
            ],
            "actions": [
                {"kind": "click", "target": "1"},  # Clicking a field is harmless.
                {"kind": "click", "target": "3"},  # So is clicking a dropdown.
                {"kind": "select", "target": "3", "value": "Price"},  # Option label.
                {"kind": "click", "target": "0", "selector": "#x", "text": "x"},
                *[{"kind": "wait"}] * 4,
            ],
            "blocked": "null",
        },
        PAGE,
    )
    assert plan["done"] is False and plan["blocked"] is None
    assert plan["notes"] == [{"fact": "Kit A", "quote": "Kit A costs 20 EUR."}]
    assert plan["malformed_notes"] == 2
    assert plan["actions"] == [
        {"kind": "click", "target": "1"},
        {"kind": "click", "target": "3"},
        {"kind": "select", "target": "3", "value": "price"},
        {"kind": "click", "target": "0"},
        {"kind": "wait"},
        {"kind": "wait"},
    ]
    assert validate_plan({"done": True}, PAGE) == {
        "notes": [],
        "actions": [],
        "done": True,
        "blocked": None,
        "malformed_notes": 0,
    }
    assert validate_plan({"blocked": "", "done": True}, PAGE)["blocked"] is None


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.text-helper
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,code",
    [
        ({"actions": [{"kind": "click", "target": "99"}]}, "unknown_target"),
        (
            {"actions": [{"kind": "type", "target": "2", "text": "x"}]},
            "wrong_target_kind",
        ),
        (
            {"actions": [{"kind": "select", "target": "1", "value": "x"}]},
            "wrong_target_kind",
        ),
        (
            {"actions": [{"kind": "select", "target": "3", "value": "unobserved"}]},
            "unobserved_option",
        ),
        ({"actions": [{"kind": "goto", "url": "http://example.com/"}]}, "bad_goto"),
        (
            {
                "actions": [
                    {"kind": "goto", "url": "https://example.com/"},
                    {"kind": "wait"},
                ]
            },
            "bad_goto",
        ),
        ({"actions": [{"kind": "scroll", "delta": 5000}]}, "bad_field"),
        ({"actions": [{"kind": "run_script"}]}, "unknown_kind"),
        ({"actions": [{"kind": "click"}]}, "missing_field"),
        ({"actions": []}, "no_action"),
        ({"actions": "click"}, "bad_shape"),
        ({"blocked": "something_else"}, "unknown_blocked"),
        ({"done": "yes"}, "bad_shape"),
    ],
)
# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.text-helper
async def test_invalid_plans_fail_with_a_content_free_code(models, change, code):
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
        "plan_error_code": code,
    }
    assert models.text_call.await_count == 2  # One repair attempt, then the code.


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.text-helper
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=web-browse.control-loop,web-browse.text-helper
async def test_one_invalid_plan_gets_a_single_metered_repair_attempt(models):
    models.text_call = AsyncMock(
        side_effect=[
            {**VALID_PLAN, "actions": [{"kind": "click", "target": "99"}]},
            VALID_PLAN,
        ]
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
# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.private-storage-and-api,web-browse.cost-accounting
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
# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.structured-data
async def test_verification_and_review_see_the_ledger_and_ledger_quotes_count(
    models,
):
    models.decision = AsyncMock(
        return_value=answers(
            grounded=0.6, answer_complete=0.5, interaction_complete=0.99, empty=0.01
        )
    )
    models.generate = AsyncMock(
        return_value={
            "grounded": True,
            "answer_complete": True,
            "interaction_complete": True,
        }
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
    assert await models.verify("List kits", observed, data, evidence=ledger) is False
    state = models.decision.await_args.args[0]
    assert state["observed_evidence"]["pages"] == ledger
    assert state["proposed_answer"]["sources"] == [
        {"url": "https://example.com/1", "title": "One"},
        {"url": "https://example.com/2", "title": "Two"},
    ]
    verdict = await models.review("List kits", observed, data, evidence=ledger)
    assert all(verdict.values())
    context = models.generate.await_args.args[0]
    assert context["observed_evidence"]["pages"] == ledger
    assert [p["source"] for p in context["matched_quotations"]] == [
        "evidence",
        "document",
    ]
    # Model-authored facts never count as literal evidence.
    assert (
        matched_quotations(
            {"x": "Kit A"},
            {"text": ""},
            [{"url": "u", "notes": [{"fact": "Kit A", "quote": "other"}]}],
        )
        == []
    )


# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.text-helper
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=web-browse.truthful-completion,web-browse.text-helper
async def test_a_review_context_that_cannot_fit_is_not_sent(models):
    models.generate = AsyncMock()
    huge = {"rows": ["x" * 1000] * 200}
    verdict = await models.review("List rows", {"url": "u", "text": "x"}, huge)
    assert verdict == {
        "grounded": False,
        "answer_complete": False,
        "interaction_complete": False,
    }
    models.generate.assert_not_awaited()
    assert models.verification["review_input_too_large"] == 1.0


# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.text-helper
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.text-helper
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

    assert charged_credits(models.cost) == 63
    models.after_attempt.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.cost-accounting
@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.cost-accounting
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
# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.private-storage-and-api
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
# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.text-helper
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
# contract-test: supporting surface=rest_api assertions=web-browse.structured-data,web-browse.cost-accounting
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
# contract-test: supporting surface=rest_api assertions=web-browse.budgets-and-stop,web-browse.cost-accounting
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
# contract-test: supporting surface=rest_api assertions=web-browse.text-helper,web-browse.cost-accounting
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
# contract-test: supporting surface=rest_api assertions=web-browse.cost-accounting,web-browse.budgets-and-stop
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


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop
def test_plan_keeps_the_valid_actions_before_a_bad_one_and_rejects_a_bad_first_action():
    from backend.shared.providers.browser_planner import PlanInvalid, validate_plan

    observation = {
        "controls": [{"id": "1", "kind": "click", "role": "button", "label": "Next"}]
    }
    good, bad = {"kind": "click", "target": "1"}, {"kind": "hover", "target": "1"}
    plan = validate_plan(
        {"notes": [], "actions": [good, bad, good], "done": False, "blocked": None},
        observation,
    )
    assert plan["actions"] == [good]
    with pytest.raises(PlanInvalid):
        validate_plan(
            {"notes": [], "actions": [bad, good], "done": False, "blocked": None},
            observation,
        )


# contract-test: supporting surface=rest_api assertions=web-browse.control-loop
@pytest.mark.parametrize(
    "spelled",
    [
        {"action": "click", "target": "1"},
        {"click": {"target": "1"}},
        {"kind": "Press", "target": "1"},
    ],
)
def test_plan_accepts_harmless_spellings_of_an_action_and_still_validates_the_target(
    spelled,
):
    from backend.shared.providers.browser_planner import PlanInvalid, validate_plan

    observation = {
        "controls": [{"id": "1", "kind": "click", "role": "button", "label": "Next"}]
    }
    plan = validate_plan(
        {"notes": [], "actions": [spelled], "done": False, "blocked": None}, observation
    )
    assert plan["actions"] == [{"kind": "click", "target": "1"}]
    with pytest.raises(PlanInvalid):
        validate_plan({"actions": [{"action": "click", "target": "9"}]}, observation)
