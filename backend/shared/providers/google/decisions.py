"""Gemini Decisions API (gemini-decision-1) behind Jev's typed decision contract.

Google's Decisions API answers the same noul/choice/score questions as Jev
with calibrated probabilities and bills input tokens only. This wrapper turns a
Jev-shaped request (JSON ``state``, ``questions`` and optional image assets)
into the Decisions API body and returns Jev's ``DecisionResponse`` so callers do
not change. It never retries: the caller's Jev chain is the fallback.

Official docs (verified 2026-11-17):
  https://aistudio.google.com/docs/decisions-api  (POST v1beta/decisions, limits, errors)
  https://aistudio.google.com/docs/pricing         ($0.10 / 1M input tokens, paid tier not used for training)
  https://aistudio.google.com/docs/rate-limits     (Tier 1: 1,500 RPM, 1M TPM)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any, Mapping, Optional

import httpx
from pydantic import ValidationError

from backend.shared.providers.typesafe.models import DecisionResponse

logger = logging.getLogger(__name__)

GEMINI_DECISION_MODEL = "google/gemini-decision-1"
GEMINI_DECISION_PROVIDER_MODEL = "gemini-decision-1"
GEMINI_DECISION_SERVER = "google_ai_studio"
GEMINI_DECISIONS_URL = "https://generativelanguage.googleapis.com/v1beta/decisions"
GEMINI_SECRET_PATH = "kv/data/providers/google_ai_studio"
GEMINI_SECRET_KEY = "api_key"
GEMINI_ENV_KEY = "SECRET__GOOGLE_AI_STUDIO__API_KEY"
# Mirror backend/providers/google.yml (gemini-decision-1 costs).
GEMINI_DECISION_INPUT_USD_PER_MILLION = 0.10
MAX_CHOICE_OPTIONS = 255
MAX_OPTION_KEY_CHARS = 128
# Documented safety-block codes (HTTP 400): the input was refused, not judged.
BLOCK_CODES = frozenset({"safety", "prohibited_content", "blocklist", "image_safety", "content_blocked"})
_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


class GeminiDecisionError(RuntimeError):
    """Any failed Gemini decision; ``reason`` is a short machine label for logs and benchmarks."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(f"{reason}: {message}" if message else reason)
        self.reason = reason


class GeminiDecisionBlocked(GeminiDecisionError):
    """Google refused to evaluate the input (documented safety-block codes)."""


def unsupported_reason(questions: Mapping[str, Mapping[str, Any]]) -> Optional[str]:
    """A documented Decisions API limit this request breaks, so Jev should answer directly."""
    for question in questions.values():
        criteria = question.get("criteria")
        if question.get("type") == "choice" and isinstance(criteria, Mapping):
            if len(criteria) > MAX_CHOICE_OPTIONS:
                return "too_many_options"
            if any(len(str(key)) > MAX_OPTION_KEY_CHARS for key in criteria):
                return "option_key_too_long"
        if question.get("type") == "score" and isinstance(criteria, list) and len(criteria) > MAX_CHOICE_OPTIONS:
            return "too_many_levels"
    return None


def _question(question: Mapping[str, Any]) -> dict[str, Any]:
    instructions = question["instructions"]
    # Jev accepts structured instructions (e.g. {"question", "candidate_id", ...}); Gemini accepts text only.
    if not isinstance(instructions, str):
        instructions = json.dumps(instructions, ensure_ascii=False)
    body = {"type": question["type"], "instructions": instructions}
    criteria = question.get("criteria")
    if question["type"] == "noul":
        if isinstance(criteria, Mapping) and criteria:
            body["criteria"] = {"true_description": str(criteria.get("true") or "yes"),
                                "false_description": str(criteria.get("false") or "no")}
    elif criteria is not None:
        body["criteria"] = dict(criteria) if isinstance(criteria, Mapping) else list(criteria)
    return body


def request_body(state: Any, questions: Mapping[str, Mapping[str, Any]],
                 images: Optional[Mapping[str, tuple[bytes, str]]] = None) -> dict[str, Any]:
    """The Decisions API body: the JSON state as text, then each image after its reference."""
    blocks: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(state, ensure_ascii=False)}]
    for reference, (content, fmt) in (images or {}).items():
        blocks.append({"type": "text", "text": f"Image {reference}:"})
        blocks.append({"type": "image", "data": base64.b64encode(content).decode("ascii"),
                       "mime_type": _MIME.get(fmt, "image/jpeg")})
    return {"model": GEMINI_DECISION_PROVIDER_MODEL, "input": blocks,
            "questions": {key: _question(question) for key, question in questions.items()}}


