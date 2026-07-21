# backend/shared/python_utils/finance_accounts.py
#
# Shared Finance account normalization utilities.
# This module is provider- and skill-agnostic: CSV importers, Revolut wrappers,
# and app skills can all use the same normalized account/transaction models.
# Raw counterparty names may enter these helpers transiently, but public outputs
# use category-aware placeholders for privacy-safe persistence and LLM context.
#
# Spec: docs/specs/finance-check-accounts-v1/spec.yml

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from pydantic import BaseModel, Field

REQUIRED_CSV_COLUMNS = {
    "transaction_id",
    "account_id",
    "account_label",
    "posted_at",
    "description",
    "amount",
    "currency",
}
OPTIONAL_CSV_COLUMNS = {
    "direction",
    "balance_after",
    "category_hint",
    "counterparty_type",
    "source_name",
    "notes",
}
SUPPORTED_PERIODS = {"monthly", "quarterly", "yearly", "custom"}
SUPPORTED_PROJECTION_HORIZONS = {"monthly", "quarterly", "yearly"}
EXPENSE_DIRECTIONS = {"expense", "debit", "out", "outflow"}
INCOME_DIRECTIONS = {"income", "credit", "in", "inflow"}
PLACEHOLDER_SAFE_PATTERN = re.compile(r"[^A-Z0-9]+")
MONEY_QUANT = Decimal("0.01")


class FinanceCSVTemplateError(ValueError):
    """Raised when a statement does not use the canonical template."""


class NormalizedAccount(BaseModel):
    account_ref: str
    source_ref: str
    display_label: str
    currency: str
    balance: float | None = None
    balance_as_of: str | None = None


class NormalizedTransaction(BaseModel):
    transaction_ref: str
    account_ref: str
    source_ref: str
    posted_at: str
    amount: float
    currency: str
    direction: str
    category: str
    counterparty_placeholder: str
    state: str = "completed"


class FinanceStatementResult(BaseModel):
    accounts: list[NormalizedAccount] = Field(default_factory=list)
    transactions: list[NormalizedTransaction] = Field(default_factory=list)
    public_mappings: list[dict[str, str]] = Field(default_factory=list)


class FinancePrivacy(BaseModel):
    placeholder_mappings_ref: str = "owner_encrypted_embed_pii_mappings"
    raw_names_persisted: bool = False
    public_mappings: list[dict[str, str]] = Field(default_factory=list)


class FinanceOverview(BaseModel):
    accounts: list[NormalizedAccount]
    transactions: list[NormalizedTransaction]
    summaries: dict[str, Any]
    privacy: FinancePrivacy
    filter_options: dict[str, list[str]]


class FinancePrivacyRedactor:
    """Create stable category-aware placeholders for raw counterparty values."""

    def __init__(self) -> None:
        self._by_original: dict[str, dict[str, str]] = {}
        self._counts: dict[tuple[str, str], int] = defaultdict(int)

    def placeholder_for(
        self,
        original: str,
        *,
        category: str | None = None,
        counterparty_type: str | None = None,
    ) -> str:
        normalized_original = " ".join(str(original or "").split()).strip()
        if not normalized_original:
            normalized_original = "Unknown counterparty"
        existing = self._by_original.get(normalized_original.casefold())
        if existing:
            return existing["placeholder"]

        safe_type = _safe_placeholder_part(counterparty_type or "merchant")
        safe_category = _safe_placeholder_part(category or "uncategorized")
        key = (safe_type, safe_category)
        self._counts[key] += 1
        placeholder = f"[{safe_type}_{safe_category}_{self._counts[key]:03d}]"
        self._by_original[normalized_original.casefold()] = {
            "original": normalized_original,
            "placeholder": placeholder,
            "category": _normalize_category(category),
            "counterparty_type": _normalize_counterparty_type(counterparty_type),
        }
        return placeholder

    def public_mapping_summary(self) -> list[dict[str, str]]:
        return [
            {
                "placeholder": item["placeholder"],
                "category": item["category"],
                "counterparty_type": item["counterparty_type"],
            }
            for item in self._by_original.values()
        ]

    def owner_mapping_payload(self) -> list[dict[str, str]]:
        return list(self._by_original.values())


