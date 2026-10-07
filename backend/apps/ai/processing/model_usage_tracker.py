"""Provider-aware usage tracking for multi-iteration main-model calls."""

import copy
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Any, Callable, Dict, Iterable, Mapping

from backend.shared.python_schemas.llm_usage import NormalizedLLMUsage
from backend.shared.python_utils.billing_utils import (
    calculate_token_category_credits,
    decimal_string,
    floor_raw_credits,
    is_cache_tariff_eligible,
    select_customer_context_band,
    snapshot_model_tariff,
)


def _optional_total(buckets: list[Mapping[str, Any]], name: str) -> int | None:
    return None if any(bucket.get(name) is None for bucket in buckets) else sum(int(bucket[name]) for bucket in buckets)


def _pricing_for_bucket(
    bucket: Mapping[str, Any],
    pricing_lookup: Callable[[str, str], Dict[str, Any] | None],
    default_provider: str | None,
) -> tuple[str, Dict[str, Any]]:
    model_id = str(bucket["model_id"])
    if "/" in model_id:
        provider, suffix = model_id.split("/", 1)
    elif default_provider:
        provider, suffix = default_provider, model_id
    else:
        raise RuntimeError("Usage pricing requires a provider-qualified model ID")
    snapshot = bucket.get("tariff_snapshot")
    if snapshot:
        frozen = dict(snapshot)
        return model_id, frozen if frozen.get("pricing_version") else snapshot_model_tariff(frozen)
    pricing = pricing_lookup(provider, suffix)
    if not pricing:
        raise RuntimeError(f"Pricing details for model '{model_id}' are not available")
    return model_id, snapshot_model_tariff(pricing)


def _validate_summary_bucket(bucket: Mapping[str, Any]) -> None:
    snapshot = bucket.get("tariff_snapshot")
    if (not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("pricing_version"), str)
            or not snapshot["pricing_version"] or not isinstance(bucket.get("attempt_id"), str)
            or not bucket["attempt_id"] or not isinstance(bucket.get("model_id"), str)
            or not bucket["model_id"]):
        raise ValueError("Summary billing requires a frozen tariff, model, and attempt identity")
    if (type(bucket.get("input_tokens")) is not int or type(bucket.get("output_tokens")) is not int
            or bucket["input_tokens"] < 0 or bucket["output_tokens"] < 0
            or bucket.get("usage_source") != "provider_reported"):
        raise ValueError("Summary billing requires reported inclusive input and billable output totals")


