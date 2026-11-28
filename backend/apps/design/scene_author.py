"""Dedicated model and bounded visual review loop for Design scenes."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from backend.apps.ai.utils.llm_utils import AllServersFailedError, call_main_llm_stream
from backend.apps.design.scene import MAX_SCENE_BYTES, DesignEdits, DesignScene, parse_draft
from backend.apps.design.scene_review import missing_copy, review_preview
from backend.apps.images.vector_author import (
    VECTOR_AUTHOR_MAX_OUTPUT_TOKENS,
    VECTOR_AUTHOR_MODELS,
    VECTOR_AUTHOR_REASONING,
    VECTOR_AUTHOR_TEMPERATURE,
    VectorUsage,
    normalize_requirements,
    review_with_jev,
)
from backend.shared.python_utils.internal_llm_policy import DEFAULT_POLICY, InternalLlmPolicy
from backend.shared.python_utils.llm_stream_usage import stream_usage_tokens

MAX_AUTHOR_ATTEMPTS = 2
AUTHOR_TIMEOUT_SECONDS = 120
REVIEW_CHECKS = (
    "All of the brief's required copy is visible and complete on the appropriate page.",
    "The text has enough room inside its boxes, with no clipped words or obscured lines.",
    "The page layout is readable and follows the brief.",
)
Progress = Callable[[str, int], Awaitable[None]]


@dataclass(frozen=True)
class DesignAuthorResult:
    scene: DesignScene | None
    model_id: str | None
    attempts: int
    usage: tuple[VectorUsage, ...]
    elapsed_ms: int
    error: str | None = None


def _system_prompt(source: DesignScene | None) -> str:
    output = DesignEdits if source is not None else DesignScene
    return (
        "You author editable visual designs. Return one JSON object matching the schema. "
        "No markup, external URLs, scripts or Markdown. Layer order is back to front. "
        "Use exact required copy in visible text layers. Choose text boxes with enough height "
        "for the complete line and its descenders, and enough space around dates and captions. "
        "Use only absolute path commands M L H V C Q Z, separated from operands by spaces. "
        + (
            "Edit the supplied base with targeted operations using its page and layer IDs. Retain unrelated content. "
            if source is not None
            else "Create the page count and artboard sizes the brief needs. Use shape and path layers for graphic elements. "
        )
        + "Schema: " + json.dumps(output.model_json_schema(), separators=(",", ":"))
    )


async def _draft(
    *, task_id: str, model_id: str, system_prompt: str, messages: list[dict[str, Any]],
    secrets_manager: Any, stream_options: dict[str, Any],
) -> tuple[str, VectorUsage]:
    chunks = []
    size = 0
    input_tokens = output_tokens = 0
    async for chunk in call_main_llm_stream(
        task_id=task_id, model_id=model_id, system_prompt=system_prompt, message_history=messages,
        temperature=VECTOR_AUTHOR_TEMPERATURE, secrets_manager=secrets_manager, max_tokens=VECTOR_AUTHOR_MAX_OUTPUT_TOKENS,
        requested_reasoning_level=VECTOR_AUTHOR_REASONING["default"], private_logging=True,
        **stream_options,
    ):
        if isinstance(chunk, str):
            size += len(chunk.encode())
            if size > MAX_SCENE_BYTES:
                raise ValueError("draft is too large")
            chunks.append(chunk)
        elif (tokens := stream_usage_tokens(chunk)) is not None:
            input_tokens += tokens[0]
            output_tokens += tokens[1]
    return "".join(chunks), VectorUsage("author", model_id, input_tokens, output_tokens)


async def author_design(
    *, task_id: str, brief: str, requirements: tuple[str, ...] = (), exact_copy: tuple[str, ...] = (),
    source: DesignScene | None = None, secrets_manager: Any = None,
    policy: InternalLlmPolicy | None = None, progress: Progress | None = None,
) -> DesignAuthorResult:
    """Return a visually accepted scene or a stable refusal within two author calls."""
    start = time.monotonic()
    policy = policy or DEFAULT_POLICY
    routes = tuple(policy.author_routes(VECTOR_AUTHOR_MODELS, required_inputs=("text",), task_id=task_id))
    checks = normalize_requirements((*REVIEW_CHECKS, *requirements))
    envelope = {"brief": brief, "requirements": checks, "exactCopy": exact_copy}
    if source is not None:
        envelope["source"] = source.model_dump(by_alias=True, exclude_none=True)
    request = {"role": "user", "content": json.dumps(envelope, ensure_ascii=False)}
    messages = [request]
    system_prompt = _system_prompt(source)
    usage: list[VectorUsage] = []
    index = 0
    model_id = None
    attempts = 0
    error = "design_author_unavailable"

    def result(scene: DesignScene | None = None) -> DesignAuthorResult:
        return DesignAuthorResult(scene, model_id, attempts, tuple(usage), round((time.monotonic() - start) * 1000),
                                  None if scene else error)

    try:
        async with asyncio.timeout(AUTHOR_TIMEOUT_SECONDS):
            while attempts < MAX_AUTHOR_ATTEMPTS and index < len(routes):
                route = routes[index]
                model_id = route.model_id
                attempts += 1
                if progress is not None:
                    await progress("authoring" if attempts == 1 else "repairing", attempts)
                answer = ""
                try:
                    answer, meter = await _draft(
                        task_id=task_id, model_id=model_id, system_prompt=system_prompt, messages=messages,
                        secrets_manager=secrets_manager, stream_options=policy.stream_options(route),
                    )
                except (AllServersFailedError, ConnectionError, TimeoutError):
                    index += 1
                    continue
                except ValueError:
                    feedback = "Return a complete scene within the allowed output size."
                    error = "design_scene_invalid"
                else:
                    usage.append(meter)
                    try:
                        scene = parse_draft(answer, source)
                    except ValueError:
                        feedback = "Return one valid JSON object matching the scene or edit schema."
                        error = "design_scene_invalid"
                    else:
                        absent_copy = missing_copy(scene, exact_copy)
                        svg, clipped = await asyncio.to_thread(review_preview, scene)
                        if absent_copy or clipped:
                            feedback = json.dumps({"missingCopy": absent_copy, "clippedLayers": clipped})
                            error = "design_review_rejected"
                        else:
                            if progress is not None:
                                await progress("reviewing", attempts)
                            review = await review_with_jev(
                                svg=svg, prompt=brief, requirements=checks, is_modification=source is not None,
                                secrets_manager=secrets_manager, task_id=task_id, policy=policy,
                            )
                            if review.input_tokens or review.output_tokens:
                                usage.append(VectorUsage("review", review.model_id, review.input_tokens, review.output_tokens))
                            if review.status == "accepted" and review.accepted:
                                return result(scene)
                            if review.status == "unavailable":
                                error = "design_review_unavailable"
                                return result()
                            feedback = review.feedback or "Make the complete required copy and layout readable."
                            error = "design_review_rejected"
                messages = [
                    request,
                    {"role": "assistant", "content": answer or "{}"},
                    {"role": "user", "content": f"Correct the draft. Validation feedback: {feedback} Return the complete JSON object."},
                ]
    except TimeoutError:
        error = "design_author_timeout"
    return result()
