# backend/shared/providers/revolut_business/client.py
#
# Pure async Revolut Business API wrapper for read-only account data.
# It accepts broker-issued short-lived access tokens and deliberately exposes
# only GET /accounts and GET /transactions style methods for Finance V1.
#
# Spec: docs/specs/finance-check-accounts-v1/spec.yml

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import httpx

from .models import RevolutAccount, RevolutTransaction

logger = logging.getLogger(__name__)

REVOLUT_BUSINESS_API_BASE_URL = "https://b2b.revolut.com/api/1.0/"
REVOLUT_BUSINESS_SANDBOX_API_BASE_URL = "https://sandbox-b2b.revolut.com/api/1.0/"
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_TRANSACTIONS_PER_REQUEST = 1000


class RevolutBusinessError(RuntimeError):
    """Sanitized Revolut Business provider failure."""

    def __init__(self, code: str, message: str, *, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class RevolutBusinessClient:
    """Minimal read-only Revolut Business API client."""

    provider_name = "Revolut Business"

    def __init__(
        self,
        *,
        access_token: str,
        base_url: str = REVOLUT_BUSINESS_API_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("access_token is required")
        self.access_token = access_token
        self.base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self.timeout = timeout
        self._http_client = http_client

    async def list_accounts(self) -> list[RevolutAccount]:
        payload = await self._get_json("accounts")
        items = payload if isinstance(payload, list) else payload.get("accounts", [])
        return [_normalize_account(item) for item in items if isinstance(item, dict)]

    async def get_account(self, account_id: str) -> RevolutAccount:
        if not account_id:
            raise ValueError("account_id is required")
        return _normalize_account(await self._get_json(f"accounts/{account_id}"))

    async def list_transactions(
        self,
        *,
        account_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        count: int = 100,
        state: str | None = None,
    ) -> list[RevolutTransaction]:
        params: dict[str, Any] = {"count": max(1, min(int(count or 100), MAX_TRANSACTIONS_PER_REQUEST))}
        if account_id:
            params["account"] = account_id
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if state:
            params["state"] = state
        payload = await self._get_json("transactions", params=params)
        items = payload if isinstance(payload, list) else payload.get("transactions", [])
        return [_normalize_transaction(item) for item in items if isinstance(item, dict)]

    async def get_transaction(self, transaction_id: str) -> RevolutTransaction:
        if not transaction_id:
            raise ValueError("transaction_id is required")
        return _normalize_transaction(await self._get_json(f"transactions/{transaction_id}"))

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        client = self._http_client or httpx.AsyncClient(timeout=self.timeout)
        close_client = self._http_client is None
        try:
            response = await client.get(
                urljoin(self.base_url, path),
                params=params,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            if response.is_error:
                logger.warning("Revolut Business GET %s failed: status=%s", path, response.status_code)
                raise RevolutBusinessError(
                    "provider_http_error",
                    f"Revolut Business returned HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            return response.json()
        except httpx.HTTPError as exc:
            logger.warning("Revolut Business GET %s request failed: %s", path, exc)
            raise RevolutBusinessError("provider_unavailable", "Revolut Business request failed") from exc
        finally:
            if close_client:
                await client.aclose()


def _normalize_account(item: dict[str, Any]) -> RevolutAccount:
    balance = item.get("balance")
    return RevolutAccount(
        id=str(item.get("id") or item.get("account_id") or ""),
        name=str(item.get("name") or item.get("label") or ""),
        balance=float(balance) if balance is not None else None,
        currency=str(item.get("currency") or "").upper(),
        state=str(item.get("state") or "unknown").lower(),
        updated_at=item.get("updated_at") or item.get("created_at"),
    )


def _normalize_transaction(item: dict[str, Any]) -> RevolutTransaction:
    amount = item.get("amount")
    if amount is None and isinstance(item.get("legs"), list) and item["legs"]:
        amount = item["legs"][0].get("amount")
    account_id = item.get("account_id") or item.get("account")
    if not account_id and isinstance(item.get("legs"), list) and item["legs"]:
        account_id = item["legs"][0].get("account_id") or item["legs"][0].get("account")
    currency = item.get("currency")
    if not currency and isinstance(item.get("legs"), list) and item["legs"]:
        currency = item["legs"][0].get("currency")
    return RevolutTransaction(
        id=str(item.get("id") or item.get("transaction_id") or item.get("request_id") or ""),
        account_id=str(account_id or ""),
        created_at=str(item.get("created_at") or item.get("completed_at") or ""),
        completed_at=item.get("completed_at"),
        amount=float(amount or 0),
        currency=str(currency or "").upper(),
        description=str(item.get("reference") or item.get("description") or item.get("reason") or "Revolut transaction"),
        state=str(item.get("state") or "unknown").lower(),
        category_hint=item.get("category_hint"),
    )
