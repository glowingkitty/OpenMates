# backend/apps/code/skills/image_to_html_skill.py
#
# Code image-to-HTML skill contract.
# Long-running provider work follows the existing media app-skill pattern: this
# skill validates the request, allocates/reuses an embed ID, dispatches an
# app_code Celery task, and returns processing metadata. The worker task owns
# Gemini/E2B calls, billing, encrypted screenshot storage, and final embed
# delivery.

from __future__ import annotations

import base64
import logging
import math
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.python_utils.app_skill_helpers import execute_skill_via_celery
from backend.shared.python_utils.billing_utils import get_usd_per_credit

logger = logging.getLogger(__name__)


DEFAULT_MAX_CORRECTION_PASSES = 2
MAX_CORRECTION_PASSES = 5
MIN_CORRECTION_PASSES = 0
MAX_IMAGE_BYTES = 10 * 1024 * 1024
SUPPORTED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
DEFAULT_INPUT_USD_PER_MILLION = 1.5
DEFAULT_OUTPUT_USD_PER_MILLION = 7.5
DEFAULT_CACHE_READ_USD_PER_MILLION = 0.2
DEFAULT_CACHE_WRITE_USD_PER_MILLION = 0.2
DEFAULT_INPUT_TOKENS_PER_CREDIT = 200
DEFAULT_OUTPUT_TOKENS_PER_CREDIT = 45
DEFAULT_CACHE_READ_TOKENS_PER_CREDIT = 5000
DEFAULT_CACHE_WRITE_TOKENS_PER_CREDIT = 5000
DEFAULT_E2B_CREDITS_PER_STARTED_MINUTE = 5
DEFAULT_MINIMUM_CREDITS = 30
DEFAULT_RESERVED_CREDITS_PER_REQUEST = 500


@dataclass(frozen=True)
class ParsedImageToHtmlInput:
    image_bytes: bytes
    mime_type: str
    filename: str | None = None
    max_correction_passes: int = DEFAULT_MAX_CORRECTION_PASSES


@dataclass(frozen=True)
class ParsedImageToHtmlDispatchInput:
    image_base64: str | None
    mime_type: str | None
    filename: str | None = None
    source_image_embed_id: str | None = None
    max_correction_passes: int = DEFAULT_MAX_CORRECTION_PASSES


@dataclass(frozen=True)
class ImageToHtmlGenerationResult:
    html: str
    screenshot_bytes: bytes | None = None
    screenshot_mime_type: str | None = None
    correction_passes_used: int = 0
    validation_warnings: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImageToHtmlUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    e2b_render_seconds: float = 0.0
    correction_passes_used: int = 0


@dataclass(frozen=True)
class ImageToHtmlCreditCharge:
    usage: ImageToHtmlUsage
    provider_cost_usd: float
    model_credits: int
    e2b_credits: int
    e2b_started_minutes: int
    credits_charged: int


class ImageToHtmlResponse(BaseModel):
    results: list[dict[str, Any]] = Field(default_factory=list)
    task_id: str | None = None
    embed_id: str | None = None
    task_ids: list[str] | None = None
    embed_ids: list[str] | None = None
    status: str = "processing"
    error: str | None = None


def validate_image_input(request: dict[str, Any]) -> ParsedImageToHtmlInput:
    if request.get("image_url"):
        raise ValueError("image_url is not supported for code.image_to_html v1")

    image_base64 = request.get("image_base64")
    if not image_base64 or not isinstance(image_base64, str):
        received_keys = sorted(str(key) for key in request.keys())
        raise ValueError(f"image_base64 is required (received keys: {received_keys})")

    mime_type = str(request.get("mime_type") or "").strip().lower()
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ValueError("mime_type must be image/png, image/jpeg, or image/webp")

    try:
        image_bytes = base64.b64decode(image_base64, validate=True)
    except Exception as exc:
        raise ValueError("image_base64 must be valid base64") from exc

    if not image_bytes:
        raise ValueError("image_base64 decoded to an empty image")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("image_base64 exceeds the maximum supported image size")

    max_correction_passes = request.get("max_correction_passes", DEFAULT_MAX_CORRECTION_PASSES)
    if not isinstance(max_correction_passes, int):
        raise ValueError("max_correction_passes must be an integer")
    if max_correction_passes < MIN_CORRECTION_PASSES or max_correction_passes > MAX_CORRECTION_PASSES:
        raise ValueError(f"max_correction_passes must be between {MIN_CORRECTION_PASSES} and {MAX_CORRECTION_PASSES}")

    filename = request.get("filename")
    return ParsedImageToHtmlInput(
        image_bytes=image_bytes,
        mime_type=mime_type,
        filename=str(filename) if filename else None,
        max_correction_passes=max_correction_passes,
    )


