# backend/apps/finance/skills/check_accounts.py
#
# Finance Check accounts skill implementation.
# It combines Revolut Business connected-account reads and canonical CSV/TSV
# statement inputs into one privacy-safe, filterable app-skill-use payload.
# Raw counterparty names are reduced to category-aware placeholders before the
# response is returned for persistence or LLM context.
#
# Spec: docs/specs/finance-check-accounts-v1/spec.yml

from __future__ import annotations

import logging
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.revolut_business import RevolutBusinessClient
from backend.shared.providers.revolut_business.client import (
    REVOLUT_BUSINESS_API_BASE_URL,
    REVOLUT_BUSINESS_SANDBOX_API_BASE_URL,
)
from backend.shared.python_utils.finance_accounts import (
    FinanceCSVTemplateError,
    FinanceOverview,
    FinancePrivacyRedactor,
    NormalizedAccount,
    NormalizedTransaction,
    build_finance_overview,
    parse_bank_statement_text,
)

logger = logging.getLogger(__name__)


class RevolutReadClient(Protocol):
    async def list_accounts(self) -> list[Any]: ...
    async def list_transactions(self, **kwargs: Any) -> list[Any]: ...


class CheckAccountsResponse(BaseModel):
    success: bool = False
    app_id: str = "finance"
    skill_id: str = "check_accounts"
    status: str = "finished"
    period: str = "monthly"
    account_count: int = 0
    transaction_count: int = 0
    overview: FinanceOverview | None = None
    summary: str | None = None
    warnings: list[dict[str, str]] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    ignore_fields_for_inference: list[str] = Field(
        default_factory=lambda: [
            "overview.privacy.public_mappings",
        ]
    )


class CheckAccountsSkill(BaseSkill):
    """Read and summarize account balances and transactions."""

    async def execute(
        self,
        period: str = "monthly",
        projection_horizon: str = "monthly",
        start_date: str | None = None,
        end_date: str | None = None,
        account_filters: list[str] | None = None,
        source_filters: list[str] | None = None,
        category_filters: list[str] | None = None,
        direction_filter: str | None = None,
        state_filters: list[str] | None = None,
        placeholder_filters: list[str] | None = None,
        csv_statements: list[dict[str, Any]] | None = None,
        connected_account_requests: list[dict[str, Any]] | None = None,
        connected_account_access_tokens: dict[str, str] | None = None,
        revolut_client_factory: Any | None = None,
        **kwargs: Any,
    ) -> CheckAccountsResponse:
        del kwargs
        redactor = FinancePrivacyRedactor()
        accounts: list[NormalizedAccount] = []
        transactions: list[NormalizedTransaction] = []
        warnings: list[dict[str, str]] = []

        try:
            for statement in csv_statements or []:
                filename = str(statement.get("filename") or "statement.csv")
                content = str(statement.get("content") or "")
                if not content.strip():
                    raise FinanceCSVTemplateError(f"CSV statement {filename} is empty")
                result = parse_bank_statement_text(
                    content,
                    filename=filename,
                    source_ref=f"csv:{filename}",
                    redactor=redactor,
                )
                accounts.extend(result.accounts)
                transactions.extend(result.transactions)

            for request in connected_account_requests or []:
                provider_result = await self._read_revolut_request(
                    request=request,
                    connected_account_access_tokens=connected_account_access_tokens,
                    redactor=redactor,
                    revolut_client_factory=revolut_client_factory,
                    start_date=start_date,
                    end_date=end_date,
                )
                accounts.extend(provider_result.accounts)
                transactions.extend(provider_result.transactions)
        except (FinanceCSVTemplateError, ValueError, PermissionError) as exc:
            return CheckAccountsResponse(
                success=False,
                period=period,
                error=str(exc),
                error_code="invalid_request" if not isinstance(exc, PermissionError) else "permission_required",
            )
        except Exception as exc:
            logger.error("finance.check_accounts failed: %s", exc, exc_info=True)
            return CheckAccountsResponse(
                success=False,
                period=period,
                error="Finance account analysis failed",
                error_code="provider_error",
            )

        if not accounts and not transactions:
            return CheckAccountsResponse(
                success=False,
                period=period,
                error="Check accounts requires at least one connected account request or CSV statement",
                error_code="missing_sources",
            )

        overview = build_finance_overview(
            accounts=accounts,
            transactions=transactions,
            period=period,
            projection_horizon=projection_horizon,
            redactor=redactor,
            start_date=start_date,
            end_date=end_date,
            account_filters=account_filters,
            source_filters=source_filters,
            category_filters=category_filters,
            direction_filter=direction_filter,
            state_filters=state_filters,
            placeholder_filters=placeholder_filters,
        )
        summary = (
            f"Finance overview for {len(overview.accounts)} account(s) and {len(overview.transactions)} transaction(s): "
            f"income {overview.summaries['income_total']}, expenses {overview.summaries['expense_total']}."
        )
        if len(overview.transactions) < 3:
            warnings.append({"code": "limited_history", "message": "Projection is based on limited transaction history."})
        return CheckAccountsResponse(
            success=True,
            period=period,
            account_count=len(overview.accounts),
            transaction_count=len(overview.transactions),
            overview=overview,
            summary=summary,
            warnings=warnings,
        )

    async def _read_revolut_request(
        self,
        *,
        request: dict[str, Any],
        connected_account_access_tokens: dict[str, str] | None,
        redactor: FinancePrivacyRedactor,
        revolut_client_factory: Any | None,
        start_date: str | None,
        end_date: str | None,
    ) -> Any:
        access_token_handle = str(request.get("access_token_handle") or "")
        if not access_token_handle:
            raise PermissionError("access_token_handle is required for Revolut Business account reads")
        if not connected_account_access_tokens or access_token_handle not in connected_account_access_tokens:
            raise PermissionError("connected account access token context is required")

        source_ref = str(request.get("source_ref") or "revolut_business")
        client_factory = revolut_client_factory or RevolutBusinessClient
        client: RevolutReadClient = client_factory(
            access_token=connected_account_access_tokens[access_token_handle],
            base_url=_revolut_base_url_for_request(request),
        )
        provider_accounts = await client.list_accounts()
        provider_transactions = await client.list_transactions(from_date=start_date, to_date=end_date)
        accounts = [_normalize_revolut_account(item, source_ref=source_ref) for item in provider_accounts]
        transactions = [
            _normalize_revolut_transaction(item, source_ref=source_ref, redactor=redactor)
            for item in provider_transactions
        ]
        return _ProviderNormalizationResult(accounts=accounts, transactions=transactions)

    @classmethod
    def resolve_preview_metadata(cls, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": "Revolut Business",
            "period": request.get("period") or "monthly",
            "csv_count": len(request.get("csv_statements") or []),
        }


