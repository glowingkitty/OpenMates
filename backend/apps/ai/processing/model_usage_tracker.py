"""Provider-aware usage tracking for multi-iteration main-model calls."""

from dataclasses import dataclass, field
from typing import Any, Dict


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

    def sentinel(self, *, tool_inference_iterations: int) -> Dict[str, Any]:
        """Return the immutable handoff consumed by final billing."""
        return {
            "__cumulative_llm_usage__": True,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "tool_inference_iterations": tool_inference_iterations,
            "successful_model_id": self.last_successful_model_id,
            "usage_by_model": [dict(bucket) for bucket in self._usage_by_model.values()],
        }
