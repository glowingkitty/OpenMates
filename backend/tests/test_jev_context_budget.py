"""Transport and partition limits, without external inference."""

# contract-test-file: infrastructure

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.shared.providers.typesafe.budget import (
    MAX_ESTIMATED_INPUT_TOKENS, estimate_request_tokens, estimate_text_tokens,
)
from backend.shared.providers.typesafe.batching import (
    candidate_batches, evaluate_batches, question_batches, run_bounded_batches,
)
from backend.shared.providers.typesafe.client import (
    DecisionRequestTooLarge, DecisionResponseInvalid, JevDecisionClient,
)
from backend.shared.providers.typesafe.models import DecisionResponse


QUESTION = {"type": "noul", "instructions": "Is this relevant?"}


@pytest.mark.asyncio
async def test_dense_input_rejected_before_credentials_or_network():
    secrets = AsyncMock()
    transport = AsyncMock()
    client = JevDecisionClient(secrets_manager=secrets, http_client=transport)
    state = {"text": "😀" * 16_000}
    assert len(json.dumps(state, ensure_ascii=False)) < 80_000
    with pytest.raises(DecisionRequestTooLarge):
        await client.evaluate(state=state, questions={"ok": QUESTION})
    secrets.get_secret.assert_not_awaited()
    transport.post.assert_not_awaited()


def test_estimator_includes_questions_and_literal_special_tokens():
    assert estimate_text_tokens("<|endoftext|>你好😀") > 0
    assert estimate_request_tokens("hello", {"ok": QUESTION}) > estimate_request_tokens("hello", {})
    with pytest.raises(DecisionRequestTooLarge):
        JevDecisionClient._validate_request("tiny", {
            "ok": {**QUESTION, "instructions": "😀" * 16_000},
        })


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 413, 422, 502, 503])
async def test_provider_context_error_is_typed_and_never_retried(status):
    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {
            "code": "context_length_exceeded", "message": "private-input-fragment",
        }})

    secrets = AsyncMock()
    secrets.get_secret.return_value = "synthetic-key"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(DecisionRequestTooLarge):
            await JevDecisionClient(secrets_manager=secrets, http_client=http, max_retries=2).evaluate(
                state="hello", questions={"ok": QUESTION},
            )
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_candidate_partition_complete_stable_and_usage_summed():
    candidates = [(f"candidate_{i}", {"id": f"candidate_{i}", "text": "😀" * 3_000})
                  for i in range(10)]
    questions = {key: QUESTION for key, _ in candidates}
    batches = candidate_batches(state={"query": "compare"}, field="candidates",
                                candidates=candidates, questions=questions)
    assert len(batches) > 1
    assert [key for batch in batches for key in batch.questions] == list(questions)
    for batch in batches:
        assert {row["id"] for row in batch.state["candidates"]} == set(batch.questions)
        assert estimate_request_tokens(batch.state, batch.questions) <= MAX_ESTIMATED_INPUT_TOKENS

    async def evaluate(*, state, questions):
        return DecisionResponse(model="jev", answers={
            key: {"type": "noul", "noul": .9} for key in questions
        }, usage={"input_tokens": 100, "output_tokens": 2})

    result = await evaluate_batches(batches, evaluate)
    assert list(result.answers) == list(questions)
    assert result.usage.input_tokens == 100 * len(batches)
    assert result.usage.output_tokens == 2 * len(batches)


@pytest.mark.asyncio
async def test_missing_later_answer_prevents_partial_merge():
    questions = {f"q{i}": QUESTION for i in range(161)}
    batches = question_batches("hello", questions)

    async def evaluate(*, state, questions):
        answers = {key: {"type": "noul", "noul": .9} for key in questions}
        if "q160" in answers:
            answers.pop("q160")
        return DecisionResponse(model="jev", answers=answers)

    with pytest.raises(DecisionResponseInvalid):
        await evaluate_batches(batches, evaluate)


def test_batch_cap_and_essential_state_reject_complete_request():
    with pytest.raises(DecisionRequestTooLarge):
        question_batches("hello", {f"q{i}": QUESTION for i in range(160 * 8 + 1)})
    with pytest.raises(DecisionRequestTooLarge):
        question_batches({"graph": "😀" * 16_000}, {"ok": QUESTION})


@pytest.mark.asyncio
async def test_near_thirty_thousand_input_is_sent_completely():
    state = {"text": "😀" * 14_700 + " KEEP THE FINAL INSTRUCTION"}
    questions = {"ok": QUESTION}
    estimate = estimate_request_tokens(state, questions)
    assert 29_000 < estimate <= 30_000
    captured = []

    async def handle(request):
        body = json.loads(request.content)
        captured.append(body)
        return httpx.Response(200, json={"model": "jev", "answers": {
            "ok": {"type": "noul", "noul": .9},
        }})

    secrets = AsyncMock()
    secrets.get_secret.return_value = "synthetic-key"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        await JevDecisionClient(secrets_manager=secrets, http_client=http).evaluate(
            state=state, questions=questions,
        )
    assert len(captured) == 1
    assert captured[0]["state"] == state
    assert captured[0]["questions"] == questions


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "sibling", "caller"])
async def test_pending_batches_cancelled_and_awaited(failure):
    started = asyncio.Event()
    ended = []
    active = 0
    peak = 0

    async def operation(index):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        started.set()
        try:
            if failure == "sibling" and index == 0:
                await asyncio.sleep(.01)
                raise RuntimeError("failed batch")
            await asyncio.Event().wait()
        finally:
            active -= 1
            ended.append(index)

    task = asyncio.create_task(run_bounded_batches(list(range(8)), operation, timeout_seconds=.05))
    await started.wait()
    if failure == "caller":
        task.cancel()
    expected = {"timeout": TimeoutError, "sibling": RuntimeError, "caller": asyncio.CancelledError}[failure]
    with pytest.raises(expected):
        await task
    assert 1 <= peak <= 3
    assert active == 0
    assert ended