def build_model_usage_breakdown(
    usage_buckets: Iterable[Mapping[str, Any]],
    pricing_lookup: Callable[[str, str], Dict[str, Any] | None],
    *,
    default_provider: str | None = None,
    purpose: str | None = None,
) -> Dict[str, Any]:
    """Build one attempt-itemized receipt and floor fractional credits once."""
    if purpose not in {None, "summary"}:
        raise ValueError("Unknown LLM usage receipt purpose")
    buckets = list(usage_buckets)
    entries: list[Dict[str, Any]] = []
    raw_total = Fraction(0)
    receipt_raw_total = Decimal(0)
    input_total = output_total = uncached_total = 0
    sources: set[str] = set()
    for bucket in buckets:
        if purpose == "summary":
            _validate_summary_bucket(bucket)
        model_id, tariff = _pricing_for_bucket(bucket, pricing_lookup, default_provider)
        input_tokens = int(bucket.get("input_tokens") or 0)
        output_tokens = int(bucket.get("output_tokens") or 0)
        legacy_output = bucket.get("legacy_billable_output_tokens")
        charged_output = (
            output_tokens if purpose == "summary" or is_cache_tariff_eligible(tariff.get("cache_pricing", {}), bucket.get("inference_host")) or legacy_output is None
            else int(legacy_output)
        )
        uncached = int(bucket.get("uncached_input_tokens", input_tokens))
        read = bucket.get("cache_read_input_tokens")
        write = bucket.get("cache_creation_input_tokens")
        write_5m = bucket.get("cache_creation_5m_input_tokens")
        write_1h = bucket.get("cache_creation_1h_input_tokens")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in
               (input_tokens, output_tokens, uncached, *(value for value in (read, write, write_5m, write_1h) if value is not None))):
            raise ValueError("LLM token categories must be non-negative integers")
        if uncached + (read or 0) + (write or 0) != input_tokens:
            raise ValueError("LLM input token categories do not reconcile")
        if (write_5m or 0) + (write_1h or 0) > (write or 0):
            raise ValueError("LLM cache retention subtotals exceed writes")
        source = str(bucket.get("usage_source") or "provider_reported")
        if source not in {"provider_reported", "estimated"}:
            raise ValueError("Unknown LLM usage source")
        categories, active = calculate_token_category_credits(
            input_total=input_tokens,
            uncached_input=uncached,
            cache_read=read,
            cache_write=write,
            cache_write_1h=write_1h,
            output_tokens=output_tokens,
            legacy_billable_input=None if purpose == "summary" else bucket.get("legacy_billable_input_tokens"),
            model_pricing_details=tariff,
            usage_source=source,
            inference_host=bucket.get("inference_host"),
            legacy_billable_output=None if purpose == "summary" else legacy_output,
        )
        eligible_policy = is_cache_tariff_eligible(tariff.get("cache_pricing", {}), bucket.get("inference_host"))
        if active:
            billed_input_tokens = (
                uncached if tariff.get("cache_pricing", {}).get("write_billing") == "separate"
                else uncached + (write or 0)
            )
        else:
            billed_input_tokens = (
                input_tokens if purpose == "summary" or eligible_policy or bucket.get("legacy_billable_input_tokens") is None
                else int(bucket["legacy_billable_input_tokens"])
            )
        raw = sum(categories.values(), Fraction(0))
        raw_total += raw
        category_strings = {name: decimal_string(amount) for name, amount in categories.items()}
        with localcontext() as context:
            context.prec = 200
            entry_receipt_raw = sum((Decimal(value) for value in category_strings.values()), Decimal(0))
            receipt_raw_total += entry_receipt_raw
        input_total += input_tokens
        output_total += charged_output
        uncached_total += uncached
        sources.add(source)
        context_band, rates = select_customer_context_band(
            model_pricing_details=tariff,
            inference_host=bucket.get("inference_host"),
            input_total=input_tokens,
        )
        one_hour_hosts = tariff.get("cache_pricing", {}).get("cache_write_1h_hosts")
        one_hour_rate_visible = one_hour_hosts is None or bucket.get("inference_host") in one_hour_hosts
        entry = {
            "model_id": model_id,
            "inference_host": bucket.get("inference_host"),
            "pricing_version": tariff.get("pricing_version"),
            "input_tokens": input_tokens,
            "uncached_input_tokens": uncached,
            "billed_input_tokens": billed_input_tokens,
            "billing_mode": "cache_aware" if active else "ordinary_input",
            "cache_read_input_tokens": read,
            "cache_creation_input_tokens": write,
            "cache_creation_5m_input_tokens": write_5m,
            "cache_creation_1h_input_tokens": write_1h,
            "output_tokens": charged_output,
            "rates": {
                name: (str(rates[name]["per_credit_unit"])
                       if name in rates and rates[name].get("per_credit_unit") is not None
                       and (name in {"input", "output"} or active)
                       and (name != "cache_write_1h" or one_hour_rate_visible) else None)
                for name in ("input", "output", "cache_read", "cache_write", "cache_write_1h")
            },
            "category_credits": category_strings,
            "raw_credits": decimal_string(entry_receipt_raw),
        }
        write_billing = tariff.get("cache_pricing", {}).get("write_billing")
        if active and write_billing in {"included_in_input", "separate"}:
            entry["write_billing"] = write_billing
        if context_band is not None:
            entry["context_band"] = context_band
        if purpose == "summary":
            entry["purpose"] = "summary"
        entries.append(entry)
    charged = floor_raw_credits(raw_total)
    with localcontext() as context:
        context.prec = 200
        rounding_adjustment = Decimal(charged) - receipt_raw_total
    return {
        "schema_version": 1,
        "input_tokens": input_total,
        "uncached_input_tokens": uncached_total,
        "cache_read_input_tokens": _optional_total(buckets, "cache_read_input_tokens"),
        "cache_creation_input_tokens": _optional_total(buckets, "cache_creation_input_tokens"),
        "output_tokens": output_total,
        "usage_source": next(iter(sources)) if len(sources) == 1 else "mixed",
        "entries": entries,
        "raw_credits": decimal_string(receipt_raw_total),
        "rounding_adjustment": decimal_string(rounding_adjustment),
        "credits_charged": charged,
        "settlement_state": "settled",
    }


def build_summary_usage_breakdown(
    usage_buckets: Iterable[Mapping[str, Any]],
    pricing_lookup: Callable[[str, str], Dict[str, Any] | None],
    *,
    default_provider: str | None = None,
) -> Dict[str, Any]:
    """Price reported summary attempts from their frozen tariffs with one floor.

    A repeated cumulative snapshot replaces the prior state of the same attempt;
    distinct incurred fallback attempts remain separate receipt entries.
    """
    tracker = ModelUsageTracker()
    for bucket in usage_buckets:
        _validate_summary_bucket(bucket)
        tracker.record_reported_usage(
            model_id=bucket["model_id"], normalized_usage=bucket, attempt_id=bucket["attempt_id"],
            usage_event_kind="cumulative",
        )
    return build_model_usage_breakdown(
        tracker.usage_by_model, pricing_lookup, default_provider=default_provider, purpose="summary",
    )


