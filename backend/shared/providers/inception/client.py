"""Pure asynchronous Inception transport; never log response bodies or credentials."""
import asyncio
import json
import math
import os
from typing import Any, AsyncIterator, Literal

import httpx
from pydantic import BaseModel, Field, field_validator

BASE_URL = "https://api.inceptionlabs.ai/v1"
MAX_RETRY_DELAY_SECONDS = 10.0


def retry_delay(response: httpx.Response, attempt: int) -> float:
    """Honor numeric Retry-After without permitting unbounded server-directed waits."""
    backoff = min(MAX_RETRY_DELAY_SECONDS, 0.5 * 2 ** attempt)
    try:
        advertised = float(response.headers.get("retry-after", ""))
    except ValueError:
        return backoff
    if not math.isfinite(advertised) or advertised < 0:
        return backoff
    return min(MAX_RETRY_DELAY_SECONDS, max(backoff, advertised))


class InceptionError(RuntimeError):
    """Sanitized upstream failure, safe for application telemetry."""

    def __init__(self, message: str, *, status_code: int | None = None, kind: str = "provider"):
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind

    @property
    def is_availability_failure(self) -> bool:
        """Only transport faults and retryable HTTP failures warrant outage recovery."""
        return self.kind in {"timeout", "transport"} or (
            self.kind == "http" and self.status_code is not None
            and (self.status_code == 429 or 500 <= self.status_code < 600)
        )


class InceptionRequest(BaseModel):
    model: str = "mercury-3"
    messages: list[dict[str, Any]]
    temperature: float = 0.7
    max_completion_tokens: int | None = Field(default=None, ge=1, le=131072)
    reasoning_effort: Literal["instant", "low", "medium", "high"] = "low"
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    response_format: dict[str, Any] | None = None

    @field_validator("temperature")
    @classmethod
    def clamp_temperature(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Temperature must be finite")
        return max(0.5, min(1.0, value))

    @field_validator("messages")
    @classmethod
    def text_only(cls, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for message in messages:
            content = message.get("content")
            if content is not None and not isinstance(content, str):
                raise ValueError("Inception supports text content only")
        return messages


class InceptionUsage(BaseModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    prompt_tokens_details: dict[str, Any] | None = None
    completion_tokens_details: dict[str, Any] | None = None


class InceptionResult(BaseModel):
    id: str | None = None
    choices: list[dict[str, Any]]
    usage: InceptionUsage | None = None

    @field_validator("choices")
    @classmethod
    def valid_choices(cls, choices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for choice in choices:
            for field in ("message", "delta"):
                message = choice.get(field)
                if message is None:
                    continue
                if not isinstance(message, dict):
                    raise ValueError("Invalid completion message")
                if message.get("content") is not None and not isinstance(message["content"], str):
                    raise ValueError("Invalid text content")
                calls = message.get("tool_calls")
                if calls is not None:
                    if not isinstance(calls, list):
                        raise ValueError("Invalid tool calls")
                    for call in calls:
                        if not isinstance(call, dict):
                            raise ValueError("Invalid tool call")
                        function = call.get("function") or {}
                        if not isinstance(function, dict):
                            raise ValueError("Invalid tool function")
                        for key in ("name", "arguments"):
                            if function.get(key) is not None and not isinstance(function[key], str):
                                raise ValueError("Invalid tool function field")
        return choices


async def resolve_api_key(secrets_manager: Any = None) -> str:
    """Prefer Vault; local environments may contain the IMPORTED_TO_VAULT sentinel."""
    if secrets_manager is not None:
        try:
            value = await secrets_manager.get_secret(
                secret_path="kv/data/providers/inception_labs", secret_key="api_key"
            )
            if value and value != "IMPORTED_TO_VAULT":
                return value
        except Exception:
            pass
    value = os.getenv("SECRET__INCEPTION_LABS__API_KEY", "")
    if value and value != "IMPORTED_TO_VAULT":
        return value
    raise InceptionError("Inception API credential is not configured")


class InceptionClient:
    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 180.0, max_retries: int = 2):
        self._api_key = api_key
        self._transport = transport
        self._timeout = timeout
        self._max_retries = max(0, min(2, max_retries))

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=BASE_URL + "/", transport=self._transport,
            headers={"Authorization": "Bearer " + self._api_key}, timeout=self._timeout,
        )

    @staticmethod
    def _check(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise InceptionError(f"Inception API HTTP {response.status_code}",
                                 status_code=response.status_code, kind="http")

    async def complete(self, request: InceptionRequest) -> InceptionResult:
        async with self._client() as client:
            for attempt in range(self._max_retries + 1):
                try:
                    response = await client.post("chat/completions", json=request.model_dump(exclude_none=True))
                    if response.status_code == 429 and attempt < self._max_retries:
                        await asyncio.sleep(retry_delay(response, attempt))
                        continue
                    self._check(response)
                    return InceptionResult.model_validate(response.json())
                except InceptionError:
                    raise
                except httpx.TimeoutException:
                    raise InceptionError("Inception API request timed out", kind="timeout") from None
                except httpx.HTTPError:
                    raise InceptionError("Inception API transport failure", kind="transport") from None
                except (ValueError, TypeError):
                    raise InceptionError("Inception API returned an invalid completion", kind="invalid_response") from None
        raise InceptionError("Inception API retry limit reached")

    async def stream(self, request: InceptionRequest) -> AsyncIterator[InceptionResult]:
        payload = {**request.model_dump(exclude_none=True), "stream": True, "stream_options": {"include_usage": True}}
        async with self._client() as client:
            for attempt in range(self._max_retries + 1):
                try:
                    async with client.stream("POST", "chat/completions", json=payload) as response:
                        if response.status_code == 429 and attempt < self._max_retries:
                            await response.aclose()
                            await asyncio.sleep(retry_delay(response, attempt))
                            continue
                        self._check(response)
                        async for line in response.aiter_lines():
                            if not line or line.startswith(":"):
                                continue
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                return
                            try:
                                yield InceptionResult.model_validate(json.loads(data))
                            except (ValueError, TypeError):
                                raise InceptionError("Inception API returned an invalid stream event", kind="invalid_response") from None
                        raise InceptionError("Inception API stream ended before completion", kind="transport")
                except InceptionError:
                    raise
                except httpx.TimeoutException:
                    raise InceptionError("Inception API request timed out", kind="timeout") from None
                except httpx.HTTPError:
                    raise InceptionError("Inception API transport failure", kind="transport") from None
        raise InceptionError("Inception API retry limit reached")

    async def models(self) -> list[dict[str, Any]]:
        """Nonbilling connectivity probe."""
        async with self._client() as client:
            try:
                response = await client.get("models")
                self._check(response)
                data = response.json()["data"]
                if not isinstance(data, list):
                    raise ValueError()
                return data
            except InceptionError:
                raise
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise InceptionError("Inception API returned an invalid model list") from None
