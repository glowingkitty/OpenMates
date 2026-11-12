"""Billing of videos.generate results (assertion videos-generate.billing.metered).

A generative clip costs its measured seconds at the model's per-resolution
provider price times the generated-media markup (``omni_clip_pricing``). A
delivered composed video costs the reported tokens of every author call at
that model's price plus 5 credits per started minute of each sandbox render
(the Code Run price), computed by the shared author-plus-sandbox helpers. A
request without a delivered video is never charged: the pipeline charges only
after the video is stored, once, with the result embed id as the event id.
A change of a video (a new version) is charged once under its own version
event id for exactly what it used: the added clip, an opening still, author
calls and the sandbox render of the join (``generate_change``).
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from backend.shared.python_utils.catalog_unit_prices import skill_price, whole_credits
from backend.shared.python_utils.cost_plus_pricing import credits_for_cost, load_pricing_settings
from backend.shared.python_utils.metered_author_billing import (
    PricingLookup,
    author_and_sandbox_credits,
    estimate_author_and_sandbox_credits,
    post_skill_charge,
)

# Catalog price per started sandbox minute (videos.generate pricing.per_minute).
COMPOSED_SANDBOX_CREDITS_PER_STARTED_MINUTE = whole_credits(skill_price("videos", "generate", "per_minute"))
LABEL = "videos.generate composed"
# Gemini Omni (gemini-omni-1.2-flash) provider price per generated second by output resolution; source and
# date in backend/providers/google.yml costs.output_per_second (backend/tests/test_video_generation_pricing.py
# keeps both equal).
OMNI_PRICE_USD_PER_SECOND = {"360p": 0.023, "720p": 0.07, "1080p": 0.104, "4k": 0.209}


def omni_clip_pricing(resolution: str) -> tuple[float, dict[str, dict[str, Any]]]:
    """Provider price per second and the per-second credit config of a Gemini Omni clip."""
    price = OMNI_PRICE_USD_PER_SECOND.get(resolution)
    if price is None:
        raise ValueError(f"no Gemini Omni price for resolution {resolution!r}")
    return price, video_second_pricing(price)


def video_second_pricing(usd_per_second: float) -> dict[str, dict[str, Any]]:
    """Per-second credit config: supplier price plus the configured margin, rounded up to 5-credit steps."""
    credits = float(credits_for_cost(usd_per_second, load_pricing_settings(), per_call=False))
    return {"per_second": {"credits": credits, "unit_name": "video_second"}}


def omni_clip_credits(resolution: str, duration_seconds: float) -> int:
    from backend.shared.python_utils.billing_utils import calculate_total_credits

    return calculate_total_credits(pricing_config=omni_clip_pricing(resolution)[1], duration_seconds=duration_seconds)
# Balance check before work starts: one author call over the request and its pictures, two render minutes.
ESTIMATE_BASE_INPUT_TOKENS = 6_000
ESTIMATE_INPUT_TOKENS_PER_PICTURE = 1_100
ESTIMATE_OUTPUT_TOKENS = 6_000
ESTIMATE_SANDBOX_SECONDS = 120


async def composed_credits(
    *, usage: Sequence[Any], sandbox_seconds: Sequence[float], pricing_for: Optional[PricingLookup] = None,
) -> tuple[int, dict[str, Any]]:
    """Credits of one delivered composed video and the usage details recorded with the charge."""
    return await author_and_sandbox_credits(usage=usage, sandbox_seconds=sandbox_seconds, label=LABEL,
                                            sandbox_credits_per_started_minute=COMPOSED_SANDBOX_CREDITS_PER_STARTED_MINUTE, pricing_for=pricing_for)


async def estimate_composed_credits(
    *, picture_count: int, author_model: str, pricing_for: Optional[PricingLookup] = None,
) -> int:
    """Estimate for the balance check before any author model or sandbox is used."""
    return await estimate_author_and_sandbox_credits(
        author_model=author_model,
        input_tokens=ESTIMATE_BASE_INPUT_TOKENS + ESTIMATE_INPUT_TOKENS_PER_PICTURE * picture_count,
        output_tokens=ESTIMATE_OUTPUT_TOKENS, sandbox_seconds=ESTIMATE_SANDBOX_SECONDS, label=LABEL,
        sandbox_credits_per_started_minute=COMPOSED_SANDBOX_CREDITS_PER_STARTED_MINUTE, pricing_for=pricing_for,
    )


async def charge_composed_credits(
    *, user_id: str, user_id_hash: str, app_id: str, skill_id: str, credits: int, usage_details: dict[str, Any],
    model_ref: str, chat_id: Any, message_id: Any, team_id: Optional[str], api_key_hash: Optional[str],
    device_hash: Optional[str], duration_seconds: float, event_id: str,
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
            "unit_name": "composed_video",
            "duration_seconds": duration_seconds,
            "model_used": model_ref,
            **usage_details,
        },
    }
    await post_skill_charge(payload, team_id=team_id, event_id=event_id)