def parse_bank_statement_text(
    content: str,
    *,
    filename: str = "statement.csv",
    source_ref: str | None = None,
    redactor: FinancePrivacyRedactor | None = None,
) -> FinanceStatementResult:
    """Parse the canonical OpenMates CSV/TSV bank-statement template."""

    source = source_ref or f"csv:{filename}"
    active_redactor = redactor or FinancePrivacyRedactor()
    delimiter = "\t" if filename.lower().endswith(".tsv") or "\t" in content.splitlines()[0] else ","
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    fieldnames = {str(field or "").strip() for field in (reader.fieldnames or [])}
    missing = sorted(REQUIRED_CSV_COLUMNS - fieldnames)
    if missing:
        raise FinanceCSVTemplateError(
            "CSV must use the canonical OpenMates bank-statement template; "
            f"missing required columns: {', '.join(missing)}"
        )

    accounts: dict[str, NormalizedAccount] = {}
    transactions: list[NormalizedTransaction] = []
    for row_index, raw_row in enumerate(reader, start=2):
        row = {str(key or "").strip(): (value or "").strip() for key, value in raw_row.items()}
        if not any(row.values()):
            continue
        account_ref = _required(row, "account_id", row_index)
        posted_at = _normalize_posted_at(_required(row, "posted_at", row_index), row_index)
        amount = _parse_decimal(_required(row, "amount", row_index), "amount", row_index)
        currency = _normalize_currency(_required(row, "currency", row_index), row_index)
        category = _normalize_category(row.get("category_hint"))
        counterparty_type = _normalize_counterparty_type(row.get("counterparty_type"))
        placeholder = active_redactor.placeholder_for(
            _required(row, "description", row_index),
            category=category,
            counterparty_type=counterparty_type,
        )
        balance = _parse_optional_decimal(row.get("balance_after"), "balance_after", row_index)
        accounts[account_ref] = NormalizedAccount(
            account_ref=account_ref,
            source_ref=source,
            display_label=_required(row, "account_label", row_index),
            currency=currency,
            balance=float(balance) if balance is not None else accounts.get(account_ref, NormalizedAccount(
                account_ref=account_ref,
                source_ref=source,
                display_label=_required(row, "account_label", row_index),
                currency=currency,
            )).balance,
            balance_as_of=posted_at,
        )
        transaction_id = _required(row, "transaction_id", row_index)
        transactions.append(
            NormalizedTransaction(
                transaction_ref=f"{source}:{transaction_id}",
                account_ref=account_ref,
                source_ref=source,
                posted_at=posted_at,
                amount=float(amount),
                currency=currency,
                direction=_normalize_direction(row.get("direction"), amount),
                category=category,
                counterparty_placeholder=placeholder,
                state="completed",
            )
        )

    return FinanceStatementResult(
        accounts=list(accounts.values()),
        transactions=transactions,
        public_mappings=active_redactor.public_mapping_summary(),
    )


def build_finance_overview(
    *,
    accounts: list[NormalizedAccount],
    transactions: list[NormalizedTransaction],
    period: str,
    projection_horizon: str,
    redactor: FinancePrivacyRedactor,
    start_date: str | None = None,
    end_date: str | None = None,
    account_filters: list[str] | None = None,
    source_filters: list[str] | None = None,
    category_filters: list[str] | None = None,
    direction_filter: str | None = None,
    state_filters: list[str] | None = None,
    placeholder_filters: list[str] | None = None,
) -> FinanceOverview:
    normalized_period = _normalize_period(period)
    horizon = _normalize_projection_horizon(projection_horizon)
    filters_applied = _normalize_filters_applied(
        start_date=start_date,
        end_date=end_date,
        account_filters=account_filters,
        source_filters=source_filters,
        category_filters=category_filters,
        direction_filter=direction_filter,
        state_filters=state_filters,
        placeholder_filters=placeholder_filters,
    )
    filtered_transactions = _filter_transactions(transactions, filters_applied)
    filtered_accounts = _filter_accounts(accounts, filtered_transactions, filters_applied)
    completed = [item for item in filtered_transactions if item.state != "cancelled"]
    income_total = _money(sum((_decimal(item.amount) for item in completed if item.direction == "income"), Decimal("0")))
    expense_total = _money(sum((abs(_decimal(item.amount)) for item in completed if item.direction == "expense"), Decimal("0")))
    by_category: dict[str, dict[str, float]] = {}
    for item in completed:
        category = item.category or "uncategorized"
        bucket = by_category.setdefault(category, {"income": 0.0, "expense": 0.0, "net": 0.0})
        amount = _decimal(item.amount)
        if item.direction == "expense":
            bucket["expense"] = _money(_decimal(bucket["expense"]) + abs(amount))
        elif item.direction == "income":
            bucket["income"] = _money(_decimal(bucket["income"]) + amount)
        bucket["net"] = _money(_decimal(bucket["income"]) - _decimal(bucket["expense"]))

    summaries = {
        "period": normalized_period,
        "income_total": income_total,
        "expense_total": expense_total,
        "net_total": _money(_decimal(income_total) - _decimal(expense_total)),
        "by_category": by_category,
        "time_series": _build_time_series(completed, normalized_period),
        "recurring_items": _detect_recurring_items(completed),
        "projection": _build_projection(expense_total, horizon, completed),
        "confidence": _confidence_for_history(completed),
        "filters_applied": filters_applied,
    }
    return FinanceOverview(
        accounts=filtered_accounts,
        transactions=filtered_transactions,
        summaries=summaries,
        privacy=FinancePrivacy(public_mappings=redactor.public_mapping_summary()),
        filter_options={
            "accounts": sorted({item.account_ref for item in accounts}),
            "sources": sorted({item.source_ref for item in accounts} | {item.source_ref for item in transactions}),
            "categories": sorted({item.category for item in transactions}),
            "directions": sorted({item.direction for item in transactions}),
            "states": sorted({item.state for item in transactions}),
            "placeholders": sorted({item.counterparty_placeholder for item in transactions}),
        },
    )


