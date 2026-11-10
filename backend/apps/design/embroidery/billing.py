"""Metered billing for design.embroidery (assertion design-embroidery.billing.metered).

A conversion costs the Code Run price per started sandbox minute plus, when a
model reworked the graphic, that call's reported tokens at the model's price.
Fractional token credits are summed and floored once, like the images vector
author. The task charges only after its files are stored; a failed conversion
is never charged.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Awaitable, Callable, Sequence

import httpx

from backend.apps.images.vector_script import script_run_credits
from backend.apps.images.vector_author import VectorUsage
from backend.shared.python_utils.billing_utils import MINIMUM_CREDITS_CHARGED, calculate_credits_from_tokens

logger = logging.getLogger(__name__)

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
SANDBOX_MODEL_REF = "e2b/sandbox"
# Balance check before work starts; the sandbox stops after 180 s (3 started minutes).
MAX_SANDBOX_SECONDS = 180
REWORK_ESTIMATE_OUTPUT_TOKENS = 8_000

PricingLookup = Callable[[str], Awaitable[dict[str, Any] | None]]


def _internal_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if token:
        headers["X-Internal-Service-Token"] = token
    return headers


async def fetch_model_pricing(model_ref: str) -> dict[str, Any] | None:
    """Read one provider model's pricing from the internal config endpoint."""
    if "/" not in model_ref:
        return None
    provider_id, model_suffix = model_ref.split("/", 1)
    url = f"{INTERNAL_API_BASE_URL}/internal/config/provider_model_pricing/{provider_id}/{model_suffix}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=_internal_headers())
    if response.status_code != 200:
        logger.warning("Embroidery pricing lookup for %s failed: HTTP %s", model_ref, response.status_code)
        return None
    return response.json()


def _token_rules(pricing_config: dict[str, Any] | None, model_id: str) -> dict[str, Any]:
    rules = (pricing_config or {}).get("pricing", pricing_config)
    if not rules or "tokens" not in rules:
        raise RuntimeError(f"No token pricing for embroidery rework model {model_id}")
    return rules


async def embroidery_credits(
    *, sandbox_seconds: float, usage: Sequence[VectorUsage], pricing_for: PricingLookup | None = None,
) -> tuple[int, dict[str, Any]]:
    """Return the credits for one delivered conversion and the usage details recorded with them.

    A rework call without reported tokens or without a price is an error, never free.
    """
    lookup = pricing_for or fetch_model_pricing
    raw_token_credits = 0.0
    steps: list[dict[str, Any]] = []
    pricing_cache: dict[str, dict[str, Any]] = {}
    for entry in usage:
        if entry.input_tokens + entry.output_tokens <= 0:
            raise RuntimeError(f"Embroidery rework call on {entry.model_id} reported no token usage")
        if entry.model_id not in pricing_cache:
            pricing_cache[entry.model_id] = _token_rules(await lookup(entry.model_id), entry.model_id)
        step_credits = calculate_credits_from_tokens(entry.input_tokens, entry.output_tokens, pricing_cache[entry.model_id])
        raw_token_credits += step_credits
        steps.append({"step": "embroidery_rework", "model_used": entry.model_id, "input_tokens": entry.input_tokens,
                      "output_tokens": entry.output_tokens, "credits": round(step_credits, 4)})
    sandbox_credits = script_run_credits(sandbox_seconds)
    steps.append({"step": "embroidery_sandbox", "model_used": SANDBOX_MODEL_REF,
                  "duration_seconds": round(sandbox_seconds, 2), "credits": sandbox_credits})
    token_credits = math.floor(raw_token_credits)
    if raw_token_credits > 0 and token_credits == 0:
        token_credits = MINIMUM_CREDITS_CHARGED
    details = {
        "input_tokens": sum(entry.input_tokens for entry in usage),
        "output_tokens": sum(entry.output_tokens for entry in usage),
        "provider_calls": steps,
    }
    return max(MINIMUM_CREDITS_CHARGED, sandbox_credits + token_credits), details


async def estimate_embroidery_credits(
    *, svg_chars: int, rework_possible: bool, rework_model: str, pricing_for: PricingLookup | None = None,
) -> int:
    """Upper estimate for the balance check: a full sandbox run plus one rework when one may run."""
    estimate = script_run_credits(MAX_SANDBOX_SECONDS)
    if rework_possible:
        rules = _token_rules(await (pricing_for or fetch_model_pricing)(rework_model), rework_model)
        input_tokens = svg_chars // 3 + 1_500
        estimate += math.ceil(calculate_credits_from_tokens(input_tokens, REWORK_ESTIMATE_OUTPUT_TOKENS, rules))
    return estimate


async def charge_embroidery_credits(
    *,
    user_id: str,
    user_id_hash: str,
    app_id: str,
    skill_id: str,
    credits: int,
    usage_details: dict[str, Any],
    chat_id: Any,
    message_id: Any,
    api_key_hash: str | None,
    device_hash: str | None,
    event_id: str,
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
            "unit_name": "embroidery_design",
            "model_used": SANDBOX_MODEL_REF,
            "server_provider": "E2B",
            "server_region": "global",
            **usage_details,
        },
    }
    from backend.shared.python_utils.team_skill_billing import skill_billing_request
    billing_path, payload = skill_billing_request(payload, None, event_id=event_id)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{INTERNAL_API_BASE_URL}{billing_path}", json=payload, headers=_internal_headers())
        response.raise_for_status()
