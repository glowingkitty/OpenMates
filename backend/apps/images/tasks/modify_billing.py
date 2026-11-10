"""Metered billing of images.modify (assertion images-modify.billing.metered).

A delivered picture costs the reported tokens of every author and review call
at that model's price plus 5 credits per started minute of each sandbox run
(``vector_script.script_run_credits``, the Code Run price). Fractional token
credits are summed and floored once, so several small calls are not each
rounded up; the platform minimum applies. A call without usage or without a
price is an error, never free. A request without a delivered picture is never
charged: the task calls ``charge_modify_credits`` only after the result is stored.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Awaitable, Callable, Optional, Sequence

import httpx

from backend.apps.images.vector_author import VectorUsage
from backend.apps.images.vector_script import script_run_credits
from backend.shared.python_utils.billing_utils import MINIMUM_CREDITS_CHARGED, calculate_credits_from_tokens

logger = logging.getLogger(__name__)

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
SANDBOX_MODEL_REF = "e2b/sandbox"
# Balance check before work starts: one author call over the request and its pictures, one sandbox minute.
ESTIMATE_BASE_INPUT_TOKENS = 2_500
ESTIMATE_INPUT_TOKENS_PER_PICTURE = 1_100
ESTIMATE_OUTPUT_TOKENS = 2_500
ESTIMATE_SANDBOX_SECONDS = 60

PricingLookup = Callable[[str], Awaitable[Optional[dict[str, Any]]]]


def _internal_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if token:
        headers["X-Internal-Service-Token"] = token
    return headers


async def fetch_model_pricing(model_ref: str) -> Optional[dict[str, Any]]:
    """Read one provider model's pricing from the internal config endpoint."""
    if "/" not in model_ref:
        return None
    provider_id, model_suffix = model_ref.split("/", 1)
    url = f"{INTERNAL_API_BASE_URL}/internal/config/provider_model_pricing/{provider_id}/{model_suffix}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=_internal_headers())
    if response.status_code != 200:
        logger.warning("Modify pricing lookup for %s failed: HTTP %s", model_ref, response.status_code)
        return None
    return response.json()


def _token_rules(pricing_config: Optional[dict[str, Any]], model_id: str) -> dict[str, Any]:
    rules = (pricing_config or {}).get("pricing", pricing_config)
    if not rules or "tokens" not in rules:
        raise RuntimeError(f"No token pricing for images.modify model {model_id}")
    return rules


async def modify_credits(
    *, usage: Sequence[VectorUsage], sandbox_seconds: Sequence[float], pricing_for: Optional[PricingLookup] = None,
) -> tuple[int, dict[str, Any]]:
    """Credits of one delivered picture and the usage details recorded with the charge."""
    lookup = pricing_for or fetch_model_pricing
    rules_by_model: dict[str, dict[str, Any]] = {}
    raw_token_credits = 0.0
    steps: list[dict[str, Any]] = []
    for entry in usage:
        if entry.input_tokens + entry.output_tokens <= 0:
            raise RuntimeError(f"images.modify call '{entry.step}' on {entry.model_id} reported no token usage")
        if entry.model_id not in rules_by_model:
            rules_by_model[entry.model_id] = _token_rules(await lookup(entry.model_id), entry.model_id)
        step_credits = calculate_credits_from_tokens(entry.input_tokens, entry.output_tokens,
                                                     rules_by_model[entry.model_id])
        raw_token_credits += step_credits
        steps.append({"step": entry.step, "model_used": entry.model_id, "input_tokens": entry.input_tokens,
                      "output_tokens": entry.output_tokens, "credits": round(step_credits, 4)})
    sandbox_credits = 0
    for seconds in sandbox_seconds:
        run_credits = script_run_credits(seconds)
        sandbox_credits += run_credits
        steps.append({"step": "sandbox_run", "model_used": SANDBOX_MODEL_REF, "duration_seconds": round(seconds, 2),
                      "credits": run_credits})
    token_credits = math.floor(raw_token_credits)
    if raw_token_credits > 0 and token_credits == 0:
        token_credits = MINIMUM_CREDITS_CHARGED
    details = {
        "input_tokens": sum(entry.input_tokens for entry in usage),
        "output_tokens": sum(entry.output_tokens for entry in usage),
        "sandbox_runs": len(sandbox_seconds),
        "provider_calls": steps,
    }
    return max(MINIMUM_CREDITS_CHARGED, token_credits + sandbox_credits), details


async def estimate_modify_credits(
    *, picture_count: int, author_model: str, pricing_for: Optional[PricingLookup] = None,
) -> int:
    """Estimate for the balance check before any model or sandbox is used."""
    rules = _token_rules(await (pricing_for or fetch_model_pricing)(author_model), author_model)
    input_tokens = ESTIMATE_BASE_INPUT_TOKENS + ESTIMATE_INPUT_TOKENS_PER_PICTURE * max(1, picture_count)
    tokens = math.ceil(calculate_credits_from_tokens(input_tokens, ESTIMATE_OUTPUT_TOKENS, rules))
    return max(MINIMUM_CREDITS_CHARGED, tokens + script_run_credits(ESTIMATE_SANDBOX_SECONDS))


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
    from backend.shared.python_utils.team_skill_billing import skill_billing_request

    billing_path, payload = skill_billing_request(payload, team_id, event_id=event_id)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{INTERNAL_API_BASE_URL}{billing_path}", json=payload, headers=_internal_headers())
        response.raise_for_status()