def _normalize_filters_applied(
    *,
    start_date: str | None,
    end_date: str | None,
    account_filters: list[str] | None,
    source_filters: list[str] | None,
    category_filters: list[str] | None,
    direction_filter: str | None,
    state_filters: list[str] | None,
    placeholder_filters: list[str] | None,
) -> dict[str, Any]:
    normalized_direction = str(direction_filter or "").strip().lower()
    if normalized_direction and normalized_direction not in {"income", "expense"}:
        raise ValueError("direction_filter must be income or expense")
    return {
        "start_date": _normalize_optional_iso_date(start_date, "start_date"),
        "end_date": _normalize_optional_iso_date(end_date, "end_date"),
        "account_filters": _normalize_string_filter_list(account_filters),
        "source_filters": _normalize_string_filter_list(source_filters),
        "category_filters": [_normalize_category(item) for item in _normalize_string_filter_list(category_filters)],
        "direction_filter": normalized_direction or None,
        "state_filters": [item.lower() for item in _normalize_string_filter_list(state_filters)],
        "placeholder_filters": _normalize_string_filter_list(placeholder_filters),
    }


def _normalize_string_filter_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _normalize_optional_iso_date(value: str | None, field_name: str) -> str | None:
    if value is None or not str(value).strip():
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 date") from exc


def _filter_transactions(transactions: list[NormalizedTransaction], filters: dict[str, Any]) -> list[NormalizedTransaction]:
    result: list[NormalizedTransaction] = []
    account_set = set(filters["account_filters"])
    source_set = set(filters["source_filters"])
    category_set = set(filters["category_filters"])
    state_set = set(filters["state_filters"])
    placeholder_set = set(filters["placeholder_filters"])
    for item in transactions:
        posted_at = _normalize_optional_iso_date(item.posted_at, "posted_at") if item.posted_at else None
        if filters["start_date"] and (not posted_at or posted_at < filters["start_date"]):
            continue
        if filters["end_date"] and (not posted_at or posted_at > filters["end_date"]):
            continue
        if account_set and item.account_ref not in account_set:
            continue
        if source_set and item.source_ref not in source_set:
            continue
        if category_set and item.category not in category_set:
            continue
        if filters["direction_filter"] and item.direction != filters["direction_filter"]:
            continue
        if state_set and item.state.lower() not in state_set:
            continue
        if placeholder_set and item.counterparty_placeholder not in placeholder_set:
            continue
        result.append(item)
    return result


def _filter_accounts(
    accounts: list[NormalizedAccount],
    transactions: list[NormalizedTransaction],
    filters: dict[str, Any],
) -> list[NormalizedAccount]:
    transaction_accounts = {item.account_ref for item in transactions}
    account_set = set(filters["account_filters"])
    source_set = set(filters["source_filters"])
    return [
        account
        for account in accounts
        if (not account_set or account.account_ref in account_set)
        and (not source_set or account.source_ref in source_set)
        and (account.account_ref in transaction_accounts or not transactions)
    ]


def _build_time_series(transactions: list[NormalizedTransaction], period: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, float]] = {}
    for item in transactions:
        bucket_id = _time_series_bucket(item.posted_at, period)
        bucket = buckets.setdefault(bucket_id, {"income": 0.0, "expense": 0.0, "net": 0.0, "transaction_count": 0})
        amount = _decimal(item.amount)
        if item.direction == "expense":
            bucket["expense"] = _money(_decimal(bucket["expense"]) + abs(amount))
        elif item.direction == "income":
            bucket["income"] = _money(_decimal(bucket["income"]) + amount)
        bucket["net"] = _money(_decimal(bucket["income"]) - _decimal(bucket["expense"]))
        bucket["transaction_count"] = int(bucket["transaction_count"]) + 1
    return [{"bucket": bucket_id, **buckets[bucket_id]} for bucket_id in sorted(buckets)]


