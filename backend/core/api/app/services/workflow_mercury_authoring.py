"""Direct Mercury authoring using the shared deterministic Workflow parser."""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

from backend.core.api.app.services.workflow_gemini_authoring import (
    WorkflowAuthoringProviderError, WorkflowAuthoringStopped, WorkflowGeminiAuthor,
)
from backend.core.api.app.utils.config_manager import ConfigManager
from backend.shared.providers.inception import InceptionClient, InceptionError, InceptionRequest, resolve_api_key

MERCURY_MODEL = "inception/mercury-3"
FIRST_OUTPUT_TIMEOUT_SECONDS = 5.0
IDLE_TIMEOUT_SECONDS = 5.0
TOTAL_TIMEOUT_SECONDS = 15.0


class WorkflowMercuryAuthor(WorkflowGeminiAuthor):
    """Change only the provider envelope; headers/nodes use the existing validator."""

    def __init__(self, secrets_manager: Any, client: Any = None, *, native_client_factory=InceptionClient,
                 config_manager: Any = None, first_output_timeout: float = FIRST_OUTPUT_TIMEOUT_SECONDS,
                 idle_timeout: float = IDLE_TIMEOUT_SECONDS, total_timeout: float = TOTAL_TIMEOUT_SECONDS,
                 reasoning_effort: str = "instant") -> None:
        if reasoning_effort not in {"instant", "low"}:
            raise ValueError("Workflow Mercury profile must be instant or low")
        self.secrets_manager, self.client = secrets_manager, client
        self.model, self.model_id = "mercury-3", MERCURY_MODEL
        self.reasoning_effort = reasoning_effort
        self.native_client_factory = native_client_factory
        self.first_output_timeout, self.idle_timeout, self.total_timeout = first_output_timeout, idle_timeout, total_timeout
        self.prices = None
        details = (config_manager or ConfigManager()).get_model_pricing(
            "inception", "mercury-3", inference_host="inception")
        if isinstance(details, dict):
            costs = details.get("costs") or {}
            input_price = (costs.get("input_per_million_token") or {}).get("price")
            output_price = (costs.get("output_per_million_token") or {}).get("price")
            if all(isinstance(value, (int, float)) for value in (input_price, output_price)):
                self.prices = (input_price, output_price)

    async def generate(self, **kwargs):
        self._call_started = time.monotonic()
        self._should_stop = kwargs.get("should_stop")
        interrupted_metrics = {}
        deadline = asyncio.timeout(self.total_timeout)
        try:
            async with deadline:
                try:
                    return await super().generate(**kwargs)
                except asyncio.CancelledError as exc:
                    interrupted_metrics = getattr(exc, "metrics", {})
                    raise
        except TimeoutError as exc:
            if not deadline.expired():
                raise
            raise WorkflowAuthoringProviderError(
                "Workflow provider transport failed", interrupted_metrics,
                code="provider_timeout", is_availability_failure=True) from exc

    async def _provider_key(self):
        lookup = asyncio.create_task(resolve_api_key(self.secrets_manager))
        try:
            while not lookup.done():
                if callable(self._should_stop):
                    stopped = self._should_stop()
                    if inspect.isawaitable(stopped):
                        stopped = await stopped
                    if stopped:
                        raise WorkflowAuthoringStopped("Workflow authoring was stopped")
                remaining = self.first_output_timeout - (time.monotonic() - self._call_started)
                if remaining <= 0:
                    raise TimeoutError()
                await asyncio.wait({lookup}, timeout=min(0.25, remaining))
            return lookup.result()
        except TimeoutError as exc:
            raise WorkflowAuthoringProviderError(
                "Workflow provider transport failed", code="provider_timeout",
                is_availability_failure=True) from exc
        except InceptionError as exc:
            raise self._provider_error(exc) from exc
        finally:
            if not lookup.done():
                lookup.cancel()
            await asyncio.gather(lookup, return_exceptions=True)

    @staticmethod
    def _provider_error(exc: InceptionError) -> WorkflowAuthoringProviderError:
        error = WorkflowAuthoringProviderError(
            "Workflow provider transport failed", code="provider_" + str(getattr(exc, "kind", "provider")),
            is_availability_failure=bool(getattr(exc, "is_availability_failure", False)))
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            error.http_status = status
        return error

    async def _events(self, body, key, client, check_stop, has_useful_output):
        config = body["generationConfig"]
        request = InceptionRequest(
            model=self.model, reasoning_effort=self.reasoning_effort, temperature=0.5,
            max_completion_tokens=config["maxOutputTokens"],
            messages=[{"role": "system", "content": body["systemInstruction"]["parts"][0]["text"]},
                      {"role": "user", "content": body["contents"][0]["parts"][0]["text"]}],
            response_format={"type": "json_schema", "json_schema": {
                "name": "workflow_authoring", "strict": True, "schema": config["responseJsonSchema"]}},
        )
        stream = self.native_client_factory(key, timeout=self.idle_timeout, max_retries=0).stream(request)
        iterator = aiter(stream)
        try:
            while True:
                pending = asyncio.create_task(anext(iterator))
                deadline = time.monotonic() + self.idle_timeout
                if not has_useful_output():
                    deadline = min(deadline, self._call_started + self.first_output_timeout)
                try:
                    while not pending.done():
                        await check_stop()
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise WorkflowAuthoringProviderError(
                                "Workflow provider transport failed", code="provider_timeout",
                                is_availability_failure=True)
                        await asyncio.wait({pending}, timeout=min(0.25, remaining))
                    event = pending.result()
                except StopAsyncIteration:
                    return
                finally:
                    if not pending.done():
                        pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                mapped = {}
                if event.usage is not None:
                    usage = event.usage
                    reasoning = int((usage.completion_tokens_details or {}).get("reasoning_tokens") or 0)
                    mapped["usageMetadata"] = {"promptTokenCount": usage.prompt_tokens,
                        "candidatesTokenCount": max(0, usage.completion_tokens - reasoning),
                        "thoughtsTokenCount": reasoning}
                    cached = (usage.prompt_tokens_details or {}).get("cached_tokens")
                    if cached is not None:
                        mapped["usageMetadata"]["cachedContentTokenCount"] = cached
                candidates = []
                for choice in event.choices:
                    content = (choice.get("delta") or {}).get("content")
                    candidate = {"content": {"parts": [{"text": content}]} if content else {"parts": []}}
                    if choice.get("finish_reason"):
                        candidate["finishReason"] = "STOP" if choice["finish_reason"] == "stop" else "MAX_TOKENS"
                    candidates.append(candidate)
                if candidates:
                    mapped["candidates"] = candidates
                yield mapped
        except InceptionError as exc:
            raise self._provider_error(exc) from exc
        finally:
            await stream.aclose()