class _ProviderNormalizationResult(BaseModel):
    accounts: list[NormalizedAccount]
    transactions: list[NormalizedTransaction]


def _revolut_base_url_for_request(request: dict[str, Any]) -> str:
    environment = str(request.get("environment") or "").strip().lower()
    if environment == "sandbox":
        return REVOLUT_BUSINESS_SANDBOX_API_BASE_URL
    return REVOLUT_BUSINESS_API_BASE_URL


def _normalize_revolut_account(item: Any, *, source_ref: str) -> NormalizedAccount:
    data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
    return NormalizedAccount(
        account_ref=str(data.get("id") or ""),
        source_ref=source_ref,
        display_label=str(data.get("name") or "Revolut Business account"),
        currency=str(data.get("currency") or "").upper(),
        balance=data.get("balance"),
        balance_as_of=data.get("updated_at"),
    )


def _normalize_revolut_transaction(
    item: Any,
    *,
    source_ref: str,
    redactor: FinancePrivacyRedactor,
) -> NormalizedTransaction:
    data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
    amount = float(data.get("amount") or 0)
    category = str(data.get("category_hint") or "uncategorized")
    placeholder = redactor.placeholder_for(
        str(data.get("description") or "Revolut transaction"),
        category=category,
        counterparty_type="merchant" if amount < 0 else "payer",
    )
    return NormalizedTransaction(
        transaction_ref=f"{source_ref}:{data.get('id') or ''}",
        account_ref=str(data.get("account_id") or ""),
        source_ref=source_ref,
        posted_at=str(data.get("completed_at") or data.get("created_at") or "")[:10],
        amount=amount,
        currency=str(data.get("currency") or "").upper(),
        direction="expense" if amount < 0 else "income",
        category=category,
        counterparty_placeholder=placeholder,
        state=str(data.get("state") or "unknown").lower(),
    )
