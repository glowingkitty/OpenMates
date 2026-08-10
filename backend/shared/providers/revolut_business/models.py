# backend/shared/providers/revolut_business/models.py
#
# Normalized Pydantic models for the Revolut Business read-only provider wrapper.
# These schemas intentionally model only account and transaction read surfaces;
# payments, transfers, cards, and mutable resources are outside Finance V1 scope.
#
# Spec: docs/specs/finance-check-accounts-v1/spec.yml

from __future__ import annotations

from pydantic import BaseModel


class RevolutAccount(BaseModel):
    id: str
    name: str = ""
    balance: float | None = None
    currency: str
    state: str = "unknown"
    updated_at: str | None = None


class RevolutTransaction(BaseModel):
    id: str
    account_id: str
    created_at: str
    completed_at: str | None = None
    amount: float
    currency: str
    description: str = ""
    state: str = "unknown"
    category_hint: str | None = None