def calculate_model_usage_credits(
    usage_by_model: Iterable[Mapping[str, Any]],
    pricing_lookup: Callable[[str, str], Dict[str, Any] | None],
    *,
    default_provider: str | None = None,
) -> int:
    """Price all attempts with one floor/minimum, preserving the old API."""
    return build_model_usage_breakdown(usage_by_model, pricing_lookup, default_provider=default_provider)["credits_charged"]


@dataclass
class ModelUsageTracker:
    """Track incurred usage independently from successful model identity.

    Legacy callers aggregate additive deltas by model. New callers supply an
    attempt ID and normalized final/cumulative usage so later snapshots replace
    earlier ones instead of being billed twice.
    """

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    last_successful_model_id: str | None = None
    _usage_by_model: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    _usage_by_attempt: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def record_reported_usage(
        self,
        *,
        model_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        user_input_tokens: int | None = None,
        system_prompt_tokens: int | None = None,
        normalized_usage: NormalizedLLMUsage | Mapping[str, Any] | None = None,
        attempt_id: str | None = None,
        usage_event_kind: str = "cumulative",
    ) -> None:
        """Record one provider event; attempt snapshots replace earlier ones."""
        if normalized_usage is not None:
            bucket = normalized_usage.to_bucket() if isinstance(normalized_usage, NormalizedLLMUsage) else dict(normalized_usage)
            bucket.setdefault("model_id", model_id)
            attempt_id = attempt_id or bucket.get("attempt_id")
        else:
            bucket = {
                "model_id": model_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "user_input_tokens": user_input_tokens or 0,
                "system_prompt_tokens": system_prompt_tokens or 0,
            }
        if not attempt_id:
            self.total_input_tokens += int(bucket.get("input_tokens") or 0)
            self.total_output_tokens += int(bucket.get("output_tokens") or 0)
            existing = self._usage_by_model.setdefault(model_id, {
                "model_id": model_id, "input_tokens": 0, "output_tokens": 0,
                "user_input_tokens": 0, "system_prompt_tokens": 0,
            })
            for key in ("input_tokens", "output_tokens", "user_input_tokens", "system_prompt_tokens"):
                existing[key] += int(bucket.get(key) or 0)
            return
        if usage_event_kind not in {"cumulative", "delta"}:
            raise ValueError("usage_event_kind must be cumulative or delta")
        bucket["attempt_id"] = attempt_id
        previous = self._usage_by_attempt.get(attempt_id)
        if previous and previous["model_id"] != model_id:
            raise ValueError("One attempt cannot switch model IDs")
        if previous and previous.get("inference_host") != bucket.get("inference_host"):
            raise ValueError("One attempt cannot switch inference hosts")
        if previous and previous.get("tariff_snapshot") != bucket.get("tariff_snapshot"):
            raise ValueError("One attempt cannot switch tariff snapshots")
        if previous and usage_event_kind == "delta":
            combined = dict(previous)
            for key in ("input_tokens", "uncached_input_tokens", "output_tokens", "user_input_tokens", "system_prompt_tokens",
                        "cache_read_input_tokens", "cache_creation_input_tokens", "cache_creation_5m_input_tokens", "cache_creation_1h_input_tokens"):
                old, new = previous.get(key), bucket.get(key)
                combined[key] = None if old is None or new is None else int(old) + int(new)
            if combined.get("cache_read_input_tokens") is None or combined.get("cache_creation_input_tokens") is None:
                # An unknown category absorbs the unknown share into ordinary
                # input; no reported discount/write is inferred from a delta.
                combined["uncached_input_tokens"] = (
                    int(combined.get("input_tokens") or 0)
                    - int(combined.get("cache_read_input_tokens") or 0)
                    - int(combined.get("cache_creation_input_tokens") or 0)
                )
            bucket = combined
        if previous and usage_event_kind == "cumulative":
            if int(bucket.get("input_tokens") or 0) < int(previous.get("input_tokens") or 0) or int(bucket.get("output_tokens") or 0) < int(previous.get("output_tokens") or 0):
                raise ValueError("Cumulative provider usage decreased within one attempt")
        self.total_input_tokens += int(bucket.get("input_tokens") or 0) - int(previous.get("input_tokens") or 0) if previous else int(bucket.get("input_tokens") or 0)
        self.total_output_tokens += int(bucket.get("output_tokens") or 0) - int(previous.get("output_tokens") or 0) if previous else int(bucket.get("output_tokens") or 0)
        self._usage_by_attempt[attempt_id] = bucket

    def mark_successful_model(self, model_id: str) -> None:
        self.last_successful_model_id = model_id

    @property
    def usage_by_model(self) -> list[Dict[str, Any]]:
        return [copy.deepcopy(bucket) for bucket in (*self._usage_by_model.values(), *self._usage_by_attempt.values())]

    def sentinel(self, *, tool_inference_iterations: int) -> Dict[str, Any]:
        return {
            "__cumulative_llm_usage__": True,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "tool_inference_iterations": tool_inference_iterations,
            "successful_model_id": self.last_successful_model_id,
            "usage_by_model": self.usage_by_model,
        }
