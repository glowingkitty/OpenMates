"""The web as one more source of a search skill, next to its API providers.

Public pages found by web search are turned into result rows by
``backend/shared/python_utils/web_result_extraction.py``. The rows are returned
as an ``InstalledProviderOutcome`` with the reserved provider id ``web`` so they
pass through the same merge, deduplication, ranking and progress reporting as
provider results. The outcome's ``usage`` reports what the source used (answered
web search requests, extraction model and tokens), so a skill that bills by
usage can charge it (backend/shared/python_utils/web_source_billing.py). The
source never fails a request: an error only becomes a warning of that request.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

from backend.shared.app_packages.provider_dispatch import InstalledProviderOutcome
from backend.shared.python_utils.web_result_extraction import (
    KIND_EVENT, KIND_PRODUCT, WEB_PROVIDER_ID, WebExtraction, extract_web_results,
)

logger = logging.getLogger(__name__)

# Skills served by the generic delegate that also search the web.
DELEGATE_WEB_KINDS: Dict[Tuple[str, str], str] = {("shopping", "search_products"): KIND_PRODUCT}
WEB_SOURCE_SECONDS = 18.0
WEB_RESULT_LIMIT = 20
DEFAULT_COUNTRY = "us"
DEFAULT_LANGUAGE = "en"
# Search market per request country; other countries use the default market.
_MARKETS: Dict[str, Tuple[str, str]] = {
    "de": ("de", "de"), "at": ("at", "de"), "ch": ("ch", "de"), "fr": ("fr", "fr"), "es": ("es", "es"),
    "it": ("it", "it"), "nl": ("nl", "nl"), "gb": ("gb", "en"), "uk": ("gb", "en"), "us": ("us", "en"),
    "ca": ("ca", "en"), "au": ("au", "en"), "jp": ("jp", "ja"),
}
_REQUEST_FACTS: FrozenSet[str] = frozenset({
    "query", "location", "start_date", "end_date", "event_type", "relevance_criteria", "country",
    "min_price", "max_price", "brand",
})

__all__ = ["DELEGATE_WEB_KINDS", "KIND_EVENT", "KIND_PRODUCT", "WEB_PROVIDER_ID", "delegate_web_kind",
           "run_web_source", "web_market", "web_usage"]


def delegate_web_kind(app_id: str, skill_id: str) -> Optional[str]:
    """The result kind the web source produces for a delegated skill, if it has one."""
    return DELEGATE_WEB_KINDS.get((app_id, skill_id))


def web_market(country: Any) -> Tuple[str, str]:
    """Search country and language for a request's ISO country code."""
    code = country.strip().lower() if isinstance(country, str) else ""
    return _MARKETS.get(code, (DEFAULT_COUNTRY, DEFAULT_LANGUAGE))


async def run_web_source(kind: str, request_item: Mapping[str, Any], secrets_manager: Any, *,
                         limit: int = WEB_RESULT_LIMIT) -> InstalledProviderOutcome:
    """Search the web for one request item; only search facts leave the server."""
    facts = {key: request_item[key] for key in _REQUEST_FACTS if request_item.get(key) not in (None, "", [], {})}
    country, language = web_market(request_item.get("country"))
    # Created here so the usage counted before a timeout is still reported.
    extraction = WebExtraction()
    try:
        async with asyncio.timeout(WEB_SOURCE_SECONDS):
            await extract_web_results(kind, facts, secrets_manager=secrets_manager, limit=limit,
                                      country=country, language=language, outcome=extraction)
    except TimeoutError:
        logger.warning("[WebResults] Web source timed out kind=%s", kind)
        return InstalledProviderOutcome(WEB_PROVIDER_ID, error="Web results did not arrive in time.",
                                        usage=web_usage(extraction))
    return InstalledProviderOutcome(WEB_PROVIDER_ID, results=extraction.results, error=extraction.error,
                                    usage=web_usage(extraction))


def web_usage(extraction: WebExtraction) -> Dict[str, Any]:
    """What one web source run used: answered search requests plus extraction model and tokens."""
    return {"web_search_requests": extraction.search_requests, "model": extraction.model,
            "input_tokens": extraction.input_tokens, "output_tokens": extraction.output_tokens}