def parse_image_to_html_dispatch_input(
    request: dict[str, Any],
    *,
    file_path_index: dict[str, str] | None = None,
) -> ParsedImageToHtmlDispatchInput:
    """Validate a request before dispatching to the worker.

    Chat calls pass source_image as an embed_ref; REST/API calls pass image_base64.
    The worker performs actual decryption for embed_refs after its services are initialized.
    """
    if request.get("image_url"):
        raise ValueError("image_url is not supported for code.image_to_html v1")

    if request.get("image_base64"):
        parsed = validate_image_input(request)
        return ParsedImageToHtmlDispatchInput(
            image_base64=base64.b64encode(parsed.image_bytes).decode("ascii"),
            mime_type=parsed.mime_type,
            filename=parsed.filename,
            max_correction_passes=parsed.max_correction_passes,
        )

    max_correction_passes = request.get("max_correction_passes", DEFAULT_MAX_CORRECTION_PASSES)
    if not isinstance(max_correction_passes, int):
        raise ValueError("max_correction_passes must be an integer")
    if max_correction_passes < MIN_CORRECTION_PASSES or max_correction_passes > MAX_CORRECTION_PASSES:
        raise ValueError(f"max_correction_passes must be between {MIN_CORRECTION_PASSES} and {MAX_CORRECTION_PASSES}")

    source_image = str(request.get("source_image") or request.get("file_path") or request.get("filename") or "").strip()
    if not source_image:
        received_keys = sorted(str(key) for key in request.keys())
        raise ValueError(f"source_image or image_base64 is required (received keys: {received_keys})")

    source_embed_id = (file_path_index or {}).get(source_image)
    if not source_embed_id:
        available = sorted((file_path_index or {}).keys())
        raise ValueError(f"source_image '{source_image}' was not found in uploaded images (available: {available})")

    return ParsedImageToHtmlDispatchInput(
        image_base64=None,
        mime_type=None,
        filename=source_image,
        source_image_embed_id=source_embed_id,
        max_correction_passes=max_correction_passes,
    )


def calculate_image_to_html_credits(
    usage: ImageToHtmlUsage,
    *,
    pricing_details: dict[str, Any] | None = None,
    input_tokens_per_credit: int = DEFAULT_INPUT_TOKENS_PER_CREDIT,
    output_tokens_per_credit: int = DEFAULT_OUTPUT_TOKENS_PER_CREDIT,
    cache_read_tokens_per_credit: int = DEFAULT_CACHE_READ_TOKENS_PER_CREDIT,
    cache_write_tokens_per_credit: int = DEFAULT_CACHE_WRITE_TOKENS_PER_CREDIT,
    input_usd_per_million: float = 0.0,
    output_usd_per_million: float = 0.0,
    cache_read_usd_per_million: float = 0.0,
    cache_write_usd_per_million: float = 0.0,
    e2b_credits_per_started_minute: int = 5,
    minimum_credits: int = 1,
) -> ImageToHtmlCreditCharge:
    token_pricing = (pricing_details or {}).get("pricing", {}).get("tokens", {}) if pricing_details else {}
    input_tokens_per_credit = _positive_int(
        token_pricing.get("input", {}).get("per_credit_unit") if isinstance(token_pricing.get("input"), dict) else None,
        input_tokens_per_credit,
    )
    output_tokens_per_credit = _positive_int(
        token_pricing.get("output", {}).get("per_credit_unit") if isinstance(token_pricing.get("output"), dict) else None,
        output_tokens_per_credit,
    )

    costs = (pricing_details or {}).get("costs", {}) if pricing_details else {}
    input_usd_per_million = _positive_float(
        (costs.get("input_per_million_token") or {}).get("price") if isinstance(costs.get("input_per_million_token"), dict) else None,
        input_usd_per_million,
    )
    output_usd_per_million = _positive_float(
        (costs.get("output_per_million_token") or {}).get("price") if isinstance(costs.get("output_per_million_token"), dict) else None,
        output_usd_per_million,
    )

    provider_cost_usd = (
        (usage.input_tokens / 1_000_000) * input_usd_per_million
        + (usage.output_tokens / 1_000_000) * output_usd_per_million
        + (usage.cache_read_tokens / 1_000_000) * cache_read_usd_per_million
        + (usage.cache_write_tokens / 1_000_000) * cache_write_usd_per_million
    )
    model_credits = math.ceil(
        _credits_for_tokens(usage.input_tokens, input_tokens_per_credit)
        + _credits_for_tokens(usage.output_tokens, output_tokens_per_credit)
        + _credits_for_tokens(usage.cache_read_tokens, cache_read_tokens_per_credit)
        + _credits_for_tokens(usage.cache_write_tokens, cache_write_tokens_per_credit)
    )
    e2b_started_minutes = math.ceil(max(0.0, usage.e2b_render_seconds) / 60.0)
    e2b_credits = e2b_started_minutes * e2b_credits_per_started_minute
    credits_charged = max(minimum_credits, model_credits + e2b_credits)
    return ImageToHtmlCreditCharge(
        usage=usage,
        provider_cost_usd=provider_cost_usd,
        model_credits=model_credits,
        e2b_credits=e2b_credits,
        e2b_started_minutes=e2b_started_minutes,
        credits_charged=credits_charged,
    )