def images_from_assets(assets: Optional[Mapping[str, Mapping[str, Any]]]) -> dict[str, tuple[bytes, str]]:
    return {reference: (base64.b64decode(asset["data_base64"]), str(asset.get("format") or "jpg"))
            for reference, asset in (assets or {}).items()}


class GeminiDecisionClient:
    """One Decisions API call per evaluation; errors raise ``GeminiDecisionError``."""

    def __init__(self, *, secrets_manager: Any, timeout_seconds: float = 2.5,
                 telemetry_task_id: Optional[str] = None, telemetry_purpose: Optional[str] = None) -> None:
        self._secrets_manager = secrets_manager
        self._timeout_seconds = timeout_seconds
        self._telemetry_task_id = telemetry_task_id
        self._telemetry_purpose = telemetry_purpose

    async def _api_key(self) -> str:
        value: Optional[str] = None
        if self._secrets_manager is not None:
            value = await self._secrets_manager.get_secret(secret_path=GEMINI_SECRET_PATH, secret_key=GEMINI_SECRET_KEY)
        cleaned = (value or os.getenv(GEMINI_ENV_KEY) or "").strip().strip('"').strip()
        if not cleaned:
            raise GeminiDecisionError("no_credentials", "Google AI Studio API key is not configured")
        return cleaned

    async def evaluate(self, client: httpx.AsyncClient, *, state: Any,
                       questions: Mapping[str, Mapping[str, Any]],
                       images: Optional[Mapping[str, tuple[bytes, str]]] = None) -> DecisionResponse:
        reason = unsupported_reason(questions)
        if reason:
            raise GeminiDecisionError(reason, "request exceeds a documented Decisions API limit")
        body = request_body(state, questions, images)
        headers = {"x-goog-api-key": await self._api_key(), "Content-Type": "application/json"}
        started = time.perf_counter()
        try:
            response = await client.post(GEMINI_DECISIONS_URL, headers=headers, json=body,
                                         timeout=self._timeout_seconds)
        except httpx.TimeoutException as exc:
            self._log_cost(status=None, input_tokens=None, success=False)
            raise GeminiDecisionError("timeout") from exc
        except httpx.TransportError as exc:
            self._log_cost(status=None, input_tokens=None, success=False)
            raise GeminiDecisionError("transport") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code >= 400:
            self._log_cost(status=response.status_code, input_tokens=None, success=False)
            error = payload.get("error") if isinstance(payload, dict) else None
            code = str(error.get("code") or "") if isinstance(error, dict) else ""
            if code in BLOCK_CODES:
                raise GeminiDecisionBlocked("blocked", code)
            if response.status_code == 429:
                raise GeminiDecisionError("rate_limited")
            raise GeminiDecisionError(f"http_{response.status_code}", code)
        if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
            self._log_cost(status=response.status_code, input_tokens=None, success=False)
            raise GeminiDecisionError("invalid_response")
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        input_tokens = usage.get("total_input_tokens")
        input_tokens = input_tokens if type(input_tokens) is int and input_tokens >= 0 else 0
        try:
            parsed = DecisionResponse.model_validate({
                "model": GEMINI_DECISION_MODEL, "answers": payload["answers"],
                "usage": {"input_tokens": input_tokens, "output_tokens": 0}})
        except ValidationError as exc:
            self._log_cost(status=response.status_code, input_tokens=input_tokens, success=False)
            raise GeminiDecisionError("invalid_response") from exc
        if set(questions) - set(parsed.answers):
            self._log_cost(status=response.status_code, input_tokens=input_tokens, success=False)
            raise GeminiDecisionError("missing_answers")
        self._log_cost(status=response.status_code, input_tokens=input_tokens, success=True)
        parsed.provider = GEMINI_DECISION_SERVER
        logger.debug("Gemini decision latency_ms=%.0f questions=%d", latency_ms, len(questions))
        return parsed

    def _log_cost(self, *, status: Optional[int], input_tokens: Optional[int], success: bool) -> None:
        if not self._telemetry_task_id:
            return
        cost = input_tokens * GEMINI_DECISION_INPUT_USD_PER_MILLION / 1_000_000 if success and input_tokens else None
        # Same record shape as Jev's LLM_JEV_COST so the cost dashboards sum both.
        logger.info("LLM_JEV_COST %s", json.dumps({
            "task_id": self._telemetry_task_id, "purpose": self._telemetry_purpose,
            "inference_host": GEMINI_DECISION_SERVER, "model_id": GEMINI_DECISION_PROVIDER_MODEL,
            "http_status": status, "success": success, "input_tokens": input_tokens, "output_tokens": 0,
            "supplier_cost_usd": cost, "supplier_cost_complete": cost is not None,
            "supplier_cost_source": "configured_rate" if cost is not None else None,
        }, sort_keys=True))
