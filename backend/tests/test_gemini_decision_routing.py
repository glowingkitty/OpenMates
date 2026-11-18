"""Gemini Decision 1 as a per-purpose default decider with automatic Jev fallback (TASK-1809).

No network: httpx.MockTransport stands in for both Google's Decisions API and TypeSafe.
"""

# contract-test-file: infrastructure

from __future__ import annotations

import base64
import json
import logging
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from backend.apps.ai.utils import internal_decisions
from backend.shared.providers.google import decisions as gemini_decisions
from backend.shared.providers.google.decisions import (
    GEMINI_DECISIONS_URL,
    GeminiDecisionBlocked,
    GeminiDecisionClient,
    GeminiDecisionError,
    request_body,
)
from backend.shared.providers.typesafe import routing
from backend.shared.providers.typesafe.client import TYPESAFE_DECISIONS_URL, JevDecisionClient
from backend.shared.python_utils.internal_llm_policy import InternalLlmPolicy

ROUTED = "search_relevance"
QUESTIONS = {"fits": {"type": "noul", "instructions": "Does the result fit?",
                      "criteria": {"true": "it fits", "false": "it does not"}}}


class Secrets:
    async def get_secret(self, *, secret_path: str, secret_key: str) -> str:
        return {"kv/data/providers/google_ai_studio": "google-key",
                "kv/data/providers/typesafe": "typesafe-key"}.get(secret_path, "")


def _gemini_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"answers": {"fits": {"type": "noul", "noul": 0.9, "confidence": 0.8}},
                                     "usage": {"total_input_tokens": 42}})


def _jev_ok() -> httpx.Response:
    return httpx.Response(200, json={"model": "jev-1.14.0", "answers": {"fits": {"type": "noul", "noul": 0.2}},
                                     "usage": {"input_tokens": 40, "output_tokens": 0}})


