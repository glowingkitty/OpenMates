"""Provider-aware usage tracking for multi-iteration main-model calls."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Mapping

from backend.shared.python_utils.billing_utils import (
    calculate_credits_from_tokens,
    calculate_total_credits,
)


def calculate_model_usage_credits(
    usage_by_model: Iterable[Mapping[str, Any]],
    pricing_lookup: Callable[[str, str], Dict[str, Any] | None],
    *,
    default_provider: str | None = None,
) -> int:
    """Price all model buckets, applying the charge minimum/floor only once.

    Anonymous reservation checkpoints and terminal billing must use this same
    calculation. Rounding each attempt independently changes the final charge.
    """
    raw_credits = 0.0
    for bucket in usage_by_model:
        model_id = str(bucket["model_id"])
        if "/" in model_id:
            provider, suffix = model_id.split("/", 1)
        elif default_provider:
            provider, suffix = default_provider, model_id
        else:
            raise RuntimeError("Usage pricing requires a provider-qualified model ID")
        pricing = pricing_lookup(provider, suffix)
        if not pricing:
            raise RuntimeError(f"Pricing details for model '{model_id}' are not available")
        raw_credits += calculate_credits_from_tokens(
            int(bucket.get("input_tokens") or 0),
            int(bucket.get("output_tokens") or 0),
            pricing.get("pricing", pricing),
        )
    return calculate_total_credits(pricing_config={"fixed": raw_credits})


@dataclass
class ModelUsageTracker:
    """Track reported token usage separately from successful model identity."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    last_successful_model_id: str | None = None
    _usage_by_model: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def record_reported_usage(
        self,
        *,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        user_input_tokens: int | None = None,
        system_prompt_tokens: int | None = None,
    ) -> None:
        """Record incurred usage as soon as the provider reports it."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        bucket = self._usage_by_model.setdefault(
            model_id,
            {
                "model_id": model_id,
                "input_tokens": 0,
                "output_tokens": 0,
                "user_input_tokens": 0,
                "system_prompt_tokens": 0,
            },
        )
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["user_input_tokens"] += user_input_tokens or 0
        bucket["system_prompt_tokens"] += system_prompt_tokens or 0

    def mark_successful_model(self, model_id: str) -> None:
        """Record the model that successfully completed the latest iteration."""
        self.last_successful_model_id = model_id

    @property
    def usage_by_model(self) -> list[Dict[str, Any]]:
        """Return a snapshot suitable for pricing without exposing mutable state."""
        return [dict(bucket) for bucket in self._usage_by_model.values()]

    def sentinel(self, *, tool_inference_iterations: int) -> Dict[str, Any]:
        """Return the immutable handoff consumed by final billing."""
        return {
            "__cumulative_llm_usage__": True,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "tool_inference_iterations": tool_inference_iterations,
            "successful_model_id": self.last_successful_model_id,
            "usage_by_model": self.usage_by_model,
        }
