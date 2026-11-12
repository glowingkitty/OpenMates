"""Author loop of composed videos (videos-generate.composed.author-writes-composition,
videos-generate.composed.sandbox-render-and-correction).

An author model that can see pictures writes one Remotion composition
(prompt in ``prompt.py``, contract in ``contract.py``); it is checked and
rendered in the offline Remotion sandbox (``rounds.py``), so the model never
returns the video itself. A composition that breaks the contract, does not
build, declares an invalid timeline or fails while rendering is sent back
with its error for at most two corrections. One request makes at most three
author calls and three sandbox renders in total, across all models. Models
are tried in a fixed order; a provider failure or an answer without a
composition moves on to the next model and uses one call of the same budget. The sandbox starts in the background while
the first composition is written and is always killed at the end.

Every author call is recorded in ``ComposedVideo.usage`` and every sandbox
round in ``sandbox_seconds`` so the task can bill exactly what was used. A
request without a video raises ``ComposeFailure`` and nothing is charged.
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Sequence

from backend.apps.images.vector_author import VECTOR_AUTHOR_MODELS
from backend.apps.videos.composed.contract import extract_source, frame_size
from backend.apps.videos.composed.models import (
    INPUT_KINDS,
    MAX_SOURCES,
    SOURCE_KINDS,
    AuthorUsage,
    ComposedInputError,
    ComposedRequest,
    ComposedVideo,
    ComposeFailure,
)
from backend.apps.videos.composed.prompt import (
    SYSTEM_PROMPT,
    build_author_message,
    build_correction_message,
    preview_jpeg,
)
from backend.apps.videos.composed.rounds import RoundFailed, SandboxRunner, SessionFactory, default_session_factory
from backend.shared.providers.e2b_remotion_renderer import MAX_INPUT_BYTES, MAX_INPUTS, SOURCE_FILENAME
from backend.shared.python_utils.llm_stream_usage import stream_usage_tokens

logger = logging.getLogger(__name__)

# Ordered: the first model that produces a valid video answers. Same image-capable author models as
# images.modify (backend/apps/images/modify_author.py MODIFY_AUTHOR_MODELS).
COMPOSE_AUTHOR_MODELS: tuple[str, ...] = VECTOR_AUTHOR_MODELS
COMPOSE_AUTHOR_REASONING = "MEDIUM"
COMPOSE_AUTHOR_TEMPERATURE = 0.3
COMPOSE_AUTHOR_MAX_OUTPUT_TOKENS = 32_000
MAX_CORRECTION_ROUNDS = 2
MAX_INSTRUCTION_CHARS = 4000

STAGE_WRITING = "writing"
STAGE_RENDERING = "rendering"
STAGE_CORRECTING = "correcting"

StageCallback = Callable[[str], Awaitable[None]]
StreamFunction = Callable[..., AsyncIterator[Any]]


def _validate_request(request: ComposedRequest) -> str:
    instructions = " ".join((request.instructions or "").split())
    if not instructions:
        raise ComposedInputError("the instructions are empty")
    if len(instructions) > MAX_INSTRUCTION_CHARS:
        raise ComposedInputError(f"the instructions are longer than {MAX_INSTRUCTION_CHARS} characters")
    frame_size(request.aspect_ratio)
    if request.duration_seconds is not None and not 2 <= request.duration_seconds <= 60:
        raise ComposedInputError("a composed video lasts between 2 and 60 seconds")
    if len(request.inputs) > MAX_INPUTS:
        raise ComposedInputError(f"at most {MAX_INPUTS} pictures can be used")
    if len(request.sources) > MAX_SOURCES:
        raise ComposedInputError(f"at most {MAX_SOURCES} search results without a picture can be used")
    for source in request.sources:
        if source.kind not in SOURCE_KINDS or not (source.title.strip() or source.text.strip()):
            raise ComposedInputError("every source text needs a title or text of a search result")
    names = [item.name for item in request.inputs]
    if len(set(names)) != len(names):
        raise ComposedInputError("every input needs its own file name")
    for item in request.inputs:
        if item.kind not in INPUT_KINDS:
            raise ComposedInputError(f"unknown input kind {item.kind!r}")
        if not item.content or len(item.content) > MAX_INPUT_BYTES:
            raise ComposedInputError(f"the input {item.name!r} is empty or larger than {MAX_INPUT_BYTES // 1048576} MB")
        if item.width < 1 or item.height < 1:
            raise ComposedInputError(f"the input {item.name!r} has no pixel size")
    return instructions


def _previews(request: ComposedRequest) -> list[Optional[bytes]]:
    previews: list[Optional[bytes]] = []
    for item in request.inputs:
        if item.kind == "video_clip":
            previews.append(None)
            continue
        try:
            previews.append(preview_jpeg(item))
        except ValueError as exc:
            raise ComposedInputError(str(exc)) from exc
    return previews


async def _stream(*, stream_fn: StreamFunction, task_id: str, model_id: str, messages: list[dict[str, Any]],
                  secrets_manager: Any) -> tuple[str, int, int]:
    """Run one author call; return its text and reported token usage."""
    text = ""
    input_tokens = output_tokens = 0
    async for chunk in stream_fn(
        task_id=task_id, model_id=model_id, system_prompt=SYSTEM_PROMPT, message_history=messages,
        temperature=COMPOSE_AUTHOR_TEMPERATURE, secrets_manager=secrets_manager,
        max_tokens=COMPOSE_AUTHOR_MAX_OUTPUT_TOKENS, requested_reasoning_level=COMPOSE_AUTHOR_REASONING,
        private_logging=True,
    ):
        if isinstance(chunk, str):
            text += chunk
        elif (tokens := stream_usage_tokens(chunk)) is not None:
            input_tokens += tokens[0]
            output_tokens += tokens[1]
    return text, input_tokens, output_tokens


async def compose_video(
    request: ComposedRequest, *, secrets_manager: Any, task_id: str, on_stage: Optional[StageCallback] = None,
    stream_fn: Optional[StreamFunction] = None, session_factory: Optional[SessionFactory] = None,
    models: Sequence[str] = COMPOSE_AUTHOR_MODELS, max_attempts: int = MAX_CORRECTION_ROUNDS + 1,
) -> ComposedVideo:
    """Write a composition, render it in the sandbox and correct it from build or render errors."""
    instructions = _validate_request(request)
    previews = _previews(request)
    if stream_fn is None:
        from backend.apps.ai.utils.llm_utils import call_main_llm_stream
        stream_fn = call_main_llm_stream
    first = build_author_message(instructions=instructions, aspect_ratio=request.aspect_ratio,
                                 duration_seconds=request.duration_seconds, inputs=request.inputs,
                                 previews=previews, previous_source=request.previous_source,
                                 sources=request.sources)
    usage: list[AuthorUsage] = []
    failures: list[str] = []
    provider_failures = 0
    last_stage = ""
    error = ""

    async def stage(name: str) -> None:
        if on_stage:
            await on_stage(name)

    runner = SandboxRunner(session_factory or default_session_factory(secrets_manager), request.inputs)
    try:
        calls = 0  # one budget for the whole request: first try plus corrections, across every model
        for model_id in models:
            messages: list[dict[str, Any]] = [first]
            while calls < max_attempts:
                calls += 1
                step = STAGE_WRITING if len(messages) == 1 else STAGE_CORRECTING
                await stage(step)
                started = time.monotonic()
                try:
                    text, input_tokens, output_tokens = await _stream(
                        stream_fn=stream_fn, task_id=task_id, model_id=model_id, messages=messages,
                        secrets_manager=secrets_manager,
                    )
                except (RuntimeError, ConnectionError, TimeoutError, ValueError) as exc:
                    logger.warning("[%s] Composed-video author %s failed: %s", task_id, model_id, exc)
                    failures.append(f"{model_id}: {exc}")
                    provider_failures += 1
                    break
                usage.append(AuthorUsage(model=model_id, provider=model_id.split("/", 1)[0],
                                         input_tokens=input_tokens, output_tokens=output_tokens, step=step))
                logger.info("[%s] Composed-video author %s call %s wrote %s chars in %.1fs", task_id, model_id,
                            calls, len(text), time.monotonic() - started)
                source = extract_source(text)
                if not source:
                    last_stage = "static"
                    failures.append(f"{model_id}: the answer was not one TSX module with `export default`")
                    break
                try:
                    await stage(STAGE_RENDERING)
                    result = await runner.run(source, aspect_ratio=request.aspect_ratio,
                                              duration_seconds=request.duration_seconds)
                except RoundFailed as exc:
                    last_stage, error = exc.stage, exc.error
                    logger.info("[%s] Composed-video round %s failed at %s: %s", task_id, calls, exc.stage,
                                exc.error[-300:])
                else:
                    timeline = result.timeline
                    return ComposedVideo(
                        mp4=result.render.mp4, thumbnail_png=result.render.thumbnail_png, source=source,
                        filename=SOURCE_FILENAME, timeline=timeline, fps=timeline["fps"], width=timeline["width"],
                        height=timeline["height"], duration_in_frames=timeline["duration_in_frames"],
                        attempts=calls, author_model=model_id, usage=tuple(usage),
                        sandbox_seconds=tuple(runner.sandbox_seconds),
                    )
                if calls >= max_attempts:
                    failures.append(f"{model_id}: no valid composition after {calls} attempts "
                                    f"({last_stage}: {error[-300:]})")
                    break
                messages = [first, {"role": "assistant", "content": source},
                            build_correction_message(stage=last_stage, error=error)]
            if calls >= max_attempts:
                break
    finally:
        await runner.close()
    if not models:
        raise ComposeFailure("author_unavailable", "no composed-video author model is configured")
    if provider_failures == len(models):
        raise ComposeFailure("author_unavailable", "; ".join(failures))
    code = "render_failed" if last_stage == "render" else "no_valid_composition"
    raise ComposeFailure(code, "; ".join(failures))
