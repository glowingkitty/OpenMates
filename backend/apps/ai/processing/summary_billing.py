"""Private, per-operation admission and settlement for automatic chat summaries."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import uuid
from typing import Any

import httpx

from backend.apps.ai.processing.model_usage_tracker import build_summary_usage_breakdown
from backend.core.api.app.tasks import celery_config
from backend.shared.python_schemas.llm_usage import normalize_provider_usage
from backend.shared.python_utils.billing_utils import (
    calculate_cache_aware_supplier_cost,
    calculate_total_credits,
    is_cache_tariff_admissible,
    select_customer_context_band,
    snapshot_model_tariff,
)

logger = logging.getLogger(__name__)


class SummaryBillingError(RuntimeError):
    """A summary cannot safely be dispatched or charged."""


class SummaryBillingLimitError(SummaryBillingError):
    """The wallet cannot cover the next summary provider call."""


class SummaryBillingUnsupportedFallbackError(SummaryBillingError):
    """The configured fallback has no admitted summary customer tariff."""


class SummaryBillingDuplicateError(SummaryBillingError):
    """An existing reservation may already have paid for this compression."""


class SummaryBillingAmbiguousError(SummaryBillingError):
    """Provider cost or settlement is uncertain; preserve the durable hold."""


def selected_main_cache_tariff_active(model_id: str) -> bool:
    """Only verified selected-main tariffs enable separate summary charges."""
    from backend.core.api.app.utils.server_mode import is_payment_enabled

    if not is_payment_enabled():
        return False
    if not isinstance(model_id, str) or "/" not in model_id:
        return False
    manager = celery_config.config_manager
    if manager is None:
        return False
    provider, suffix = model_id.split("/", 1)
    pricing = manager.get_model_pricing(provider, suffix)
    if not pricing:
        return False
    host = pricing.get("default_server") or provider
    return is_cache_tariff_admissible(pricing.get("cache_pricing") or {}, host)


def _quote_attempt(
    *, tariff: dict[str, Any], host: str, system_prompt: str,
    messages: list[dict[str, Any]], max_tokens: int,
) -> int:
    """Reserve a cold-input bound plus the full configured output cap."""
    input_bound = max(1, len(json.dumps(
        {"system": system_prompt, "messages": messages},
        default=str, separators=(",", ":"),
    ).encode("utf-8")))
    _band, rates = select_customer_context_band(
        model_pricing_details=tariff, inference_host=host, input_total=input_bound,
    )
    quote_tariff = copy.deepcopy(tariff)
    quote_tariff["pricing"]["tokens"] = copy.deepcopy(rates)
    policy = tariff.get("cache_pricing") or {}
    if policy.get("enabled") and policy.get("write_billing") == "separate":
        positive_units = [
            row["per_credit_unit"] for category in ("input", "cache_write", "cache_write_1h")
            if isinstance(row := rates.get(category), dict)
            and isinstance(row.get("per_credit_unit"), (int, float))
            and not isinstance(row["per_credit_unit"], bool)
            and row["per_credit_unit"] > 0
        ]
        if positive_units:
            quote_tariff["pricing"]["tokens"].setdefault("input", {})["per_credit_unit"] = min(positive_units)
    return calculate_total_credits(
        pricing_config=quote_tariff,
        input_tokens=input_bound,
        output_tokens=max_tokens,
    ) + 1  # Round-up room when a failed attempt precedes fallback.


class SummaryBillingOperation:
    """One summary hold, potentially two actual provider attempts, one charge."""

    def __init__(self, *, task_id: str, request_data: Any):
        identity = request_data.resolved_recovery_inference_task_id() or task_id
        self.charge_id = f"ai-ask:{identity}:summary"
        if (len(self.charge_id) > 255
                or re.fullmatch(r"ai-ask:[A-Za-z0-9_-]+:summary", self.charge_id) is None):
            raise SummaryBillingError("Summary charge identity is invalid")
        try:
            uuid.UUID(request_data.user_id)
            if request_data.team_id:
                uuid.UUID(request_data.team_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise SummaryBillingError("Summary billing actor identity is invalid") from exc
        if hashlib.sha256(request_data.user_id.encode("utf-8")).hexdigest() != request_data.user_id_hash:
            raise SummaryBillingError("Summary billing actor hash is invalid")
        for value in (request_data.chat_id, request_data.message_id):
            if (not isinstance(value, str)
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{0,254}", value) is None):
                raise SummaryBillingError("Summary chat or message identity is invalid")
        self.request_data = request_data
        self.buckets: list[dict[str, Any]] = []
        self.hold_active = False
        self.payment_skipped = False
        self.dispatched = False
        self.quoted_credits = 0
        self.intent_recorded = False
        self._admitted: dict[str, dict[str, Any]] = {}

    @staticmethod
    async def _post(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Local import keeps the ordinary main processor independent of summaries.
        from backend.apps.ai.processing.main_processor import _make_internal_api_request
        return await _make_internal_api_request("POST", endpoint, payload)

    def _identity(self) -> dict[str, Any]:
        request = self.request_data
        if request.team_id:
            return {"team_id": request.team_id, "actor_user_id": request.user_id}
        return {"user_id": request.user_id, "user_id_hash": request.user_id_hash}

    async def admit(
        self, *, model_id: str, host: str, system_prompt: str,
        messages: list[dict[str, Any]], max_tokens: int, attempt_id: str,
    ) -> None:
        if attempt_id in self._admitted:
            raise SummaryBillingError("Summary attempt was already admitted")
        manager = celery_config.config_manager
        if manager is None or "/" not in model_id:
            raise SummaryBillingError("Summary pricing is unavailable")
        provider, suffix = model_id.split("/", 1)
        pricing = manager.get_model_pricing(provider, suffix)
        if not pricing:
            raise SummaryBillingError("Summary model is unpriced")
        tariff = snapshot_model_tariff(pricing)
        quote = _quote_attempt(
            tariff=tariff, host=host, system_prompt=system_prompt,
            messages=messages, max_tokens=max_tokens,
        )
        observed = 0
        if self.buckets:
            observed = build_summary_usage_breakdown(
                self.buckets, manager.get_model_pricing,
            )["credits_charged"]
        cumulative = max(self.quoted_credits, observed + quote)
        endpoint = "internal/billing/team/reserve" if self.request_data.team_id else "internal/billing/reserve"
        try:
            response = await self._post(endpoint, {
                **self._identity(), "idempotency_key": self.charge_id,
                "quoted_credits": cumulative, "app_id": "ai", "skill_id": "ask",
            })
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 402:
                raise SummaryBillingLimitError("Insufficient credits for summary") from exc
            raise SummaryBillingAmbiguousError("Summary reservation was rejected") from exc
        except Exception as exc:
            raise SummaryBillingAmbiguousError("Summary reservation acknowledgement is unavailable") from exc
        if response.get("charge_id") != self.charge_id:
            raise SummaryBillingAmbiguousError("Summary reservation identity mismatch")
        if response.get("state") == "skipped":
            self.payment_skipped = True
        elif response.get("state") == "reserved":
            held = response.get("quoted_credits")
            if type(held) is not int or held < cumulative:
                raise SummaryBillingAmbiguousError("Summary reservation quote is invalid")
            if not self.dispatched and response.get("created") is not True:
                raise SummaryBillingDuplicateError("Summary hold already exists")
            self.hold_active = True
            self.quoted_credits = held
        else:
            raise SummaryBillingAmbiguousError("Summary reservation state is invalid")
        self._admitted[attempt_id] = {
            "model_id": model_id, "host": host, "tariff": tariff,
        }
        self.dispatched = True

    def observe(self, response: Any, *, attempt_id: str) -> None:
        if self.payment_skipped:
            return
        admitted = self._admitted.get(attempt_id)
        if not admitted:
            raise SummaryBillingError("Summary response has no admitted attempt")
        usage = getattr(response, "usage", None)
        if usage is None:
            raise SummaryBillingAmbiguousError("Summary response omitted provider usage")
        if (admitted["host"] == "cerebras"
                and getattr(usage, "_cerebras_reported_usage_complete", False) is not True):
            raise SummaryBillingAmbiguousError("Cerebras summary usage is not fully reported")
        if admitted["host"] == "google_ai_studio":
            def count(name: str) -> Any:
                return usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)

            prompt = count("prompt_token_count")
            candidates = count("candidates_token_count")
            thoughts = count("thoughts_token_count")
            total = count("total_token_count")
            if thoughts is None:
                # A missing thought counter proves zero only when Google's
                # inclusive total reconciles to prompt plus candidates.
                if (type(prompt) is not int or type(candidates) is not int
                        or type(total) is not int or total != prompt + candidates):
                    raise SummaryBillingAmbiguousError("Summary reasoning output is not fully reported")
            elif (type(total) is int and type(prompt) is int and type(candidates) is int
                  and total != prompt + candidates + thoughts):
                raise SummaryBillingAmbiguousError("Summary output counters do not reconcile")
        try:
            normalized = normalize_provider_usage(
                usage,
                model_id=admitted["model_id"],
                provider_kind="google" if admitted["host"] == "google_ai_studio" else "openai",
                attempt_id=attempt_id,
                inference_host=admitted["host"],
                tariff_snapshot=admitted["tariff"],
            )
        except (TypeError, ValueError) as exc:
            raise SummaryBillingAmbiguousError("Summary usage cannot be normalized") from exc
        if normalized.usage_source != "provider_reported":
            raise SummaryBillingAmbiguousError("Summary provider usage is incomplete")
        bucket = normalized.to_bucket()
        bucket.pop("provider_request_id", None)
        self.buckets.append(bucket)
        try:
            estimate = calculate_cache_aware_supplier_cost(
                usage=bucket, model_pricing_details=admitted["tariff"],
                inference_host=admitted["host"],
            )
        except (TypeError, ValueError, RuntimeError):
            estimate = {"complete": False, "upper_bound_complete": False}
        supplier_complete = bool(estimate["complete"])
        supplier_cost = str(estimate["cost_usd"]) if supplier_complete else None
        supplier_upper_bound = (
            str(estimate["cost_upper_bound_usd"])
            if estimate.get("upper_bound_complete") else None
        )
        logger.info(
            "LLM_SUMMARY_COST %s",
            json.dumps({
                "charge_id": self.charge_id, "attempt_id": attempt_id,
                "model_id": bucket["model_id"], "host": bucket["inference_host"],
                "input_tokens": bucket["input_tokens"], "output_tokens": bucket["output_tokens"],
                "reasoning_tokens": bucket.get("output_reasoning_tokens"),
                "supplier_cost_usd": supplier_cost,
                "supplier_cost_complete": supplier_complete,
                "supplier_cost_upper_bound_usd": supplier_upper_bound,
            }, sort_keys=True),
        )

    def receipt(self) -> dict[str, Any]:
        if not self.buckets:
            raise SummaryBillingAmbiguousError("Summary has no reported usage")
        manager = celery_config.config_manager
        if manager is None:
            raise SummaryBillingError("Summary pricing is unavailable")
        try:
            receipt = build_summary_usage_breakdown(self.buckets, manager.get_model_pricing)
        except (TypeError, ValueError, RuntimeError) as exc:
            raise SummaryBillingAmbiguousError("Summary reported usage cannot be priced") from exc
        if self.hold_active and receipt["credits_charged"] > self.quoted_credits:
            raise SummaryBillingAmbiguousError("Summary usage exceeded reserved credits")
        receipt["settlement_state"] = "pending"
        return receipt

    async def record_intent(self, *, summary_message_id: str) -> dict[str, Any] | None:
        if self.payment_skipped:
            return None
        receipt = self.receipt()
        request = self.request_data
        payload = {
            "charge_id": self.charge_id,
            "user_id": request.user_id,
            **({"team_id": request.team_id} if request.team_id else {}),
            "user_id_hash": request.user_id_hash,
            "app_id": "ai", "skill_id": "ask",
            "chat_id": request.chat_id, "message_id": request.message_id,
            "summary_message_id": summary_message_id,
            "llm_usage_breakdown": receipt,
        }
        try:
            response = await self._post("internal/billing/reservation/record-intent", payload)
        except Exception as exc:
            raise SummaryBillingAmbiguousError("Summary billing intent was not acknowledged") from exc
        if response.get("state") != "response_recorded" or response.get("charge_id") != self.charge_id:
            raise SummaryBillingAmbiguousError("Summary billing intent acknowledgement is invalid")
        self.intent_recorded = True
        return receipt

    async def settle(self, *, receipt: dict[str, Any]) -> dict[str, Any]:
        if self.payment_skipped:
            return {"state": "skipped"}
        if not self.intent_recorded:
            raise SummaryBillingError("Summary charge lacks a durable intent")
        request = self.request_data
        details = {
            "chat_id": request.chat_id, "message_id": request.message_id,
            "root_chat_id": request.root_chat_id or request.chat_id,
            "actual_chat_id": request.chat_id,
            "root_turn_id": request.root_turn_id,
            "orchestration_id": request.orchestration_id,
            "depth": request.sub_chat_depth,
            "operation_id": self.charge_id,
            "source": "chat" if not request.api_key_hash else "api",
            "usage_type": "llm_tokens",
            "purpose": "summary",
            "is_incognito": request.is_incognito,
            "model_used": self.buckets[-1]["model_id"],
            "input_tokens": receipt["input_tokens"],
            "output_tokens": receipt["output_tokens"],
            "llm_usage_breakdown": receipt,
            "reservation_required": self.hold_active,
        }
        if request.team_id:
            endpoint = "internal/billing/team/charge"
            payload = {
                "team_id": request.team_id, "actor_user_id": request.user_id,
                "credits": receipt["credits_charged"], "app_id": "ai", "skill_id": "ask",
                "idempotency_key": self.charge_id,
                "usage_details": {
                    **details,
                    "workspace_type": request.team_workspace_type or "chat",
                    "object_id_hash": request.team_object_id_hash,
                },
            }
        else:
            endpoint = "internal/billing/charge"
            payload = {
                "user_id": request.user_id, "user_id_hash": request.user_id_hash,
                "credits": receipt["credits_charged"], "app_id": "ai", "skill_id": "ask",
                "idempotency_key": self.charge_id, "usage_details": details,
                "api_key_hash": request.api_key_hash, "device_hash": request.device_hash,
            }
        response = None
        for attempt in range(2):
            try:
                response = await self._post(endpoint, payload)
                break
            except Exception as exc:
                if attempt:
                    raise SummaryBillingAmbiguousError("Summary settlement acknowledgement is unavailable") from exc
        assert response is not None
        if response.get("state") not in {"committed", "retry_scheduled"} or (
            response.get("charge_id", self.charge_id) != self.charge_id
        ):
            raise SummaryBillingAmbiguousError("Summary settlement acknowledgement is invalid")
        return response

    async def release_failed(self) -> None:
        if not self.hold_active or self.intent_recorded:
            return
        request = self.request_data
        try:
            response = await self._post("internal/billing/reservation/release", {
                "subject_kind": "team" if request.team_id else "personal",
                "idempotency_key": self.charge_id,
                "reason": "provider_failed" if self.dispatched else "cancelled_before_dispatch",
                **self._identity(),
            })
        except Exception as exc:
            raise SummaryBillingAmbiguousError("Summary hold release is unacknowledged") from exc
        if response.get("state") != "released":
            # Core may return another idempotent terminal spelling; the hold is
            # not assumed released until a documented acknowledgement exists.
            raise SummaryBillingAmbiguousError("Summary hold release acknowledgement is invalid")
        self.hold_active = False
