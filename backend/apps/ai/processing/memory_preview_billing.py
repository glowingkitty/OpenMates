# backend/apps/ai/processing/memory_preview_billing.py
#
# Charging for the memory update preview model request. The usage record holds
# token counts, model and the originating chat_id only - never memory or chat text.
# Spec: app-memories.suggestions.billing
# test-file: backend/tests/test_memory_update_preview.py, backend/tests/test_memory_create_draft.py

from typing import Any, Callable, Dict, List, Optional

from backend.apps.ai.processing.model_usage_tracker import build_model_usage_breakdown
from backend.apps.ai.processing.postprocessor import POSTPROCESSING_MODEL_ID


def priced_buckets(telemetry: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not telemetry:
        return []
    inp, out = telemetry.get("input_tokens"), telemetry.get("output_tokens")
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (inp, out)):
        return []
    return [{
        "model_id": telemetry.get("model_id") or POSTPROCESSING_MODEL_ID,
        "inference_host": telemetry.get("inference_host"),
        "input_tokens": inp, "output_tokens": out,
        "uncached_input_tokens": telemetry.get("uncached_input_tokens", inp),
        "cache_read_input_tokens": telemetry.get("cache_read_input_tokens"),
        "cache_creation_input_tokens": telemetry.get("cache_creation_input_tokens"),
    }]


async def charge_preview(billing: Any, pricing_lookup: Callable[[str, str], Any], *, user_id: str, user_id_hash: str, chat_id: str,
                         operation_id: str, buckets: List[Dict[str, Any]],
                         purpose: str = "memory_update_preview", message_id: Optional[str] = None) -> int:
    """Charge token usage to the chat. The record never contains memory or chat text.

    message_id: the turn's user message id (the id a chat turn's own usage row
    carries), so the charge also groups under that turn.
    """
    breakdown = build_model_usage_breakdown(buckets, pricing_lookup)
    credits = breakdown["credits_charged"]
    usage_details = {
        "chat_id": chat_id,
        "model_used": buckets[0]["model_id"],
        "input_tokens": breakdown["input_tokens"],
        "output_tokens": breakdown["output_tokens"],
        "purpose": purpose,
        "llm_usage_breakdown": breakdown,
    }
    if message_id:
        usage_details["message_id"] = message_id
    await billing.charge_user_credits(
        user_id=user_id, credits_to_deduct=credits, user_id_hash=user_id_hash,
        app_id="ai", skill_id=purpose, idempotency_key=operation_id,
        usage_details=usage_details,
    )
    return credits
