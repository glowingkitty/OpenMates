"""Validate the customer-facing LLM billing snapshot before persistence.

This is a public billing record. In particular, provider invoices, prompt text,
private supplier costs and arbitrary metadata must never enter it.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from typing import Any


TOP_LEVEL = frozenset({
    "schema_version", "input_tokens", "uncached_input_tokens", "cache_read_input_tokens",
    "cache_creation_input_tokens", "output_tokens", "usage_source", "entries",
    "raw_credits", "rounding_adjustment", "credits_charged", "settlement_state",
})
ENTRY_FIELDS = frozenset({
    "model_id", "inference_host", "pricing_version", "input_tokens",
    "uncached_input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
    "cache_creation_5m_input_tokens", "cache_creation_1h_input_tokens", "output_tokens",
    "rates", "category_credits", "raw_credits", "write_billing",
    "billing_mode", "billed_input_tokens",
})
CATEGORIES = frozenset({"input", "cache_read", "cache_write", "cache_write_1h", "output"})
COUNTS = frozenset({
    "input_tokens", "uncached_input_tokens", "cache_read_input_tokens",
    "cache_creation_input_tokens", "cache_creation_5m_input_tokens",
    "cache_creation_1h_input_tokens", "output_tokens",
})


def _decimal_string(value: Any, *, positive: bool = False, nonnegative: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    try:
        number = Decimal(value)
        return number.is_finite() and (not positive or number > 0) and (not nonnegative or number >= 0)
    except InvalidOperation:
        return False


def validate_public_llm_usage_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict) or frozenset(receipt) not in {TOP_LEVEL, TOP_LEVEL | {"requested_credits"}}:
        raise ValueError("Invalid LLM usage receipt fields")
    if receipt["schema_version"] != 1 or type(receipt["credits_charged"]) is not int or receipt["credits_charged"] < 0:
        raise ValueError("Invalid LLM usage receipt version or charge")
    if receipt["settlement_state"] not in {"pending", "settled"}:
        raise ValueError("Invalid LLM usage settlement state")
    if "requested_credits" in receipt and (type(receipt["requested_credits"]) is not int or receipt["requested_credits"] < 0):
        raise ValueError("Invalid requested credits")
    if not isinstance(receipt["usage_source"], str) or not receipt["usage_source"]:
        raise ValueError("Invalid LLM usage source")
    if not _decimal_string(receipt["raw_credits"], nonnegative=True) or not _decimal_string(receipt["rounding_adjustment"]):
        raise ValueError("Invalid LLM usage credit totals")
    if not isinstance(receipt["entries"], list):
        raise ValueError("Invalid LLM usage entries")
    for item in [receipt, *receipt["entries"]]:
        if not isinstance(item, dict):
            raise ValueError("Invalid LLM usage entry")
        for key in COUNTS & set(item):
            value = item[key]
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Invalid LLM usage token count")
    for entry in receipt["entries"]:
        required_fields = ENTRY_FIELDS - {"write_billing", "billing_mode", "billed_input_tokens"}
        if not required_fields.issubset(entry) or not set(entry).issubset(ENTRY_FIELDS):
            raise ValueError("Invalid LLM usage entry fields")
        if "write_billing" in entry and entry["write_billing"] not in {"included_in_input", "separate"}:
            raise ValueError("Invalid cache write billing mode")
        if "billing_mode" in entry and entry["billing_mode"] not in {"cache_aware", "ordinary_input"}:
            raise ValueError("Invalid LLM usage billing mode")
        if "billed_input_tokens" in entry and (
            type(entry["billed_input_tokens"]) is not int or entry["billed_input_tokens"] < 0
        ):
            raise ValueError("Invalid billed input token count")
        for key in ("model_id", "pricing_version"):
            if not isinstance(entry[key], str) or not entry[key]:
                raise ValueError("Invalid LLM usage model or pricing identity")
        if entry["inference_host"] is not None and not isinstance(entry["inference_host"], str):
            raise ValueError("Invalid LLM inference host")
        rates = entry["rates"]
        categories = entry["category_credits"]
        if not isinstance(rates, dict) or not set(rates).issubset(CATEGORIES):
            raise ValueError("Invalid LLM usage price categories")
        if not all(value is None or _decimal_string(value, positive=True) for value in rates.values()):
            raise ValueError("Invalid LLM usage rate")
        if not isinstance(categories, dict) or set(categories) != CATEGORIES:
            raise ValueError("Invalid LLM usage credit categories")
        if not all(_decimal_string(value, nonnegative=True) for value in categories.values()):
            raise ValueError("Invalid LLM usage category credit")
        if not _decimal_string(entry["raw_credits"], nonnegative=True):
            raise ValueError("Invalid LLM usage entry total")
    return receipt


def settle_public_llm_usage_receipt(receipt: Any, charged_credits: int) -> dict[str, Any]:
    """Return a fresh settled snapshot with reconciliation to the actual debit."""
    if not isinstance(receipt, dict) or type(charged_credits) is not int or charged_credits < 0:
        raise ValueError("Invalid LLM usage receipt or debit")
    validate_public_llm_usage_receipt(receipt)
    result = dict(receipt)
    try:
        raw_string = result["raw_credits"]
        raw_credits = Decimal(raw_string)
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid raw_credits in LLM usage receipt") from exc
    prospective_credits = result["credits_charged"]
    if charged_credits != prospective_credits:
        result.setdefault("requested_credits", prospective_credits)
    result["credits_charged"] = charged_credits
    with localcontext() as context:
        context.prec = max(28, len(raw_string) + len(str(charged_credits)) + 4)
        result["rounding_adjustment"] = format(Decimal(charged_credits) - raw_credits, "f")
    result["settlement_state"] = "settled"
    return validate_public_llm_usage_receipt(result)
