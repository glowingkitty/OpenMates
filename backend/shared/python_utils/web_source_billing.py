"""Usage-based credits of a search skill that reads public web pages (events.search).

A successful request group costs what it used, at the platform's regular prices:
- each answered web search request at the search provider's per-request price
  (backend/providers/brave.yml ``pricing.per_request_credits``), and
- the extraction model's input and output tokens at that model's token price
  (backend/providers/<provider>.yml, temporary tariffs such as a launch price
  included; resolved by the internal pricing route).
Fractional token credits are added to the request credits and floored once.
A successful group that used neither (an official schedule or an installed
provider answered alone) costs the platform minimum of 1 credit. A group with an
error or without results costs nothing. Groups served only by operator-installed
providers are exempt per the server's registry (backend/shared/app_packages/billing.py),
whatever the skill output says.

Prices are loaded before the web is searched; when they cannot be loaded the web
is not searched (a warning of that request), so no unpriced usage happens.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import httpx

from backend.shared.python_utils.billing_utils import MINIMUM_CREDITS_CHARGED, calculate_credits_from_tokens
from backend.shared.python_utils.metered_author_billing import (
    INTERNAL_API_BASE_URL, fetch_model_pricing, internal_headers,
)

logger = logging.getLogger(__name__)

SEARCH_PROVIDER_ID = "brave"
EVENTS_SEARCH = ("events", "search")
# Upper bound reserved per request item before the search runs: one web search
# request (10 credits) plus 5 pages of up to ~10k input and 4k output tokens at
# Mercury 3's regular price (~15 + ~21 credits), rounded up. The charge itself
# is the actual usage, usually 15-25 credits.
RESERVED_CREDITS_PER_REQUEST = 50

Lookup = Callable[[str], Awaitable[Optional[Dict[str, Any]]]]


class WebSourcePricingError(RuntimeError):
    """The web search or extraction model price could not be loaded."""


@dataclass(frozen=True)
class WebSourcePrices:
    """Prices of one web source run: credits per search request and the extraction model's token rules."""
    search_request_credits: int
    model: str
    token_rules: Mapping[str, Any]


async def fetch_provider_pricing(provider_id: str) -> Optional[Dict[str, Any]]:
    """Provider-level pricing (``pricing`` block of backend/providers/<id>.yml) from the internal config route."""
    url = f"{INTERNAL_API_BASE_URL}/internal/config/provider_pricing/{provider_id}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=internal_headers())
    if response.status_code != 200:
        logger.warning("Provider pricing lookup for %s failed: HTTP %s", provider_id, response.status_code)
        return None
    return response.json()


async def fetch_web_source_prices(model: str, *, provider_pricing: Optional[Lookup] = None,
                                  model_pricing: Optional[Lookup] = None) -> WebSourcePrices:
    """Current prices for searching the web and extracting with ``model`` (``provider/model``)."""
    try:
        search = await (provider_pricing or fetch_provider_pricing)(SEARCH_PROVIDER_ID)
        rules = await (model_pricing or fetch_model_pricing)(model)
    except httpx.HTTPError as exc:
        raise WebSourcePricingError(f"pricing lookup failed: {type(exc).__name__}") from exc
    per_request = (search or {}).get("per_request_credits")
    if not isinstance(per_request, int) or isinstance(per_request, bool) or per_request <= 0:
        raise WebSourcePricingError("no per-request price for web search")
    rules = (rules or {}).get("pricing", rules)
    if not isinstance(rules, dict) or not isinstance(rules.get("tokens"), dict):
        raise WebSourcePricingError(f"no token price for {model}")
    return WebSourcePrices(search_request_credits=per_request, model=model, token_rules=rules)


def raw_web_credits(usage: Optional[Mapping[str, Any]], prices: Optional[WebSourcePrices]) -> float:
    """Unrounded credits of one web source run (0 when it used nothing)."""
    if not usage or prices is None:
        return 0.0
    requests = int(usage.get("web_search_requests") or 0)
    tokens_in = int(usage.get("input_tokens") or 0)
    tokens_out = int(usage.get("output_tokens") or 0)
    return requests * prices.search_request_credits + calculate_credits_from_tokens(
        tokens_in, tokens_out, prices.token_rules)


def group_usage(*, has_results: bool, failed: bool, web: Optional[Mapping[str, Any]],
                prices: Optional[WebSourcePrices]) -> Dict[str, Any]:
    """``usage`` of one request group: its credits plus what the web source used."""
    usage: Dict[str, Any] = {"credits_charged": 0}
    if web:
        usage.update({"web_search_requests": int(web.get("web_search_requests") or 0),
                      "input_tokens": int(web.get("input_tokens") or 0),
                      "output_tokens": int(web.get("output_tokens") or 0)})
        if web.get("model"):
            usage["model"] = web["model"]
    if failed or not has_results:
        return usage
    usage["credits_charged"] = max(MINIMUM_CREDITS_CHARGED, math.floor(raw_web_credits(web, prices)))
    return usage


def _credits(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value)


def usage_charge_items(app_id: str, skill_id: str,
                       groups: Sequence[Any]) -> List[Tuple[int, int, Dict[str, Any]]]:
    """``(group index, credits, group)`` of every charged group of a usage-billed search skill.

    Only successful groups with results are charged, never installed-only groups
    (checked against the server registry).
    """
    from backend.shared.app_packages.billing import is_installed_only_group

    items: List[Tuple[int, int, Dict[str, Any]]] = []
    for index, group in enumerate(groups):
        if not isinstance(group, dict) or group.get("error") or not group.get("results"):
            continue
        if is_installed_only_group(app_id, skill_id, group):
            continue
        usage = group.get("usage")
        credits = _credits(usage.get("credits_charged")) if isinstance(usage, dict) else None
        if credits:
            items.append((index, credits, group))
    return items


def usage_details(group: Any) -> Dict[str, Any]:
    """Usage record fields of one charged group (model, tokens, web search requests)."""
    usage = group.get("usage") if isinstance(group, dict) else None
    if not isinstance(usage, dict):
        return {}
    details: Dict[str, Any] = {}
    if usage.get("model"):
        details["model_used"] = usage["model"]
    for key in ("input_tokens", "output_tokens", "web_search_requests"):
        if usage.get(key) is not None:
            details[key] = usage[key]
    return details