def _credits_for_tokens(tokens: int, tokens_per_credit: int) -> float:
    if tokens <= 0 or tokens_per_credit <= 0:
        return 0.0
    return tokens / tokens_per_credit


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _positive_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def image_to_html_model_pricing(model_reference: str) -> dict[str, Any] | None:
    if "/" not in model_reference:
        return None
    provider_id, model_id = model_reference.split("/", 1)
    try:
        from backend.core.api.app.utils.config_manager import ConfigManager

        return ConfigManager().get_model_pricing(provider_id, model_id)
    except Exception:
        logger.exception("Failed to resolve pricing for image-to-HTML model %s", model_reference)
        return None


class ImageToHtmlSkill(BaseSkill):
    """Generate standalone inline HTML from screenshot bytes."""

    async def execute(
        self,
        requests: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ImageToHtmlResponse:
        if not self.celery_producer:
            logger.error("Celery producer not available in ImageToHtmlSkill (App: %s)", self.app_id)
            return ImageToHtmlResponse(
                results=[{"error": "Image-to-HTML service temporarily unavailable"}],
                status="error",
                error="Image-to-HTML service temporarily unavailable",
            )

        results: list[dict[str, Any]] = []
        user_id = kwargs.get("user_id")
        file_path_index = kwargs.get("file_path_index") or {}
        placeholder_embed_ids = kwargs.get("placeholder_embed_ids") or []
        for index, request in enumerate(requests):
            parsed = parse_image_to_html_dispatch_input(request, file_path_index=file_path_index)
            embed_id = (
                str(placeholder_embed_ids[index])
                if index < len(placeholder_embed_ids) and placeholder_embed_ids[index]
                else str(uuid.uuid4())
            )
            arguments = {
                "filename": parsed.filename,
                "max_correction_passes": parsed.max_correction_passes,
                "reserved_credits": reserved_credits_for_correction_passes(parsed.max_correction_passes),
                "user_id": user_id,
                "user_vault_key_id": kwargs.get("user_vault_key_id"),
                "chat_id": self._current_chat_id or kwargs.get("chat_id"),
                "message_id": self._current_message_id or kwargs.get("message_id"),
                "external_request": kwargs.get("external_request", False),
                "api_key_hash": kwargs.get("api_key_hash"),
                "device_hash": kwargs.get("device_hash"),
                "app_id": self.app_id,
                "skill_id": self.skill_id,
                "embed_id": embed_id,
            }
            if parsed.source_image_embed_id:
                arguments["source_image_embed_id"] = parsed.source_image_embed_id
            else:
                arguments["image_base64"] = parsed.image_base64
                arguments["mime_type"] = parsed.mime_type
            task_id = await execute_skill_via_celery(
                app_id=self.app_id,
                skill_id=self.skill_id,
                arguments=arguments,
                celery_producer=self.celery_producer,
            )
            results.append({
                "task_id": task_id,
                "embed_id": embed_id,
                "status": "processing",
                "reserved_credits": reserved_credits_for_correction_passes(parsed.max_correction_passes),
            })
        if not results:
            return ImageToHtmlResponse(results=[], status="error", error="No valid image-to-HTML requests provided")
        if len(results) == 1:
            return ImageToHtmlResponse(
                results=results,
                task_id=results[0]["task_id"],
                embed_id=results[0]["embed_id"],
            )
        return ImageToHtmlResponse(
            results=results,
            task_ids=[item["task_id"] for item in results],
            embed_ids=[item["embed_id"] for item in results],
        )


def _result_payload(
    generation: ImageToHtmlGenerationResult,
    max_correction_passes: int,
    *,
    chat_bound: bool = False,
    placeholder_embed_ids: list[str] | None = None,
) -> dict[str, Any]:
    usage = _usage_payload_with_credits(generation, max_correction_passes)
    embed_id = _resolve_result_embed_id(chat_bound, placeholder_embed_ids)
    payload: dict[str, Any] = {
        "html": generation.html,
        "embed_id": embed_id,
        "latest_screenshot_url": None,
        "latest_screenshot_mime_type": generation.screenshot_mime_type,
        "correction_passes_used": generation.correction_passes_used,
        "validation_warnings": generation.validation_warnings,
        "usage": usage,
    }
    if generation.screenshot_bytes is not None:
        payload["latest_screenshot_base64"] = base64.b64encode(generation.screenshot_bytes).decode("ascii")
    if chat_bound:
        payload["embed"] = _code_embed_payload(generation, usage, embed_id)
    return payload


def _direct_result_payload(
    generation: ImageToHtmlGenerationResult,
    max_correction_passes: int,
) -> dict[str, Any]:
    return _result_payload(generation, max_correction_passes)


def reserved_credits_for_correction_passes(max_correction_passes: int) -> int:
    return DEFAULT_RESERVED_CREDITS_PER_REQUEST * max(1, int(max_correction_passes) + 1)


def _resolve_result_embed_id(chat_bound: bool, placeholder_embed_ids: list[str] | None) -> str | None:
    if not chat_bound:
        return None
    if placeholder_embed_ids and placeholder_embed_ids[0]:
        return str(placeholder_embed_ids[0])
    return str(uuid.uuid4())


def _code_embed_payload(
    generation: ImageToHtmlGenerationResult,
    usage: dict[str, Any],
    embed_id: str | None,
) -> dict[str, Any]:
    line_count = max(1, generation.html.count("\n") + 1)
    return {
        "type": "code",
        "frontend_type": "code-code",
        "backend_type": "code",
        "embed_id": embed_id,
        "language": "html",
        "filename": "index.html",
        "code": generation.html,
        "line_count": line_count,
        "latest_screenshot_url": None,
        "latest_screenshot": None,
        "latest_screenshot_mime_type": generation.screenshot_mime_type,
        "image_to_html_metadata": {
            "correction_passes_used": generation.correction_passes_used,
            "validation_warnings": generation.validation_warnings,
            "usage": usage,
        },
    }


def _usage_payload_with_credits(
    generation: ImageToHtmlGenerationResult,
    max_correction_passes: int,
) -> dict[str, Any]:
    usage_payload = dict(generation.usage or {})
    usage = ImageToHtmlUsage(
        model=str(usage_payload.get("model") or "unknown"),
        input_tokens=int(usage_payload.get("input_tokens") or 0),
        output_tokens=int(usage_payload.get("output_tokens") or 0),
        cache_read_tokens=int(usage_payload.get("cache_read_tokens") or 0),
        cache_write_tokens=int(usage_payload.get("cache_write_tokens") or 0),
        e2b_render_seconds=float(usage_payload.get("e2b_render_seconds") or 0.0),
        correction_passes_used=int(usage_payload.get("correction_passes_used") or generation.correction_passes_used),
    )
    charge = calculate_image_to_html_credits(
        usage,
        pricing_details=image_to_html_model_pricing(usage.model),
        input_usd_per_million=DEFAULT_INPUT_USD_PER_MILLION,
        output_usd_per_million=DEFAULT_OUTPUT_USD_PER_MILLION,
        cache_read_usd_per_million=DEFAULT_CACHE_READ_USD_PER_MILLION,
        cache_write_usd_per_million=DEFAULT_CACHE_WRITE_USD_PER_MILLION,
        e2b_credits_per_started_minute=DEFAULT_E2B_CREDITS_PER_STARTED_MINUTE,
        minimum_credits=DEFAULT_MINIMUM_CREDITS,
    )
    estimated_cost_credits = math.ceil(charge.provider_cost_usd / get_usd_per_credit()) if charge.provider_cost_usd > 0 else 0
    reserved_credits = DEFAULT_RESERVED_CREDITS_PER_REQUEST * max(1, max_correction_passes + 1)
    usage_payload.update(
        {
            "model": usage.model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "e2b_render_seconds": usage.e2b_render_seconds,
            "duration_second": usage.e2b_render_seconds,
            "correction_passes_used": usage.correction_passes_used,
            "provider_cost_usd": charge.provider_cost_usd,
            "provider_cost_credits": estimated_cost_credits,
            "model_credits": charge.model_credits,
            "e2b_credits": charge.e2b_credits,
            "e2b_started_minutes": charge.e2b_started_minutes,
            "reserved_credits": reserved_credits,
            "credits_charged": charge.credits_charged,
            "credits_refunded": max(0, reserved_credits - charge.credits_charged),
        }
    )
    return usage_payload