def _transport(gemini_handler, calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append("gemini" if url == GEMINI_DECISIONS_URL else "jev" if url == TYPESAFE_DECISIONS_URL else url)
        if url == GEMINI_DECISIONS_URL:
            return gemini_handler(request)
        return _jev_ok()
    return httpx.MockTransport(handler)


async def _decide(gemini_handler, *, purpose: str = ROUTED, **kwargs):
    calls: list[str] = []
    async with httpx.AsyncClient(transport=_transport(gemini_handler, calls)) as http_client:
        result = await JevDecisionClient(secrets_manager=Secrets(), http_client=http_client, max_retries=0,
                                         telemetry_purpose=purpose, **kwargs).evaluate(
            state={"query": "sourdough guide"}, questions=QUESTIONS)
    return result, calls


# --- routing config -------------------------------------------------------------------------

def _app_yml(tmp_path: Path, block: str) -> Path:
    path = tmp_path / "app.yml"
    path.write_text(f"skills:\n  - id: ask\n    skill_config:\n{block}", encoding="utf-8")
    return path


# contract-test: direct surface=rest_api assertions=ai-model-routing.decisions.per-purpose-model-with-jev-fallback
def test_repo_routes_only_reviewed_purposes_to_gemini() -> None:
    default, purposes = routing.decision_routes()
    assert default == (routing.JEV_DECISION_MODEL,)
    assert set(purposes) == {"search_relevance", "shopping_visual_relevance", "result_photo_relevance"}
    assert all(route == (routing.GEMINI_DECISION_MODEL, routing.JEV_DECISION_MODEL) for route in purposes.values())
    for kept in ("preprocess_decision", "postprocess_decision", "image_safety", "pdf_text_injection", None):
        assert not routing.gemini_first(kept)


def test_missing_block_means_jev_only(tmp_path: Path) -> None:
    path = _app_yml(tmp_path, "      other: 1\n")
    assert routing.decision_routes.__wrapped__(path) == ((routing.JEV_DECISION_MODEL,), {})


@pytest.mark.parametrize("route", [
    "[google/gemini-decision-1]",                                  # no Jev fallback
    "[typesafe/jev-1.14, google/gemini-decision-1]",               # Jev not last
    "[example/unknown, typesafe/jev-1.14]",                        # unknown model
    "[typesafe/jev-1.14, typesafe/jev-1.14]",                      # duplicate
    "[]",
])
def test_invalid_routes_are_rejected(tmp_path: Path, route: str) -> None:
    path = _app_yml(tmp_path, f"      decision_routing:\n        purposes:\n          x: {route}\n")
    with pytest.raises(ValueError):
        routing.decision_routes.__wrapped__(path)


# --- Decisions API body ---------------------------------------------------------------------

def test_request_body_maps_jev_questions_and_images() -> None:
    body = request_body({"q": "x"}, {
        **QUESTIONS,
        "structured": {"type": "noul", "instructions": {"question": "fits?", "candidate_id": "a"}},
        "level": {"type": "score", "instructions": "how well", "criteria": ["no", "yes"]},
    }, {"ref-1": (b"\xff\xd8jpeg", "jpg")})
    assert body["model"] == "gemini-decision-1"
    assert body["questions"]["fits"]["criteria"] == {"true_description": "it fits", "false_description": "it does not"}
    assert json.loads(body["questions"]["structured"]["instructions"]) == {"question": "fits?", "candidate_id": "a"}
    assert body["questions"]["level"]["criteria"] == ["no", "yes"]
    assert [block["type"] for block in body["input"]] == ["text", "text", "image"]
    assert body["input"][1]["text"] == "Image ref-1:"
    assert base64.b64decode(body["input"][2]["data"]) == b"\xff\xd8jpeg"
    assert body["input"][2]["mime_type"] == "image/jpeg"


@pytest.mark.asyncio
@pytest.mark.parametrize("response,error,reason", [
    (httpx.Response(400, json={"error": {"code": "prohibited_content"}}), GeminiDecisionBlocked, "blocked"),
    (httpx.Response(429, json={"error": {"code": "rate_limit"}}), GeminiDecisionError, "rate_limited"),
    (httpx.Response(400, json={"error": {"code": "invalid_request"}}), GeminiDecisionError, "http_400"),
    (httpx.Response(200, json={"answers": {}}), GeminiDecisionError, "missing_answers"),
    (httpx.Response(200, text="not json"), GeminiDecisionError, "invalid_response"),
])
async def test_gemini_failures_carry_a_reason(response, error, reason) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as http_client:
        with pytest.raises(error) as raised:
            await GeminiDecisionClient(secrets_manager=Secrets()).evaluate(
                http_client, state={}, questions=QUESTIONS)
    assert raised.value.reason == reason


@pytest.mark.asyncio
async def test_too_many_options_never_calls_google() -> None:
    calls: list[str] = []
    questions = {"pick": {"type": "choice", "instructions": "pick",
                          "criteria": {f"o{i}": None for i in range(gemini_decisions.MAX_CHOICE_OPTIONS + 1)}}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append("x") or _jev_ok())) as client:
        with pytest.raises(GeminiDecisionError) as raised:
            await GeminiDecisionClient(secrets_manager=Secrets()).evaluate(client, state={}, questions=questions)
    assert raised.value.reason == "too_many_options" and calls == []


# --- Gemini first, Jev fallback ---------------------------------------------------------------

# contract-test: direct surface=rest_api assertions=ai-model-routing.decisions.per-purpose-model-with-jev-fallback
@pytest.mark.asyncio
async def test_routed_purpose_is_answered_by_gemini_and_logged(caplog) -> None:
    caplog.set_level(logging.INFO)
    result, calls = await _decide(_gemini_ok, telemetry_task_id="task-1")
    assert calls == ["gemini"]
    assert result.model == "google/gemini-decision-1" and result.provider == "google_ai_studio"
    assert result.answers["fits"].noul == 0.9
    assert result.usage.input_tokens == 42 and result.usage.output_tokens == 0
    assert ("Decision decided: purpose=search_relevance model=google/gemini-decision-1 "
            "provider=google_ai_studio task=task-1") in caplog.text


