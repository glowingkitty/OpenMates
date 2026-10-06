"""TypeSafe Jev decisions with direct inference and an OpenRouter outage fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Literal, Mapping, Optional

import httpx
from pydantic import ValidationError

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.providers.typesafe.budget import MAX_ESTIMATED_INPUT_TOKENS, estimate_request_tokens


logger = logging.getLogger(__name__)

DEFAULT_JEV_MODEL = "typesafe/jev-1.13"
TYPESAFE_MODEL = "jev-1.13.0"
TYPESAFE_DECISIONS_URL = "https://api.typesafe.ai/v1/systemone"
TYPESAFE_SECRET_PATH = "kv/data/providers/typesafe"
TYPESAFE_SECRET_KEY = "api_key"
TYPESAFE_ENV_KEY = "SECRET__TYPESAFE__API_KEY"
OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
OPENROUTER_SECRET_PATH = "kv/data/providers/openrouter"
OPENROUTER_SECRET_KEY = "api_key"
OPENROUTER_ENV_KEY = "SECRET__OPENROUTER__API_KEY"
PROVIDER_SETTINGS = {
    "typesafe": (TYPESAFE_DECISIONS_URL, TYPESAFE_SECRET_PATH, TYPESAFE_SECRET_KEY, TYPESAFE_ENV_KEY),
    "openrouter": (OPENROUTER_DECISIONS_URL, OPENROUTER_SECRET_PATH, OPENROUTER_SECRET_KEY, OPENROUTER_ENV_KEY),
}
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
    """Evaluate through TypeSafe first; fall back only on provider unavailability."""

    def __init__(
        self,
        *,
        secrets_manager: Optional[SecretsManager],
        model: str = DEFAULT_JEV_MODEL,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout_seconds: float = 3.0,
        max_retries: int = 1,
        endpoint: Optional[str] = None,
        provider: Optional[Literal["typesafe", "openrouter"]] = None,
    ) -> None:
        self._secrets_manager = secrets_manager
        self._model = model
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        if provider is not None and provider not in PROVIDER_SETTINGS:
            raise ValueError("Unsupported Jev provider")
        if endpoint is not None or provider is not None:
            selected = provider or ("openrouter" if endpoint == OPENROUTER_DECISIONS_URL else "typesafe")
            self._providers = (selected,)
        else:
            self._providers = ("typesafe", "openrouter")
        self._endpoint = endpoint

    async def _api_key(self, provider: str) -> str:
        _, secret_path, secret_key, environment_key = PROVIDER_SETTINGS[provider]
        value: Optional[str] = None
        if self._secrets_manager is not None:
            try:
                value = await self._secrets_manager.get_secret(
                    secret_path=secret_path,
                    secret_key=secret_key,
                )
            except Exception:
                logger.warning("Jev %s credentials unavailable from Vault; checking environment fallback", provider)
        cleaned = value.strip().strip('"').strip() if value else ""
        cleaned = cleaned or (os.getenv(environment_key) or "").strip().strip('"').strip()
        if not cleaned:
            raise DecisionProviderUnavailable(f"Jev {provider} API key is not configured")
        return cleaned

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
        owns_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(timeout=self._timeout_seconds)
        try:
            last_error: Optional[DecisionProviderUnavailable] = None
            for provider in self._providers:
                try:
                    result = await self._evaluate_provider(client, provider, state, questions)
                except DecisionProviderUnavailable as exc:
                    last_error = exc
                    logger.warning("Jev %s unavailable", provider)
                    continue
                logger.info("Jev decision completed: provider=%s estimated_input_tokens=%d input_tokens=%d questions=%d",
                            provider, estimated_tokens, result.usage.input_tokens, len(questions))
                return result
            raise last_error or DecisionProviderUnavailable("No Jev provider is configured")
        finally:
            if owns_client:
                await client.aclose()

    async def _evaluate_provider(
        self, client: httpx.AsyncClient, provider: str, state: Any,
        questions: Mapping[str, Mapping[str, Any]],
    ) -> DecisionResponse:
        api_key = await self._api_key(provider)
        model = self._model
        if provider == "typesafe" and model == DEFAULT_JEV_MODEL:
            model = TYPESAFE_MODEL
        elif provider == "openrouter" and model == TYPESAFE_MODEL:
            model = DEFAULT_JEV_MODEL
        payload = {"model": model, "state": state, "questions": dict(questions)}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if provider == "openrouter":
            headers.update({"HTTP-Referer": "https://openmates.org", "X-Title": "OpenMates decision processing"})
        endpoint = self._endpoint or PROVIDER_SETTINGS[provider][0]
        for attempt in range(self._max_retries + 1):
            try:
                response = await client.post(endpoint, headers=headers, json=payload, timeout=self._timeout_seconds)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self._max_retries:
                    raise DecisionProviderUnavailable(f"Jev {provider} transport unavailable") from exc
                await asyncio.sleep(0.05 * (2**attempt))
                continue

            if response.status_code >= 400 and _is_context_overflow(response):
                raise DecisionRequestTooLarge("Jev provider rejected the input context size")
            if response.status_code in {401, 403}:
                raise DecisionProviderUnavailable(f"Jev {provider} credentials rejected")
            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt >= self._max_retries:
                    raise DecisionProviderUnavailable(
                        f"Jev {provider} unavailable with status {response.status_code}")
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = min(max(float(retry_after or 0.05 * (2**attempt)), 0.01), 0.5)
                except ValueError:
                    delay = min(0.05 * (2**attempt), 0.5)
                await asyncio.sleep(delay)
                continue
            if response.status_code >= 400:
                raise DecisionProviderError(f"Jev request rejected with status {response.status_code}")
            try:
                parsed = DecisionResponse.model_validate(response.json())
            except (ValueError, ValidationError) as exc:
                raise DecisionResponseInvalid("Jev returned an invalid decision response") from exc
            if set(questions) - set(parsed.answers):
                raise DecisionResponseInvalid("Jev response omitted requested answers")
            parsed.provider = provider
            return parsed
        raise DecisionProviderUnavailable("Jev request did not complete")

    async def health_check(self) -> bool:
        """Check credentials without incurring an inference charge."""
        for provider in self._providers:
            try:
                await self._api_key(provider)
                return True
            except DecisionProviderUnavailable:
                continue
        return False


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
