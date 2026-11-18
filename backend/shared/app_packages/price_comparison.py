"""Price comparison across the providers of one product search request.

Installed providers and the web source each return their own offers. For a skill
in ``PRICE_COMPARED_SKILLS`` this module turns the merged offers of one request
item into a comparison:

1. exact product: when the request names a ``brand`` and/or ``model``, offers whose
   title (or brand field) lacks the brand, or lacks any model token that contains a
   digit (``X100`` but not ``X10`` or ``X100S``), are dropped, so accessories and
   neighbouring models do not pose as the cheapest offer. When no offer names the
   product, the similar offers stay and the summary says ``exact_product_found: false``;
2. condition: ``condition`` ``new`` or ``used`` drops offers that state another
   condition (offers that state none are kept);
3. total price: every offer with a known item price and shipping cost gets
   ``total_amount`` (item + shipping). With ``sort: price_asc`` offers are ordered by
   that total, falling back to the item price when shipping is unknown
   (``shipping_known: false``); offers without a price, or in another currency than
   most offers, follow in their previous order.

Each installed provider of a compared search runs for at most ``PROVIDER_SECONDS``.

Providers stay responsible for their own fields; nothing here invents a price,
shipping cost or condition. Architecture: docs/architecture/apps/instance-app-packages.md
("Price comparison").
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

PRICE_COMPARED_SKILLS: FrozenSet[Tuple[str, str]] = frozenset({("shopping", "search_products")})
PRICE_ORDER = "price_asc"
CONDITIONS = frozenset({"new", "used", "refurbished"})
TOTAL_FIELD = "total_amount"
# Each installed provider of a compared search gets at most this long. The skill's
# whole envelope is 20 s (30 s with photo ranking); a provider still running at the
# runner default (30 s) would cancel the comparison and lose every other shop's
# offers, while over this limit it fails alone as "did not respond in time".
PROVIDER_SECONDS = 14
_CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP", "chf": "CHF"}
_TOKEN = re.compile(r"[a-z0-9]+")


def compares_prices(app_id: str, skill_id: str) -> bool:
    return (app_id, skill_id) in PRICE_COMPARED_SKILLS


def wants_price_order(item: Mapping[str, Any]) -> bool:
    return item.get("sort") == PRICE_ORDER


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value >= 0 else None


def _tokens(text: Any) -> List[str]:
    return _TOKEN.findall(text.casefold()) if isinstance(text, str) else []


def offer_currency(result: Mapping[str, Any]) -> Optional[str]:
    """ISO currency of an offer from ``currency`` or ``currency_symbol``."""
    for field in ("currency", "currency_symbol"):
        value = result.get(field)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            return _CURRENCY_SYMBOLS.get(text.casefold(), text.upper()) if len(text) <= 3 else None
    return None


def with_total(result: Dict[str, Any]) -> Dict[str, Any]:
    """The offer with ``total_amount`` when item price and shipping cost are both known."""
    price = _number(result.get("price_amount"))
    shipping = _number(result.get("shipping_amount"))
    if price is not None and shipping is not None and _number(result.get(TOTAL_FIELD)) is None:
        return {**result, TOTAL_FIELD: round(price + shipping, 2)}
    return result


def comparable_price(result: Mapping[str, Any]) -> Optional[float]:
    """Total incl. shipping when known, else the item price."""
    total = _number(result.get(TOTAL_FIELD))
    return total if total is not None else _number(result.get("price_amount"))


def matches_product(result: Mapping[str, Any], brand: Optional[str], model: Optional[str]) -> bool:
    """True when the offer names the requested brand and every model token with a digit."""
    title_tokens = set(_tokens(result.get("title"))) | set(_tokens(result.get("brand")))
    brand_tokens = _tokens(brand)
    if brand_tokens and not all(token in title_tokens for token in brand_tokens):
        return False
    model_tokens = [token for token in _tokens(model) if any(char.isdigit() for char in token)]
    return all(token in title_tokens for token in model_tokens)


def matches_condition(result: Mapping[str, Any], condition: Any) -> bool:
    stated = result.get("condition")
    if condition not in ("new", "used") or not isinstance(stated, str) or stated.casefold() not in CONDITIONS:
        return True
    stated = stated.casefold()
    return stated == condition or (condition == "used" and stated == "refurbished")


def order_by_total_price(results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cheapest first by total (or item price); unpriced and other-currency offers keep their order after."""
    currencies = Counter(offer_currency(result) for result in results if comparable_price(result) is not None)
    currencies.pop(None, None)
    main_currency = currencies.most_common(1)[0][0] if currencies else None

    def key(indexed: Tuple[int, Dict[str, Any]]) -> Tuple[int, float, int]:
        index, result = indexed
        price = comparable_price(result)
        currency = offer_currency(result)
        comparable = price is not None and (main_currency is None or currency in (None, main_currency))
        return (0, price, index) if comparable else (1, 0.0, index)

    return [result for _index, result in sorted(enumerate(results), key=key)]


def compare_offers(results: Sequence[Dict[str, Any]], item: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Filtered, totalled (and, for ``price_asc``, price-ordered) offers plus a summary for the group."""
    brand = item.get("brand") if isinstance(item.get("brand"), str) else None
    model = item.get("model") if isinstance(item.get("model"), str) else None
    in_condition = [result for result in results if matches_condition(result, item.get("condition"))]
    exact = [result for result in in_condition if matches_product(result, brand, model)]
    # No offer names the exact product: keep the similar ones, flagged, rather than none.
    kept = [with_total(result) for result in (exact or in_condition)]
    for result in kept:
        if _number(result.get("price_amount")) is not None:
            result["shipping_known"] = _number(result.get("shipping_amount")) is not None
    summary: Dict[str, Any] = {"offers_considered": len(results), "offers_kept": len(kept)}
    if brand or model:
        summary["exact_product"] = " ".join(part for part in (brand, model) if part)
        summary["exact_product_found"] = bool(exact)
    if wants_price_order(item):
        kept = order_by_total_price(kept)
        summary["order"] = "total_price_incl_shipping"
    return kept, summary