# contract-test: direct surface=rest_api assertions=ai-model-routing.decisions.per-purpose-model-with-jev-fallback
@pytest.mark.asyncio
@pytest.mark.parametrize("gemini_handler,reason", [
    (lambda request: httpx.Response(400, json={"error": {"code": "safety"}}), "blocked"),
    (lambda request: httpx.Response(503, json={}), "http_503"),
    (lambda request: httpx.Response(429, json={}), "rate_limited"),
    (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=request)), "timeout"),
])
async def test_gemini_failure_falls_back_to_jev(caplog, gemini_handler, reason) -> None:
    caplog.set_level(logging.INFO)
    result, calls = await _decide(gemini_handler)
    assert calls == ["gemini", "jev"]
    assert result.answers["fits"].noul == 0.2
    assert f"Decision fallback to Jev: purpose=search_relevance reason={reason}" in caplog.text
    assert "Decision decided: purpose=search_relevance model=" in caplog.text
    assert "provider=typesafe" in caplog.text


# contract-test: direct surface=rest_api assertions=ai-model-routing.decisions.per-purpose-model-with-jev-fallback
@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"purpose": "image_safety"},                 # not routed
    {"provider": "typesafe"},                    # pinned provider (benchmarks, safety)
    {"allow_gemini": False},                     # user's AI settings turn Google off
    {"model": "typesafe/jev-1.13"},              # pinned Jev version
])
async def test_unrouted_or_pinned_clients_never_call_google(kwargs) -> None:
    _, calls = await _decide(_gemini_ok, **kwargs)
    assert calls == ["jev"]


def _prepared_jpeg() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (336, 336), (200, 30, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


# contract-test: direct surface=rest_api assertions=ai-model-routing.decisions.per-purpose-model-with-jev-fallback
@pytest.mark.asyncio
async def test_image_decision_sends_images_to_gemini() -> None:
    reference = "a" * 32
    seen: dict = {}

    def gemini(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _gemini_ok(request)

    calls: list[str] = []
    async with httpx.AsyncClient(transport=_transport(gemini, calls)) as http_client:
        result = await JevDecisionClient(secrets_manager=Secrets(), http_client=http_client, max_retries=0,
                                         telemetry_purpose="shopping_visual_relevance").evaluate_with_images(
            state={"photos": [reference]}, questions=QUESTIONS, images={reference: _prepared_jpeg()})
    assert calls == ["gemini"] and result.model == "google/gemini-decision-1"
    assert [block["type"] for block in seen["input"]] == ["text", "text", "image"]


# --- user AI settings -----------------------------------------------------------------------

# contract-test: direct surface=rest_api assertions=ai-model-routing.decisions.per-purpose-model-with-jev-fallback
def test_policy_that_turns_off_google_disables_gemini(monkeypatch) -> None:
    def servers(self, ref, cfg=None):
        return frozenset({"typesafe"}) if ref == "google/gemini-decision-1" else frozenset({"typesafe", "openrouter"})

    monkeypatch.setattr(InternalLlmPolicy, "allowed_servers", servers)
    policy = InternalLlmPolicy(disabled_ai_models=frozenset({"gemini-decision-1"}))
    client = internal_decisions.decision_client_for_policy(policy, secrets_manager=Secrets(), purpose=ROUTED)
    assert isinstance(client, JevDecisionClient) and client._allow_gemini is False

    monkeypatch.setattr(InternalLlmPolicy, "allowed_servers",
                        lambda self, ref, cfg=None: frozenset({"typesafe", "openrouter", "google_ai_studio"}))
    client = internal_decisions.decision_client_for_policy(policy, secrets_manager=Secrets(), purpose=ROUTED)
    assert client._allow_gemini is True