def _time_series_bucket(posted_at: str, period: str) -> str:
    parsed = date.fromisoformat(str(posted_at or "")[:10])
    if period == "yearly":
        return f"{parsed.year:04d}"
    if period == "quarterly":
        quarter = ((parsed.month - 1) // 3) + 1
        return f"{parsed.year:04d}-Q{quarter}"
    return f"{parsed.year:04d}-{parsed.month:02d}"


def _required(row: dict[str, str], column: str, row_index: int) -> str:
    value = row.get(column, "").strip()
    if not value:
        raise FinanceCSVTemplateError(f"CSV row {row_index} is missing required value for {column}")
    return value


def _normalize_posted_at(value: str, row_index: int) -> str:
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise FinanceCSVTemplateError(f"CSV row {row_index} has invalid ISO posted_at") from exc


def _parse_decimal(value: str, column: str, row_index: int) -> Decimal:
    try:
        return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise FinanceCSVTemplateError(f"CSV row {row_index} has invalid numeric {column}") from exc


def _parse_optional_decimal(value: str | None, column: str, row_index: int) -> Decimal | None:
    if value is None or not value.strip():
        return None
    return _parse_decimal(value, column, row_index)


def _decimal(value: float | Decimal) -> Decimal:
    return Decimal(str(value))


def _money(value: Decimal) -> float:
    return float(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def _normalize_currency(value: str, row_index: int) -> str:
    currency = value.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise FinanceCSVTemplateError(f"CSV row {row_index} has invalid ISO 4217 currency")
    return currency


def _normalize_direction(value: str | None, amount: Decimal) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in EXPENSE_DIRECTIONS:
        return "expense"
    if normalized in INCOME_DIRECTIONS:
        return "income"
    return "expense" if amount < 0 else "income"


def _normalize_category(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "uncategorized").strip().lower()).strip("_")
    return normalized or "uncategorized"


def _normalize_counterparty_type(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "merchant").strip().lower()).strip("_")
    return normalized or "merchant"


def _safe_placeholder_part(value: str) -> str:
    safe = PLACEHOLDER_SAFE_PATTERN.sub("_", value.strip().upper()).strip("_")
    return safe or "UNKNOWN"


def _normalize_period(value: str) -> str:
    normalized = str(value or "monthly").strip().lower()
    if normalized not in SUPPORTED_PERIODS:
        raise ValueError(f"Unsupported Finance period: {value}")
    return normalized


def _normalize_projection_horizon(value: str) -> str:
    normalized = str(value or "monthly").strip().lower()
    if normalized not in SUPPORTED_PROJECTION_HORIZONS:
        raise ValueError(f"Unsupported Finance projection horizon: {value}")
    return normalized


def _build_projection(expense_total: float, horizon: str, transactions: list[NormalizedTransaction]) -> dict[str, Any]:
    multiplier = {"monthly": 1, "quarterly": 3, "yearly": 12}[horizon]
    return {
        "horizon": horizon,
        "expense_projection": _money(_decimal(expense_total) * Decimal(multiplier)),
        "basis": "observed_period_expense_total",
        "transaction_count": len(transactions),
    }


def _confidence_for_history(transactions: list[NormalizedTransaction]) -> dict[str, str]:
    if len(transactions) < 3:
        return {"level": "low", "note": "Projection is based on fewer than three transactions."}
    return {"level": "medium", "note": "Projection is deterministic and based on provided statement coverage."}


def _detect_recurring_items(transactions: list[NormalizedTransaction]) -> list[dict[str, Any]]:
    by_placeholder: dict[str, list[NormalizedTransaction]] = defaultdict(list)
    for item in transactions:
        if item.direction == "expense":
            by_placeholder[item.counterparty_placeholder].append(item)
    recurring: list[dict[str, Any]] = []
    for placeholder, items in by_placeholder.items():
        if len(items) >= 2:
            recurring.append(
                {
                    "counterparty_placeholder": placeholder,
                    "category": items[0].category,
                    "count": len(items),
                    "average_amount": _money(sum(abs(_decimal(item.amount)) for item in items) / Decimal(len(items))),
                }
            )
    return recurring
