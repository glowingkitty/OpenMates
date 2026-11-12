"""Metered billing of author-model plus sandbox work (images.modify, videos.generate composed).

A delivered result costs the reported tokens of every author (and review) call
at that model's price plus 5 credits per started minute of each sandbox run
(the Code Run price, backend/apps/code/app.yml ``code.run`` pricing.per_minute).
Fractional token credits are summed and floored once, so several small calls
are not each rounded up; the platform minimum applies. A call without usage or
without a price is an error, never free.

A usage record is any object with ``input_tokens`` and ``output_tokens`` and a
model reference as ``model_id`` (``provider/model``) or as ``model`` plus
``provider``; ``step`` names the call when present.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Awaitable, Callable, Optional, Sequence

import httpx

from backend.shared.python_utils.billing_utils import MINIMUM_CREDITS_CHARGED, calculate_credits_from_tokens

logger = logging.getLogger(__name__)

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
SANDBOX_CREDITS_PER_STARTED_MINUTE = 5
SANDBOX_MODEL_REF = "e2b/sandbox"

PricingLookup = Callable[[str], Awaitable[Optional[dict[str, Any]]]]


def internal_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if token:
        headers["X-Internal-Service-Token"] = token
    return headers


def sandbox_run_credits(seconds: float) -> int:
    """Credits for one sandbox run: every started minute is charged, a run that never started is free."""
    if seconds <= 0:
        return 0
    return math.ceil(seconds / 60) * SANDBOX_CREDITS_PER_STARTED_MINUTE


async def fetch_model_pricing(model_ref: str) -> Optional[dict[str, Any]]:
    """Read one provider model's pricing from the internal config endpoint."""
    if "/" not in model_ref:
        return None
    provider_id, model_suffix = model_ref.split("/", 1)
    url = f"{INTERNAL_API_BASE_URL}/internal/config/provider_model_pricing/{provider_id}/{model_suffix}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=internal_headers())
    if response.status_code != 200:
        logger.warning("Pricing lookup for %s failed: HTTP %s", model_ref, response.status_code)
        return None
    return response.json()


def token_rules(pricing_config: Optional[dict[str, Any]], model_id: str, *, label: str) -> dict[str, Any]:
    rules = (pricing_config or {}).get("pricing", pricing_config)
    if not rules or "tokens" not in rules:
        raise RuntimeError(f"No token pricing for {label} model {model_id}")
    return rules


def usage_model_ref(entry: Any) -> str:
    """``provider/model`` of one usage record; raise when the record names no model."""
    model_id = getattr(entry, "model_id", None)
    if isinstance(model_id, str) and model_id:
        return model_id
    model = getattr(entry, "model", None)
    provider = getattr(entry, "provider", None)
    if isinstance(model, str) and model:
        if "/" in model or not isinstance(provider, str) or not provider:
            return model
        return f"{provider}/{model}"
    raise RuntimeError("a usage record names no model")


async def author_and_sandbox_credits(
    *, usage: Sequence[Any], sandbox_seconds: Sequence[float], label: str,
    pricing_for: Optional[PricingLookup] = None,
) -> tuple[int, dict[str, Any]]:
    """Credits of one delivered result and the usage details recorded with the charge."""
    lookup = pricing_for or fetch_model_pricing
    rules_by_model: dict[str, dict[str, Any]] = {}
    raw_token_credits = 0.0
    steps: list[dict[str, Any]] = []
    for entry in usage:
        model_ref = usage_model_ref(entry)
        step = str(getattr(entry, "step", "") or "author")
        if entry.input_tokens + entry.output_tokens <= 0:
            raise RuntimeError(f"{label} call '{step}' on {model_ref} reported no token usage")
        if model_ref not in rules_by_model:
            rules_by_model[model_ref] = token_rules(await lookup(model_ref), model_ref, label=label)
        step_credits = calculate_credits_from_tokens(entry.input_tokens, entry.output_tokens,
                                                     rules_by_model[model_ref])
        raw_token_credits += step_credits
        steps.append({"step": step, "model_used": model_ref, "input_tokens": entry.input_tokens,
                      "output_tokens": entry.output_tokens, "credits": round(step_credits, 4)})
    sandbox_credits = 0
    for seconds in sandbox_seconds:
        run_credits = sandbox_run_credits(seconds)
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


async def estimate_author_and_sandbox_credits(
    *, author_model: str, input_tokens: int, output_tokens: int, sandbox_seconds: float, label: str,
    pricing_for: Optional[PricingLookup] = None,
) -> int:
    """Estimate for the balance check before any model or sandbox is used."""
    rules = token_rules(await (pricing_for or fetch_model_pricing)(author_model), author_model, label=label)
    tokens = math.ceil(calculate_credits_from_tokens(input_tokens, output_tokens, rules))
    return max(MINIMUM_CREDITS_CHARGED, tokens + sandbox_run_credits(sandbox_seconds))


async def post_skill_charge(payload: dict[str, Any], *, team_id: Optional[str], event_id: str) -> None:
    """Record one skill charge through the internal billing route; raise ``httpx.HTTPError`` on failure."""
    from backend.shared.python_utils.team_skill_billing import skill_billing_request

    billing_path, payload = skill_billing_request(payload, team_id, event_id=event_id)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{INTERNAL_API_BASE_URL}{billing_path}", json=payload,
                                     headers=internal_headers())
        response.raise_for_status()
