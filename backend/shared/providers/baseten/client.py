"""Documented Baseten Model API transport; no application or skill dependencies."""

from __future__ import annotations

import asyncio
import json
import math
import os
from typing import Any, AsyncIterator, Literal

import httpx
from pydantic import BaseModel, Field

BASE_URL = "https://inference.baseten.co/v1"
SECRET_PATH = "kv/data/providers/baseten"
ENV_KEY = "SECRET__BASETEN__API_KEY"


class BasetenError(RuntimeError):
    """A sanitized failure that never includes provider response bodies."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class BasetenRequest(BaseModel):
    model: str = Field(min_length=1)
    messages: list[dict[str, Any]]
    temperature: float = Field(default=0.7, ge=0, le=4, allow_inf_nan=False)
    max_tokens: int | None = Field(default=None, ge=1)
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    reasoning_effort: Literal["none", "low", "medium", "high", "max"] | None = None
    response_format: dict[str, Any] | None = None


class BasetenResult(BaseModel):
    id: str | None = None
    choices: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, Any] | None = None


async def resolve_api_key(secrets_manager: Any = None) -> str:
    if secrets_manager is not None:
        try:
            key = await secrets_manager.get_secret(
                secret_path=SECRET_PATH, secret_key="api_key"
            )
            if key and key != "IMPORTED_TO_VAULT":
                return key
        except Exception:
            pass
    key = os.getenv(ENV_KEY, "")
    if key and key != "IMPORTED_TO_VAULT":
        return key
    raise BasetenError("Baseten API key is not configured")


class BasetenClient:
    def __init__(
        self,
        api_key: str,
        *,
        session_affinity: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 180,
        max_retries: int = 2,
    ):
        self._key, self._affinity, self._transport = (
            api_key,
            session_affinity,
            transport,
        )
        self._timeout, self._retries = timeout, max(0, min(2, max_retries))

    def _client(self) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self._key}"}
        if self._affinity:
            headers["x-session-affinity"] = self._affinity
        return httpx.AsyncClient(
            base_url=BASE_URL + "/",
            headers=headers,
            timeout=self._timeout,
            transport=self._transport,
        )

    @staticmethod
    def _check(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise BasetenError(
                f"Baseten API HTTP error {response.status_code}",
                status_code=response.status_code,
            )

    @staticmethod
    async def _backoff(response: httpx.Response, attempt: int) -> None:
        try:
            retry_after = float(response.headers.get("retry-after", "0"))
        except ValueError:
            retry_after = 0
        if not math.isfinite(retry_after):
            retry_after = 0
        await asyncio.sleep(min(10, max(0.5 * 2**attempt, retry_after)))

    async def models(self) -> list[dict[str, Any]]:
        """Non-billable credential/catalog check; never dispatch inference."""
        try:
            async with self._client() as client:
                response = await client.get("models")
                self._check(response)
                data = response.json().get("data")
                if not isinstance(data, list) or any(
                    not isinstance(row, dict) for row in data
                ):
                    raise ValueError()
                return data
        except (httpx.HTTPError, ValueError, TypeError):
            raise BasetenError("Baseten catalog request failed") from None

    async def complete(self, request: BasetenRequest) -> BasetenResult:
        try:
            async with self._client() as client:
                for attempt in range(self._retries + 1):
                    response = await client.post(
                        "chat/completions", json=request.model_dump(exclude_none=True)
                    )
                    if response.status_code == 429 and attempt < self._retries:
                        await self._backoff(response, attempt)
                        continue
                    self._check(response)
                    return BasetenResult.model_validate(response.json())
        except (httpx.HTTPError, ValueError, TypeError):
            raise BasetenError(
                "Baseten completion connection or response failed"
            ) from None
        raise BasetenError("Baseten request retry limit reached")

    async def stream(self, request: BasetenRequest) -> AsyncIterator[BasetenResult]:
        payload = {
            **request.model_dump(exclude_none=True),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        try:
            async with self._client() as client:
                for attempt in range(self._retries + 1):
                    async with client.stream(
                        "POST", "chat/completions", json=payload
                    ) as response:
                        if response.status_code == 429 and attempt < self._retries:
                            await response.aclose()
                            await self._backoff(response, attempt)
                            continue
                        self._check(response)
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                return
                            yield BasetenResult.model_validate(json.loads(data))
                        raise BasetenError("Baseten stream ended before completion")
        except (httpx.HTTPError, ValueError, TypeError):
            raise BasetenError("Baseten stream connection or response failed") from None
        raise BasetenError("Baseten request retry limit reached")
