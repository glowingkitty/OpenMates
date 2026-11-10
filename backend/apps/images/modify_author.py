"""Author loop of the images-modify skill.

An author model that can see pictures writes one deterministic Python editing
program (contract and prompt in ``modify_program.py``); the program runs in the
image-edit sandbox on the original input files (``e2b_image_edit.py``), so the
model never returns pixels itself. When the request states requirements, the
computed picture is judged by Jev (``modify_review.py``); a failed run, an
invalid program or a clearly unmet requirement triggers a bounded number of
correction rounds in the same short conversation. After the last round the
best valid picture is delivered with the requirements it still misses. Models
are tried in a fixed order; a provider failure moves on to the next one.

Every provider call is recorded in ``ModifyAuthorResult.usage`` and every
sandbox run in ``sandbox_seconds`` so the task can bill exactly what was used.
A request that ends without any valid picture raises ``ModifyAuthorError`` and
the caller charges nothing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Sequence

from backend.apps.images.modify_program import (
    MAX_INSTRUCTION_CHARS,
    InvalidProgramError,
    ModifyInputError,
    PreparedInput,
    SYSTEM_PROMPT,
    build_author_message,
    build_correction_message,
    extract_program,
    reduced_jpeg,
    validate_program,
)
from backend.apps.images.modify_review import review_image_with_jev
from backend.apps.images.vector_author import (
    VECTOR_AUTHOR_MODELS,
    VECTOR_REVIEW_MODEL,
    VectorReview,
    VectorUsage,
    normalize_requirements,
)
from backend.shared.providers.e2b_image_edit import OUTPUT_TYPES, ImageEditInput, ImageEditRun, ImageEditSession

logger = logging.getLogger(__name__)

# Ordered: the first model that produces a valid picture answers. All three take image input
# (backend/providers/*.yml input_types include "image") through call_main_llm_stream's image_url blocks.
MODIFY_AUTHOR_MODELS: tuple[str, ...] = VECTOR_AUTHOR_MODELS
MODIFY_AUTHOR_REASONING = "MEDIUM"
MODIFY_AUTHOR_TEMPERATURE = 0.2
MODIFY_AUTHOR_MAX_OUTPUT_TOKENS = 24_000
MAX_CORRECTION_ROUNDS = 2

STAGE_WRITING = "writing"
STAGE_RUNNING = "running"
STAGE_CHECKING = "checking"
STAGE_CORRECTING = "correcting"

REVIEW_ACCEPTED = "accepted"
REVIEW_CORRECTED = "corrected"
REVIEW_UNMET_DELIVERED = "unmet_delivered"
REVIEW_SKIPPED = "skipped"
REVIEW_UNAVAILABLE = "unavailable"

ProgressCallback = Callable[[str, int, Optional[bytes]], Awaitable[None]]
StreamFunction = Callable[..., AsyncIterator[Any]]
ReviewFunction = Callable[..., Awaitable[VectorReview]]
RunFunction = Callable[[str, Sequence[ImageEditInput]], Awaitable[ImageEditRun]]


class ModifyAuthorError(RuntimeError):
    """No author model produced a valid picture within the rounds; nothing is charged."""


@dataclass
class ModifyAuthorResult:
    """Final picture plus everything needed for billing, provenance and a later change."""

    image: bytes
    mime_type: str
    width: int
    height: int
    program: str
    model_id: str
    attempts: int  # rounds run by the answering model
    review_status: str  # accepted | corrected | unmet_delivered | skipped | unavailable
    unmet_requirements: tuple[str, ...] = ()
    usage: list[VectorUsage] = field(default_factory=list)
    sandbox_seconds: list[float] = field(default_factory=list)
    delivered_attempt: int = 1  # round whose picture is delivered (earlier than attempts when unmet)


class _BackgroundSession:
    """Starts the sandbox while the first program is written; runs wait for it, close always kills it."""

    def __init__(self, session: ImageEditSession) -> None:
        self._session = session
        self._started = asyncio.create_task(session.__aenter__())

    async def run(self, program: str, inputs: Sequence[ImageEditInput]) -> ImageEditRun:
        await self._started
        return await self._session.run(program, inputs)

    async def close(self) -> None:
        # The start runs in a worker thread and cannot be cancelled; wait for it so the sandbox is killed.
        await asyncio.wait([self._started])
        if not self._started.cancelled() and self._started.exception() is not None:
            return  # a failed start already cleaned up after itself
        await self._session.__aexit__(None, None, None)


@dataclass
class _Candidate:
    run: ImageEditRun
    program: str
    attempt: int
    unmet: tuple[str, ...]


async def _stream_program(
    *, stream_fn: StreamFunction, task_id: str, model_id: str, messages: list[dict[str, Any]],
    secrets_manager: Any,
) -> tuple[str, int, int]:
    """Run one author call; return its text and reported token usage."""
    text = ""
    input_tokens = output_tokens = 0
    async for chunk in stream_fn(
        task_id=task_id, model_id=model_id, system_prompt=SYSTEM_PROMPT, message_history=messages,
        temperature=MODIFY_AUTHOR_TEMPERATURE, secrets_manager=secrets_manager,
        max_tokens=MODIFY_AUTHOR_MAX_OUTPUT_TOKENS, requested_reasoning_level=MODIFY_AUTHOR_REASONING,
        private_logging=True,
    ):
        if isinstance(chunk, str):
            text += chunk
        elif hasattr(chunk, "input_tokens") and hasattr(chunk, "output_tokens"):
            input_tokens += int(chunk.input_tokens or 0)
            output_tokens += int(chunk.output_tokens or 0)
    return text, input_tokens, output_tokens


def _final_status(attempt: int, review: VectorReview) -> str:
    if review.status == "unavailable":
        return REVIEW_UNAVAILABLE
    return REVIEW_CORRECTED if attempt > 1 else REVIEW_ACCEPTED


async def author_modification(
    *, task_id: str, instructions: str, inputs: Sequence[PreparedInput], requirements: Sequence[str] = (),
    output_type: str = "png", source_program: Optional[str] = None, secrets_manager: Any = None,
    progress: Optional[ProgressCallback] = None, stream_fn: Optional[StreamFunction] = None,
    review_fn: Optional[ReviewFunction] = None, run_fn: Optional[RunFunction] = None,
    models: Sequence[str] = MODIFY_AUTHOR_MODELS, max_attempts: int = MAX_CORRECTION_ROUNDS + 1,
) -> ModifyAuthorResult:
    """Write an editing program, run it, check the picture against the requirements and correct it."""
    instructions = " ".join(instructions.split()) if instructions else ""
    if not instructions:
        raise ModifyInputError("the instructions are empty")
    if len(instructions) > MAX_INSTRUCTION_CHARS:
        raise ModifyInputError(f"the instructions are longer than {MAX_INSTRUCTION_CHARS} characters")
    if output_type not in OUTPUT_TYPES:
        raise ModifyInputError(f"unknown output type {output_type!r}")
    if stream_fn is None:
        from backend.apps.ai.utils.llm_utils import call_main_llm_stream
        stream_fn = call_main_llm_stream
    review = review_fn or review_image_with_jev
    requirements = normalize_requirements(requirements)
    uploads = [item.upload for item in inputs]
    request = build_author_message(instructions=instructions, requirements=requirements, inputs=inputs,
                                   output_type=output_type, source_program=source_program)
    usage: list[VectorUsage] = []
    sandbox_seconds: list[float] = []
    failures: list[str] = []

    async def report(stage: str, attempt: int, draft: Optional[bytes] = None) -> None:
        if progress:
            await progress(stage, attempt, draft)

    def result(candidate: _Candidate, model_id: str, status: str, attempts: int) -> ModifyAuthorResult:
        run = candidate.run
        return ModifyAuthorResult(
            image=run.image or b"", mime_type=run.mime_type or OUTPUT_TYPES[output_type], width=run.width,
            height=run.height, program=candidate.program, model_id=model_id, attempts=attempts,
            review_status=status, unmet_requirements=candidate.unmet, usage=usage, sandbox_seconds=sandbox_seconds,
            delivered_attempt=candidate.attempt,
        )

    async with AsyncExitStack() as stack:
        if run_fn is None:
            background = _BackgroundSession(ImageEditSession(secrets_manager, output_type=output_type))
            stack.push_async_callback(background.close)
            run_fn = background.run
        for model_id in models:
            messages: list[dict[str, Any]] = [request]
            best: Optional[_Candidate] = None
            attempt = 0
            feedback = ""
            try:
                for attempt in range(1, max_attempts + 1):
                    await report(STAGE_WRITING if attempt == 1 else STAGE_CORRECTING, attempt)
                    started = time.monotonic()
                    text, input_tokens, output_tokens = await _stream_program(
                        stream_fn=stream_fn, task_id=task_id, model_id=model_id, messages=messages,
                        secrets_manager=secrets_manager,
                    )
                    usage.append(VectorUsage(STAGE_WRITING if attempt == 1 else STAGE_CORRECTING, model_id,
                                             input_tokens, output_tokens))
                    logger.info("[%s] Modify author %s attempt %s wrote %s chars in %.1fs", task_id, model_id,
                                attempt, len(text), time.monotonic() - started)
                    program = extract_program(text)
                    preview: Optional[bytes] = None
                    try:
                        if not program:
                            raise InvalidProgramError("the answer was not a Python module that defines edit(inputs)")
                        validate_program(program)
                        await report(STAGE_RUNNING, attempt)
                        run = await run_fn(program, uploads)
                        sandbox_seconds.append(run.seconds)
                        if run.error or not run.image:
                            raise InvalidProgramError(run.error or "the program wrote no picture")
                    except InvalidProgramError as exc:
                        feedback = str(exc)
                    else:
                        preview = reduced_jpeg(run.image)
                        candidate = _Candidate(run=run, program=program, attempt=attempt, unmet=())
                        if not requirements:
                            return result(candidate, model_id, REVIEW_SKIPPED, attempt)
                        await report(STAGE_CHECKING, attempt, preview)
                        outcome = await review(
                            image=run.image, instructions=instructions, requirements=requirements,
                            input_images=[item.preview for item in inputs],
                            secrets_manager=secrets_manager, task_id=task_id,
                        )
                        if outcome.input_tokens:
                            usage.append(VectorUsage("review", VECTOR_REVIEW_MODEL, outcome.input_tokens, 0))
                        if outcome.accepted:
                            return result(candidate, model_id, _final_status(attempt, outcome), attempt)
                        candidate.unmet = outcome.unmet
                        # The best picture misses the fewest requirements; the earlier one wins a tie, because
                        # corrections that did not reduce the misses tend to drift from the request (measured).
                        if best is None or len(candidate.unmet) < len(best.unmet):
                            best = candidate
                        feedback = outcome.feedback or "a requirement is not met"
                    if attempt >= max_attempts:
                        break
                    messages = [
                        request,
                        {"role": "assistant", "content": program or text[-4000:] or "(empty)"},
                        build_correction_message(feedback=feedback, computed_preview=preview),
                    ]
                if best:
                    # The round limit is reached: deliver the best valid picture and say what it still misses.
                    return result(best, model_id, REVIEW_UNMET_DELIVERED, attempt)
                failures.append(f"{model_id}: no valid picture after {attempt} attempts ({feedback[:300]})")
            except (RuntimeError, ConnectionError, TimeoutError, ValueError) as exc:
                if isinstance(exc, ModifyInputError):
                    raise
                # A provider failure moves on to the next configured author model.
                logger.warning("[%s] Modify author model %s failed: %s", task_id, model_id, exc)
                failures.append(f"{model_id}: {exc}")
    raise ModifyAuthorError("; ".join(failures) or "no modify author model configured")
