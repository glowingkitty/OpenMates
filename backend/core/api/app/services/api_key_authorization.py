"""API-key authorization helpers for SDK and REST access.

Purpose: centralize API-key metadata normalization, scope checks, and budgets.
Architecture: docs/specs/sdk-packages-v1/spec.yml.
Security: callers must enforce these checks server-side before executing work.
Scope: pure authorization logic with no Directus or request dependencies.
"""

from dataclasses import dataclass
from typing import Any


VALID_CREDIT_PERIODS = {"daily", "weekly", "monthly", "lifetime"}


@dataclass(frozen=True)
class ApiKeyScopeError(PermissionError):
    """Raised when an API key lacks a required scope."""

    missing_scope: str

    def __str__(self) -> str:
        return f"API key missing required scope: {self.missing_scope}"


@dataclass(frozen=True)
class ApiKeyBudgetError(PermissionError):
    """Raised when an API-key request would exceed its credit budget."""

    period: str
    limit_credits: int
    remaining_credits: int

    def __str__(self) -> str:
        return (
            f"API key {self.period} credit limit exceeded: "
            f"{self.remaining_credits} credits remaining"
        )


class ApiKeyAuthorizationService:
    """Normalize and enforce API-key permission metadata."""

    def normalize_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        normalized = dict(metadata or {})
        normalized.setdefault("full_access", True)
        normalized.setdefault("scopes", {})

        credit_limit = normalized.get("credit_limit")
        if credit_limit:
            normalized["credit_limit"] = self._normalize_credit_limit(credit_limit)

        return normalized

    def require_chat_scope(self, metadata: dict[str, Any], required_scope: str) -> None:
        if metadata.get("full_access", True):
            return

        chat_scopes = metadata.get("scopes", {}).get("chat") or []
        if required_scope not in chat_scopes:
            raise ApiKeyScopeError(required_scope)

    def require_scope(
        self,
        metadata: dict[str, Any],
        group: str,
        required_scope: str,
    ) -> None:
        if metadata.get("full_access", True):
            return

        scopes = metadata.get("scopes", {}).get(group) or []
        if required_scope not in scopes:
            raise ApiKeyScopeError(required_scope)

    def require_app_skill_scope(
        self,
        metadata: dict[str, Any],
        app_id: str,
        skill_id: str,
    ) -> None:
        if metadata.get("full_access", True):
            return

        apps_scope = metadata.get("scopes", {}).get("apps") or {}
        mode = apps_scope.get("mode", "all")
        if mode == "all":
            return

        skill_scope = f"{app_id}:{skill_id}"
        allowed_skills = set(apps_scope.get("allowed_skills") or [])
        allowed_apps = set(apps_scope.get("allowed_apps") or [])
        if skill_scope in allowed_skills or app_id in allowed_apps:
            return

        raise ApiKeyScopeError(f"skill:{skill_scope}")

    def require_budget(
        self,
        metadata: dict[str, Any],
        *,
        already_spent: int,
        requested_credits: int,
    ) -> None:
        credit_limit = metadata.get("credit_limit")
        if not credit_limit:
            return

        limit_credits = int(credit_limit["credits"])
        remaining_credits = max(limit_credits - int(already_spent), 0)
        if int(requested_credits) > remaining_credits:
            raise ApiKeyBudgetError(
                period=credit_limit["period"],
                limit_credits=limit_credits,
                remaining_credits=remaining_credits,
            )

    def _normalize_credit_limit(self, credit_limit: dict[str, Any]) -> dict[str, Any]:
        if "period" in credit_limit and "credits" in credit_limit:
            period = credit_limit["period"]
            if period not in VALID_CREDIT_PERIODS:
                raise ValueError(f"Unsupported credit limit period: {period}")
            return {"period": period, "credits": int(credit_limit["credits"])}

        periods = [period for period in VALID_CREDIT_PERIODS if period in credit_limit]
        if len(periods) != 1:
            raise ValueError("API keys support exactly one credit limit period")

        period = periods[0]
        return {"period": period, "credits": int(credit_limit[period])}
