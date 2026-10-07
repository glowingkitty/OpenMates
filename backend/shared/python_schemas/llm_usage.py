"""Provider-neutral, non-overlapping token usage for one LLM invocation.

Provider cache counters are optional: an absent counter is not a reported zero.
Only reported cache writes may be billed as writes. The legacy input count is
retained while cache tariffs are inactive, especially for Anthropic's exclusive
``input_tokens`` counter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def _field(value: Any, *names: str) -> Any:
    for name in names:
        if isinstance(value, Mapping):
            if name in value:
                return value[name]
        elif hasattr(value, name):
            return getattr(value, name)
    return None


def _count(value: Any, name: str, *, required: bool = False) -> int | None:
    if value is None:
        if required:
            raise ValueError(f"Provider usage is missing {name}")
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Provider usage {name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class NormalizedLLMUsage:
    model_id: str
    input_total: int
    input_uncached: int
    output_billable: int
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_creation_5m_input_tokens: int | None = None
    cache_creation_1h_input_tokens: int | None = None
    output_reasoning_tokens: int | None = None
    legacy_billable_input_tokens: int | None = None
    legacy_billable_output_tokens: int | None = None
    usage_source: str = "provider_reported"
    provider_kind: str | None = None
    attempt_id: str | None = None
    inference_host: str | None = None
    region: str | None = None
    provider_request_id: str | None = None
    tariff_snapshot: Mapping[str, Any] | None = None
    user_input_tokens: int | None = None
    system_prompt_tokens: int | None = None

    def to_bucket(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "input_tokens": self.input_total,
            "uncached_input_tokens": self.input_uncached,
            "output_tokens": self.output_billable,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_creation_5m_input_tokens": self.cache_creation_5m_input_tokens,
            "cache_creation_1h_input_tokens": self.cache_creation_1h_input_tokens,
            "output_reasoning_tokens": self.output_reasoning_tokens,
            "legacy_billable_input_tokens": self.legacy_billable_input_tokens,
            "legacy_billable_output_tokens": self.legacy_billable_output_tokens,
            "usage_source": self.usage_source,
            "provider_kind": self.provider_kind,
            "attempt_id": self.attempt_id,
            "inference_host": self.inference_host,
            "region": self.region,
            "provider_request_id": self.provider_request_id,
            "tariff_snapshot": dict(self.tariff_snapshot) if self.tariff_snapshot else None,
            "user_input_tokens": self.user_input_tokens,
            "system_prompt_tokens": self.system_prompt_tokens,
        }


def normalize_provider_usage(
    usage: Any,
    *,
    model_id: str,
    provider_kind: str | None = None,
    attempt_id: str | None = None,
    inference_host: str | None = None,
    region: str | None = None,
    provider_request_id: str | None = None,
    tariff_snapshot: Mapping[str, Any] | None = None,
) -> NormalizedLLMUsage:
    """Normalize one provider's final usage into disjoint input categories.

    Anthropic and Bedrock native input counters exclude cache reads/writes.
    Google/OpenAI/Mistral prompt counters include cache reads and writes. Google
    candidate output excludes separately reported thoughts, whereas other
    providers' output counts already include billable reasoning.
    """
    if not model_id:
        raise ValueError("model_id is required")
    kind = (provider_kind or _field(usage, "provider_kind") or "").lower()
    if not kind:
        class_name = type(usage).__name__.lower()
        kind = next((name for name in ("bedrock", "anthropic", "google", "openai", "mistral") if name in class_name), "")
    if not kind:
        kind = model_id.split("/", 1)[0].lower()
    kind = next((name for name in ("bedrock", "anthropic", "google", "openai", "mistral") if name in kind), kind)

    native_input = _count(
        _field(usage, "prompt_token_count") if kind == "google" else
        _field(usage, "prompt_tokens", "input_tokens") if kind == "mistral" else
        _field(usage, "input_tokens", "prompt_tokens"),
        "input_tokens", required=kind != "google",
    )
    google_input_missing = kind == "google" and native_input is None
    if native_input is None:
        native_input = 0  # Preserve Google's previous optional-count behavior.
    output = _count(
        _field(usage, "candidates_token_count") if kind == "google" else
        _field(usage, "completion_tokens", "output_tokens") if kind == "mistral" else
        _field(usage, "output_tokens", "completion_tokens"),
        "output_tokens", required=kind != "google",
    )
    thoughts = _count(_field(usage, "thoughts_token_count"), "thoughts_token_count") if kind == "google" else None
    google_output_estimated = False
    if output is None:
        reported_total = _count(_field(usage, "total_token_count"), "total_token_count")
        # Google totals include prompt, candidates and thoughts. This equality
        # proves zero candidates without treating every absent counter as zero.
        proven_zero_candidates = (
            kind == "google" and not google_input_missing and thoughts is not None
            and reported_total is not None and reported_total == native_input + thoughts
        )
        output = 0  # Legacy behavior for optional Google candidate counts.
        google_output_estimated = not proven_zero_candidates
    native_output = output
    if thoughts is not None:
        output += thoughts

    read = _count(_field(usage, "cache_read_input_tokens", "cached_content_token_count", "cached_tokens"), "cache_read_input_tokens")
    write = _count(_field(usage, "cache_creation_input_tokens"), "cache_creation_input_tokens")
    write_5m = _count(_field(usage, "cache_creation_5m_input_tokens"), "cache_creation_5m_input_tokens")
    write_1h = _count(_field(usage, "cache_creation_1h_input_tokens"), "cache_creation_1h_input_tokens")
    if google_input_missing:
        # A missing inclusive prompt count has no safe partition denominator.
        # Preserve provider-reported raw metadata on the native response; the
        # normalized billable categories remain unknown, not invented zeros.
        read = write = write_5m = write_1h = None
    if write is None and (write_5m is not None or write_1h is not None):
        write = (write_5m or 0) + (write_1h or 0)
    if write is not None and (write_5m or 0) + (write_1h or 0) > write:
        raise ValueError("Cache write retention subtotals exceed total cache writes")

    exclusive = kind in {"anthropic", "bedrock"}
    if exclusive:
        total = native_input + (read or 0) + (write or 0)
        uncached = native_input
    else:
        total = native_input
        uncached = total - (read or 0) - (write or 0)
        if uncached < 0:
            raise ValueError("Cache read/write tokens exceed inclusive provider input tokens")

    usage_source = _field(usage, "usage_source") or "provider_reported"
    if google_input_missing or google_output_estimated:
        usage_source = "estimated"
    if usage_source not in {"provider_reported", "estimated"}:
        raise ValueError("usage_source must be provider_reported or estimated")
    return NormalizedLLMUsage(
        model_id=model_id,
        input_total=total,
        input_uncached=uncached,
        output_billable=output,
        cache_read_input_tokens=read,
        cache_creation_input_tokens=write,
        cache_creation_5m_input_tokens=write_5m,
        cache_creation_1h_input_tokens=write_1h,
        output_reasoning_tokens=thoughts if kind == "google" else _count(_field(usage, "reasoning_tokens"), "reasoning_tokens"),
        legacy_billable_input_tokens=native_input,
        legacy_billable_output_tokens=native_output,
        usage_source=usage_source,
        provider_kind=kind,
        attempt_id=attempt_id or _field(usage, "attempt_id"),
        inference_host=inference_host or _field(usage, "inference_host"),
        region=region or _field(usage, "region"),
        provider_request_id=provider_request_id or _field(usage, "provider_request_id"),
        tariff_snapshot=tariff_snapshot,
        user_input_tokens=_count(_field(usage, "user_input_tokens"), "user_input_tokens"),
        system_prompt_tokens=_count(_field(usage, "system_prompt_tokens"), "system_prompt_tokens"),
    )
