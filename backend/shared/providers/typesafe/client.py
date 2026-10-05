"""TypeSafe Jev decision client using OpenRouter's decisions endpoint.

The transport boundary is deliberately isolated here. A direct TypeSafe transport can
be added later without changing preprocessing or safety callers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Mapping, Optional

import httpx
from pydantic import ValidationError

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.providers.typesafe.budget import MAX_ESTIMATED_INPUT_TOKENS, estimate_request_tokens


logger = logging.getLogger(__name__)

DEFAULT_JEV_MODEL = "typesafe/jev-1.13"
OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
OPENROUTER_SECRET_PATH = "kv/data/providers/openrouter"
OPENROUTER_SECRET_KEY = "api_key"
OPENROUTER_ENV_KEY = "SECRET__OPENROUTER__API_KEY"
MAX_SERIALIZED_STATE_CHARS = 80_000
MAX_SERIALIZED_REQUEST_CHARS = 120_000
MAX_QUESTIONS = 160
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504, 529}


class DecisionProviderError(RuntimeError):
    """Base error for a typed decision request."""


class DecisionProviderUnavailable(DecisionProviderError):
    """The provider or credentials were unavailable after bounded retries."""


class DecisionRequestTooLarge(DecisionProviderError):
    """The bounded state exceeds the conservative Jev input budget."""


class DecisionResponseInvalid(DecisionProviderError):
    """The provider response did not match the requested decision contract."""


class JevDecisionClient:
    """Evaluate named Choice, Noul, and Score questions through OpenRouter."""

    def __init__(
        self,
        *,
        secrets_manager: Optional[SecretsManager],
        model: str = DEFAULT_JEV_MODEL,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout_seconds: float = 3.0,
        max_retries: int = 1,
        endpoint: str = OPENROUTER_DECISIONS_URL,
    ) -> None:
        self._secrets_manager = secrets_manager
        self._model = model
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._endpoint = endpoint

    async def _api_key(self) -> str:
        value: Optional[str] = None
        if self._secrets_manager is not None:
            try:
                value = await self._secrets_manager.get_secret(
                    secret_path=OPENROUTER_SECRET_PATH,
                    secret_key=OPENROUTER_SECRET_KEY,
                )
            except Exception:
                logger.warning("Jev credentials unavailable from Vault; checking environment fallback")
        value = value or os.getenv(OPENROUTER_ENV_KEY)
        if not value or not value.strip():
            raise DecisionProviderUnavailable("OpenRouter API key is not configured")
        return value.strip().strip('"')

    @staticmethod
    def _validate_request(state: Any, questions: Mapping[str, Mapping[str, Any]]) -> int:
        if not questions:
            raise DecisionProviderError("at least one decision question is required")
        if len(questions) > MAX_QUESTIONS:
            raise DecisionRequestTooLarge(f"decision request exceeds {MAX_QUESTIONS} questions")
        try:
            serialized_state = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise DecisionProviderError("decision state is not JSON serializable") from exc
        if len(serialized_state) > MAX_SERIALIZED_STATE_CHARS:
            raise DecisionRequestTooLarge(
                f"decision state exceeds {MAX_SERIALIZED_STATE_CHARS} serialized characters"
            )
        for question_id, question in questions.items():
            if not question_id or not isinstance(question, Mapping):
                raise DecisionProviderError("decision question ids and definitions must be mappings")
            question_type = question.get("type")
            if question_type not in {"choice", "noul", "score"}:
                raise DecisionProviderError(f"unsupported question type for {question_id}")
            if "instructions" not in question:
                raise DecisionProviderError(f"missing instructions for {question_id}")
        try:
            request_size = len(
                json.dumps(
                    {"state": state, "questions": questions},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        except (TypeError, ValueError) as exc:
            raise DecisionProviderError("decision questions are not JSON serializable") from exc
        if request_size > MAX_SERIALIZED_REQUEST_CHARS:
            raise DecisionRequestTooLarge(
                f"decision request exceeds {MAX_SERIALIZED_REQUEST_CHARS} serialized characters"
            )
        try:
            estimated_tokens = estimate_request_tokens(state, questions)
        except ImportError as exc:
            raise DecisionProviderUnavailable("Jev input tokenizer is unavailable") from exc
        if estimated_tokens > MAX_ESTIMATED_INPUT_TOKENS:
            raise DecisionRequestTooLarge(
                f"decision request exceeds {MAX_ESTIMATED_INPUT_TOKENS} estimated input tokens"
            )
        return estimated_tokens

    async def evaluate(
        self,
        *,
        state: Any,
        questions: Mapping[str, Mapping[str, Any]],
    ) -> DecisionResponse:
        estimated_tokens = self._validate_request(state, questions)
        api_key = await self._api_key()
        payload = {"model": self._model, "state": state, "questions": dict(questions)}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://openmates.org",
            "X-Title": "OpenMates decision processing",
        }

        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(timeout=self._timeout_seconds)
        try:
            for attempt in range(self._max_retries + 1):
                try:
                    response = await client.post(self._endpoint, headers=headers, json=payload)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt >= self._max_retries:
                        raise DecisionProviderUnavailable("Jev transport unavailable") from exc
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue

                if response.status_code >= 400 and _is_context_overflow(response):
                    raise DecisionRequestTooLarge("Jev provider rejected the input context size")

                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt >= self._max_retries:
                        raise DecisionProviderUnavailable(
                            f"Jev provider unavailable with status {response.status_code}"
                        )
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = min(max(float(retry_after or 0.05), 0.01), 0.5)
                    except ValueError:
                        delay = 0.05
                    await asyncio.sleep(delay)
                    continue

                if response.status_code >= 400:
                    raise DecisionProviderError(f"Jev request rejected with status {response.status_code}")

                try:
                    parsed = DecisionResponse.model_validate(response.json())
                except (ValueError, ValidationError) as exc:
                    raise DecisionResponseInvalid("Jev returned an invalid decision response") from exc

                missing = set(questions) - set(parsed.answers)
                if missing:
                    raise DecisionResponseInvalid("Jev response omitted requested answers")
                logger.info("Jev decision completed: estimated_input_tokens=%d input_tokens=%d questions=%d",
                            estimated_tokens, parsed.usage.input_tokens, len(questions))
                return parsed
        finally:
            if owns_client:
                await client.aclose()

        raise DecisionProviderUnavailable("Jev request did not complete")

    async def health_check(self) -> bool:
        """Check configuration only; do not incur an inference charge."""

        try:
            await self._api_key()
        except DecisionProviderError:
            return False
        return True


def _is_context_overflow(response: httpx.Response) -> bool:
    """Classify size errors without retaining or logging private provider text."""
    if response.status_code == 413:
        return True
    if response.status_code not in {400, 422, 500, 502, 503}:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict) or "error" not in body:
        return False
    error = json.dumps(body["error"], ensure_ascii=False)[:8_000].lower()
    return any(marker in error for marker in (
        "context_length_exceeded", "context_window_exceeded", "input_too_long",
        "request_too_large", "maximum context", "context length", "context window",
        "too many tokens", "input token limit", "token limit exceeded",
    ))
