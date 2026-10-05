"""Pack independent Jev decisions without dropping inputs or partial answers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Sequence, TypeVar

from backend.shared.providers.typesafe.client import (
    DecisionRequestTooLarge, DecisionResponseInvalid, JevDecisionClient, MAX_QUESTIONS,
)
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.providers.typesafe.budget import serialize, sizing_cache


MAX_DECISION_BATCHES = 8
MAX_BATCH_PARALLEL = 3
BATCH_DEADLINE_SECONDS = 12.0
logger = logging.getLogger(__name__)
T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class DecisionRequest:
    state: Any
    questions: Mapping[str, Mapping[str, Any]]


def pack_batches(
    items: Sequence[T], build: Callable[[list[T]], DecisionRequest],
    *, max_batches: int = MAX_DECISION_BATCHES, max_state_chars: int | None = None,
) -> list[DecisionRequest]:
    """Validate the entire partition before starting any provider operation."""
    with sizing_cache():
        return _pack_batches(items, build, max_batches=max_batches, max_state_chars=max_state_chars)


def _pack_batches(
    items: Sequence[T], build: Callable[[list[T]], DecisionRequest], *,
    max_batches: int, max_state_chars: int | None,
) -> list[DecisionRequest]:
    if max_batches < 1:
        raise ValueError("max_batches must be positive")
    batches: list[DecisionRequest] = []
    current: list[T] = []

    def validate(request: DecisionRequest) -> None:
        if max_state_chars is not None and len(serialize(request.state)) > max_state_chars:
            raise DecisionRequestTooLarge("batch state exceeds its serialized bound")
        JevDecisionClient._validate_request(request.state, request.questions)

    for item in items:
        proposed = build([*current, item])
        try:
            validate(proposed)
        except DecisionRequestTooLarge:
            if not current:
                raise
            batches.append(build(current))
            current = [item]
            proposed = build(current)
            validate(proposed)
        else:
            current.append(item)
        if len(batches) >= max_batches:
            raise DecisionRequestTooLarge("decision input exceeds the bounded batch count")
    if current:
        batches.append(build(current))
    return batches


def question_batches(state: Any, questions: Mapping[str, Mapping[str, Any]]) -> list[DecisionRequest]:
    if len(questions) > MAX_DECISION_BATCHES * MAX_QUESTIONS:
        raise DecisionRequestTooLarge("decision questions exceed the bounded batch count")
    return pack_batches(list(questions.items()), lambda rows: DecisionRequest(state, dict(rows)))


def candidate_batches(
    *, state: Mapping[str, Any], field: str, candidates: Sequence[tuple[str, Any]],
    questions: Mapping[str, Mapping[str, Any]],
) -> list[DecisionRequest]:
    """Each stable question ID travels with exactly its corresponding candidate."""
    ids = [key for key, _ in candidates]
    if len(set(ids)) != len(ids) or set(ids) != set(questions):
        raise ValueError("candidate and question IDs must match exactly")
    return pack_batches(candidates, lambda rows: DecisionRequest(
        {**state, field: [value for _, value in rows]},
        {key: questions[key] for key, _ in rows},
    ))


async def run_bounded_batches(
    batches: Sequence[T], operation: Callable[[T], Awaitable[R]], *,
    max_parallel: int = MAX_BATCH_PARALLEL, timeout_seconds: float = BATCH_DEADLINE_SECONDS,
) -> list[R]:
    """Cancel and await unfinished work on failure, timeout or caller cancellation."""
    if not 1 <= len(batches) <= MAX_DECISION_BATCHES or max_parallel < 1 or timeout_seconds <= 0:
        raise DecisionRequestTooLarge("invalid bounded batch execution")
    semaphore = asyncio.Semaphore(min(max_parallel, MAX_BATCH_PARALLEL))

    async def execute(batch: T) -> R:
        async with semaphore:
            return await operation(batch)

    tasks = [asyncio.create_task(execute(batch)) for batch in batches]
    try:
        return await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout_seconds)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def evaluate_batches(
    batches: Sequence[DecisionRequest], evaluate: Callable[..., Awaitable[DecisionResponse]], *,
    timeout_seconds: float = BATCH_DEADLINE_SECONDS,
) -> DecisionResponse:
    """Merge only complete, nonoverlapping decisions and sum provider usage."""
    expected: set[str] = set()
    for batch in batches:
        JevDecisionClient._validate_request(batch.state, batch.questions)
        if expected.intersection(batch.questions):
            raise DecisionResponseInvalid("duplicate question IDs across batches")
        expected.update(batch.questions)

    async def call(batch: DecisionRequest) -> DecisionResponse:
        response = await evaluate(state=batch.state, questions=batch.questions)
        if set(response.answers) != set(batch.questions):
            raise DecisionResponseInvalid("batch response IDs do not match requested decisions")
        return response

    responses = await run_bounded_batches(batches, call, timeout_seconds=timeout_seconds)
    logger.info("Jev decision batches completed: batches=%d questions=%d input_tokens=%d",
                len(batches), len(expected), sum(row.usage.input_tokens for row in responses))
    return DecisionResponse(
        model=responses[0].model,
        answers={key: answer for response in responses for key, answer in response.answers.items()},
        usage={"input_tokens": sum(row.usage.input_tokens for row in responses),
               "output_tokens": sum(row.usage.output_tokens for row in responses)},
    )
