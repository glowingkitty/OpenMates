"""Metered billing of images.modify (assertion images-modify.billing.metered).

A delivered picture costs the reported tokens of every author and review call
at that model's price plus 5 credits per started minute of each sandbox run
(the Code Run price). The arithmetic is shared with other author-plus-sandbox
skills in ``backend.shared.python_utils.metered_author_billing``. A request
without a delivered picture is never charged: the task calls
``charge_modify_credits`` only after the result is stored.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from backend.apps.images.vector_author import VectorUsage
from backend.shared.python_utils.metered_author_billing import (
    PricingLookup,
    SANDBOX_MODEL_REF,
    author_and_sandbox_credits,
    estimate_author_and_sandbox_credits,
    fetch_model_pricing,
    post_skill_charge,
)

__all__ = ["SANDBOX_MODEL_REF", "charge_modify_credits", "estimate_modify_credits", "fetch_model_pricing",
           "modify_credits"]

LABEL = "images.modify"
# Balance check before work starts: one author call over the request and its pictures, one sandbox minute.
ESTIMATE_BASE_INPUT_TOKENS = 2_500
ESTIMATE_INPUT_TOKENS_PER_PICTURE = 1_100
ESTIMATE_OUTPUT_TOKENS = 2_500
ESTIMATE_SANDBOX_SECONDS = 60


async def modify_credits(
    *, usage: Sequence[VectorUsage], sandbox_seconds: Sequence[float], pricing_for: Optional[PricingLookup] = None,
) -> tuple[int, dict[str, Any]]:
    """Credits of one delivered picture and the usage details recorded with the charge."""
    return await author_and_sandbox_credits(usage=usage, sandbox_seconds=sandbox_seconds, label=LABEL,
                                            pricing_for=pricing_for)


async def estimate_modify_credits(
    *, picture_count: int, author_model: str, pricing_for: Optional[PricingLookup] = None,
) -> int:
    """Estimate for the balance check before any model or sandbox is used."""
    return await estimate_author_and_sandbox_credits(
        author_model=author_model,
        input_tokens=ESTIMATE_BASE_INPUT_TOKENS + ESTIMATE_INPUT_TOKENS_PER_PICTURE * max(1, picture_count),
        output_tokens=ESTIMATE_OUTPUT_TOKENS, sandbox_seconds=ESTIMATE_SANDBOX_SECONDS, label=LABEL,
        pricing_for=pricing_for,
    )


async def charge_modify_credits(
    *, user_id: str, user_id_hash: str, app_id: str, skill_id: str, credits: int, usage_details: dict[str, Any],
    model_ref: str, chat_id: Any, message_id: Any, team_id: Optional[str], api_key_hash: Optional[str],
    device_hash: Optional[str], event_id: str,
) -> None:
    """Record the charge through the internal billing route; raise ``httpx.HTTPError`` on failure."""
    if credits <= 0:
        return
    payload = {
        "user_id": user_id,
        "user_id_hash": user_id_hash,
        "credits": credits,
        "skill_id": skill_id,
        "app_id": app_id,
        "api_key_hash": api_key_hash,
        "device_hash": device_hash,
        "usage_details": {
            "chat_id": chat_id,
            "message_id": message_id,
            "units_processed": 1,
            "unit_name": "image",
            "model_used": model_ref,
            **usage_details,
        },
    }
    await post_skill_charge(payload, team_id=team_id, event_id=event_id)
